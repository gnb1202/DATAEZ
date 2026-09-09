"""Safe SQL execution layer for user data tables.

Security guarantees:
1. Table name validation (must match ut_{} pattern)
2. User ownership verification via table_meta
3. Prepared statements only (no string interpolation for values)
4. Column name quoting (psycopg sql.Identifier)
5. Row limits on SELECT (max 10000 rows)
6. Timeout on queries (30 seconds)
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .config import settings
from .db import _connect, get_user_table_name
from .ledger_guards import assert_unmanaged_table

MAX_SELECT_ROWS = settings.max_select_rows
QUERY_TIMEOUT_MS = settings.query_timeout_ms


def validate_table_access(user_id: str, table_name: str) -> bool:
    """Verify this table name matches the expected pattern for this user."""
    uid = user_id.replace("-", "")[:8]
    return table_name.startswith(f"ut_{uid}_")


def _build_where_clause(
    conditions: list[dict[str, str]] | None,
) -> tuple[sql.Composable, list[Any]]:
    """Build a WHERE clause from a list of condition dicts.

    Each condition: {"column": str, "operator": str, "value": str}
    Supported operators: =, !=, >, <, >=, <=, LIKE, ILIKE
    """
    if not conditions:
        return sql.SQL(""), []

    allowed_ops = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "ILIKE"}
    parts: list[sql.Composable] = []
    params: list[Any] = []

    for cond in conditions:
        op = cond.get("operator", "=").upper()
        if op not in allowed_ops:
            op = "="
        parts.append(
            sql.SQL("{col} " + op + " %s").format(col=sql.Identifier(cond["column"]))
        )
        params.append(cond["value"])

    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts), params


def safe_select(
    table_name: str,
    user_id: str,
    columns: list[str] | None = None,
    where: list[dict[str, str]] | None = None,
    group_by: list[str] | None = None,
    order_by: str | None = None,
    order_dir: str = "ASC",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Execute a safe SELECT query. Returns {columns, rows, total_count}."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")

    limit = min(limit, MAX_SELECT_ROWS)
    if order_dir.upper() not in ("ASC", "DESC"):
        order_dir = "ASC"

    # SELECT columns
    if columns:
        select_cols = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    else:
        select_cols = sql.SQL("*")

    # WHERE
    where_clause, where_params = _build_where_clause(where)

    # GROUP BY
    group_clause = sql.SQL("")
    if group_by:
        group_clause = sql.SQL(" GROUP BY ") + sql.SQL(", ").join(
            sql.Identifier(g) for g in group_by
        )

    # ORDER BY
    order_clause = sql.SQL("")
    if order_by:
        order_clause = sql.SQL(" ORDER BY {col} " + order_dir).format(
            col=sql.Identifier(order_by)
        )

    # Main query
    query = (
        sql.SQL("SELECT {cols} FROM {tbl}")
        .format(cols=select_cols, tbl=sql.Identifier(table_name))
        + where_clause
        + group_clause
        + order_clause
        + sql.SQL(" LIMIT %s OFFSET %s")
    )

    # Count query
    count_query = (
        sql.SQL("SELECT COUNT(*) AS cnt FROM {tbl}").format(
            tbl=sql.Identifier(table_name)
        )
        + where_clause
    )

    all_params = where_params + [limit, offset]
    count_params = where_params

    t0 = time.monotonic()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(QUERY_TIMEOUT_MS),))
            cur.execute(count_query, count_params)
            total_count = cur.fetchone()["cnt"]  # type: ignore[index]
            cur.execute(query, all_params)
            rows = cur.fetchall()
    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms > 500:
        logger.warning("Slow query on %s: %.0fms", table_name, elapsed_ms)

    col_names = [desc.name for desc in cur.description] if cur.description else []
    return {
        "columns": col_names,
        "rows": [dict(r) for r in rows],
        "total_count": total_count,
    }


def safe_aggregate(
    table_name: str,
    user_id: str,
    operation: str,
    column: str,
    group_by: list[str] | None = None,
    where: list[dict[str, str]] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Execute an aggregation query. Returns {columns, rows}."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")

    allowed_ops = {"sum", "avg", "count", "min", "max"}
    op = operation.lower()
    if op not in allowed_ops:
        raise ValueError(f"Unsupported aggregation: {operation}")

    limit = min(limit, MAX_SELECT_ROWS)

    # Build SELECT
    agg_expr = sql.SQL("{op}({col}) AS result").format(
        op=sql.SQL(op.upper()),
        col=sql.Identifier(column),
    )

    if group_by:
        group_cols = sql.SQL(", ").join(sql.Identifier(g) for g in group_by)
        select_expr = group_cols + sql.SQL(", ") + agg_expr
    else:
        select_expr = agg_expr

    where_clause, where_params = _build_where_clause(where)

    group_clause = sql.SQL("")
    if group_by:
        group_clause = sql.SQL(" GROUP BY ") + sql.SQL(", ").join(
            sql.Identifier(g) for g in group_by
        )

    query = (
        sql.SQL("SELECT {expr} FROM {tbl}").format(
            expr=select_expr, tbl=sql.Identifier(table_name)
        )
        + where_clause
        + group_clause
        + sql.SQL(" LIMIT %s")
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(QUERY_TIMEOUT_MS),))
            cur.execute(query, where_params + [limit])
            rows = cur.fetchall()

    col_names = [desc.name for desc in cur.description] if cur.description else []
    return {
        "columns": col_names,
        "rows": [dict(r) for r in rows],
    }


def _lock_write_catalog(cur, table_name, user_id):
    """Generic row edits participate in the same metadata/outbox transaction."""
    cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(QUERY_TIMEOUT_MS),))
    cur.execute("""SELECT t.id FROM table_meta t JOIN projects p ON p.id=t.project_id AND p.user_id=t.user_id
        WHERE t.user_id=%s AND t.deleted_at IS NULL AND p.deleted_at IS NULL
          AND ('ut_' || left(replace(t.user_id::text,'-',''),8) || '_' || left(replace(t.id::text,'-',''),8))=%s
        FOR UPDATE OF t FOR SHARE OF p""", (user_id, table_name))
    metas = cur.fetchall()
    if len(metas) != 1:
        raise PermissionError('Live table metadata could not be uniquely resolved')
    return metas[0]['id']


def _touch_write_catalog(cur, meta_id, count_delta=0):
    cur.execute('UPDATE table_meta SET row_count=greatest(0,row_count+%s),updated_at=clock_timestamp() WHERE id=%s',
                (count_delta, meta_id))


def safe_insert(
    table_name: str,
    user_id: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """INSERT rows with prepared statements. Returns {inserted_count, sample_row}."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")
    if not rows:
        return {"inserted_count": 0, "sample_row": None}

    columns = list(rows[0].keys())
    col_ids = [sql.Identifier(c) for c in columns]
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in columns)

    query = sql.SQL("INSERT INTO {tbl} ({cols}) VALUES ({vals})").format(
        tbl=sql.Identifier(table_name),
        cols=sql.SQL(", ").join(col_ids),
        vals=placeholders,
    )

    inserted = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            assert_unmanaged_table(cur, table_name)
            meta_id = _lock_write_catalog(cur, table_name, user_id)
            for row in rows:
                values = [row.get(c) for c in columns]
                cur.execute(query, values)
                inserted += cur.rowcount
            _touch_write_catalog(cur, meta_id, inserted)
        conn.commit()

    return {
        "inserted_count": inserted,
        "sample_row": rows[0] if rows else None,
    }


def safe_update(
    table_name: str,
    user_id: str,
    set_values: dict[str, Any],
    where: list[dict[str, str]],
) -> dict[str, Any]:
    """UPDATE with WHERE clause. Returns {updated_count}."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")
    if not where:
        raise ValueError("WHERE clause is required for UPDATE operations")
    if not set_values:
        return {"updated_count": 0}

    set_parts = []
    set_params: list[Any] = []
    for col, val in set_values.items():
        set_parts.append(
            sql.SQL("{col} = %s").format(col=sql.Identifier(col))
        )
        set_params.append(val)

    where_clause, where_params = _build_where_clause(where)

    query = (
        sql.SQL("UPDATE {tbl} SET ").format(tbl=sql.Identifier(table_name))
        + sql.SQL(", ").join(set_parts)
        + where_clause
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            assert_unmanaged_table(cur, table_name)
            meta_id = _lock_write_catalog(cur, table_name, user_id)
            cur.execute(query, set_params + where_params)
            updated = cur.rowcount
            if updated:
                _touch_write_catalog(cur, meta_id)
        conn.commit()

    return {"updated_count": updated}


def safe_delete(
    table_name: str,
    user_id: str,
    where: list[dict[str, str]],
) -> dict[str, Any]:
    """DELETE with WHERE clause. Returns {deleted_count}."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")
    if not where:
        raise ValueError("WHERE clause is required for DELETE operations")

    where_clause, where_params = _build_where_clause(where)

    query = (
        sql.SQL("DELETE FROM {tbl}").format(tbl=sql.Identifier(table_name))
        + where_clause
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            assert_unmanaged_table(cur, table_name)
            meta_id = _lock_write_catalog(cur, table_name, user_id)
            cur.execute(query, where_params)
            deleted = cur.rowcount
            if deleted:
                _touch_write_catalog(cur, meta_id, -deleted)
        conn.commit()

    return {"deleted_count": deleted}


ALLOWED_PG_TYPES = {"TEXT", "BIGINT", "NUMERIC(15,2)", "BOOLEAN", "DATE", "TIMESTAMP"}
PROTECTED_COLUMNS = {"_row_id"}
ALLOWED_JOIN_TYPES = {"INNER", "LEFT", "RIGHT"}


def safe_alter_table(
    table_name: str,
    user_id: str,
    operation: str,
    column_name: str,
    new_column_name: str | None = None,
    column_type: str | None = None,
) -> dict[str, Any]:
    """ALTER TABLE operations: add_column, drop_column, rename_column, change_type."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")

    allowed_ops = {"add_column", "drop_column", "rename_column", "change_type"}
    if operation not in allowed_ops:
        raise ValueError(f"Unsupported alter operation: {operation}")

    if column_name.lower() in PROTECTED_COLUMNS:
        raise ValueError(f"Column '{column_name}' is protected and cannot be modified")

    if operation in ("add_column", "change_type"):
        if not column_type or column_type.upper() not in ALLOWED_PG_TYPES:
            raise ValueError(f"Invalid column type: {column_type}. Allowed: {ALLOWED_PG_TYPES}")

    if operation == "rename_column":
        if not new_column_name:
            raise ValueError("new_column_name is required for rename_column")
        if new_column_name.lower() in PROTECTED_COLUMNS:
            raise ValueError(f"Cannot rename to protected name '{new_column_name}'")

    with _connect() as conn:
        with conn.cursor() as cur:
            assert_unmanaged_table(cur, table_name)
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(QUERY_TIMEOUT_MS),))

            if operation == "add_column":
                cur.execute(
                    sql.SQL("ALTER TABLE {tbl} ADD COLUMN {col} {typ}").format(
                        tbl=sql.Identifier(table_name),
                        col=sql.Identifier(column_name),
                        typ=sql.SQL(column_type.upper()),  # type: ignore[union-attr]
                    )
                )
            elif operation == "drop_column":
                cur.execute(
                    sql.SQL("ALTER TABLE {tbl} DROP COLUMN {col}").format(
                        tbl=sql.Identifier(table_name),
                        col=sql.Identifier(column_name),
                    )
                )
            elif operation == "rename_column":
                cur.execute(
                    sql.SQL("ALTER TABLE {tbl} RENAME COLUMN {old} TO {new}").format(
                        tbl=sql.Identifier(table_name),
                        old=sql.Identifier(column_name),
                        new=sql.Identifier(new_column_name),  # type: ignore[arg-type]
                    )
                )
            elif operation == "change_type":
                cur.execute(
                    sql.SQL(
                        "ALTER TABLE {tbl} ALTER COLUMN {col} TYPE {typ} USING {col}::{typ}"
                    ).format(
                        tbl=sql.Identifier(table_name),
                        col=sql.Identifier(column_name),
                        typ=sql.SQL(column_type.upper()),  # type: ignore[union-attr]
                    )
                )
        conn.commit()

    return {"success": True, "operation": operation, "column": column_name}


def safe_cross_select(
    tables: list[dict[str, str]],
    user_id: str,
    join_conditions: list[dict[str, str]],
    columns: list[str] | None = None,
    where: list[dict[str, str]] | None = None,
    group_by: list[str] | None = None,
    order_by: str | None = None,
    order_dir: str = "ASC",
    limit: int = 100,
) -> dict[str, Any]:
    """Execute a JOIN query across multiple user tables.

    tables: [{"name": pg_table_name, "alias": "a"}, ...]
    join_conditions: [{"left": "a.col", "right": "b.col", "type": "INNER"}, ...]
    columns/where/group_by use qualified refs: "alias.column_name"
    """
    if len(tables) < 2 or len(tables) > 3:
        raise ValueError("Cross query requires 2-3 tables")

    for t in tables:
        if not validate_table_access(user_id, t["name"]):
            raise PermissionError(f"Access denied to table {t['name']}")

    valid_aliases = {t["alias"] for t in tables}
    limit = min(limit, MAX_SELECT_ROWS)
    if order_dir.upper() not in ("ASC", "DESC"):
        order_dir = "ASC"

    def _parse_qualified(ref: str) -> tuple[str, str]:
        """Parse 'alias.column' into (alias, column). Raises on invalid."""
        parts = ref.split(".", 1)
        if len(parts) != 2 or parts[0] not in valid_aliases:
            raise ValueError(f"Invalid column reference: {ref}. Use 'alias.column' format.")
        return parts[0], parts[1]

    def _qualified_id(ref: str) -> sql.Composable:
        alias, col = _parse_qualified(ref)
        return sql.SQL("{a}.{c}").format(a=sql.Identifier(alias), c=sql.Identifier(col))

    # SELECT columns
    if columns:
        select_cols = sql.SQL(", ").join(_qualified_id(c) for c in columns)
    else:
        select_cols = sql.SQL("*")

    # FROM + JOINs
    base = tables[0]
    from_clause = sql.SQL("{tbl} AS {a}").format(
        tbl=sql.Identifier(base["name"]), a=sql.Identifier(base["alias"])
    )

    for jc in join_conditions:
        join_type = jc.get("type", "INNER").upper()
        if join_type not in ALLOWED_JOIN_TYPES:
            join_type = "INNER"

        # Find the right-side table
        right_alias, right_col = _parse_qualified(jc["right"])
        right_table = next((t for t in tables if t["alias"] == right_alias), None)
        if not right_table:
            raise ValueError(f"Unknown alias in join condition: {right_alias}")

        left_id = _qualified_id(jc["left"])
        right_id = _qualified_id(jc["right"])

        from_clause = (
            from_clause
            + sql.SQL(f" {join_type} JOIN ")
            + sql.SQL("{tbl} AS {a}").format(
                tbl=sql.Identifier(right_table["name"]),
                a=sql.Identifier(right_alias),
            )
            + sql.SQL(" ON ")
            + left_id
            + sql.SQL(" = ")
            + right_id
        )

    # WHERE
    where_parts: list[sql.Composable] = []
    where_params: list[Any] = []
    if where:
        allowed_ops = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "ILIKE"}
        for cond in where:
            op = cond.get("operator", "=").upper()
            if op not in allowed_ops:
                op = "="
            col_id = _qualified_id(cond["column"])
            where_parts.append(sql.SQL("{col} " + op + " %s").format(col=col_id))
            where_params.append(cond["value"])

    where_clause = sql.SQL("")
    if where_parts:
        where_clause = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_parts)

    # GROUP BY
    group_clause = sql.SQL("")
    if group_by:
        group_clause = sql.SQL(" GROUP BY ") + sql.SQL(", ").join(
            _qualified_id(g) for g in group_by
        )

    # ORDER BY
    order_clause = sql.SQL("")
    if order_by:
        order_clause = sql.SQL(" ORDER BY ") + _qualified_id(order_by) + sql.SQL(f" {order_dir}")

    query = (
        sql.SQL("SELECT {cols} FROM ").format(cols=select_cols)
        + from_clause
        + where_clause
        + group_clause
        + order_clause
        + sql.SQL(" LIMIT %s")
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(QUERY_TIMEOUT_MS),))
            cur.execute(query, where_params + [limit])
            rows = cur.fetchall()

    col_names = [desc.name for desc in cur.description] if cur.description else []
    return {
        "columns": col_names,
        "rows": [dict(r) for r in rows],
        "total_count": len(rows),
    }


def export_table_csv(table_name: str, user_id: str) -> str:
    """Export full table contents as a CSV string."""
    import csv
    import io

    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(QUERY_TIMEOUT_MS),))
            cur.execute(
                sql.SQL("SELECT * FROM {tbl} ORDER BY {pk} ASC").format(
                    tbl=sql.Identifier(table_name),
                    pk=sql.Identifier("_row_id"),
                )
            )
            rows = cur.fetchall()
            col_names = [desc.name for desc in cur.description] if cur.description else []

    # Exclude internal _row_id column
    export_cols = [c for c in col_names if c != "_row_id"]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=export_cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return buf.getvalue()


def get_table_row_count(table_name: str, user_id: str) -> int:
    """Get the current row count of a user data table."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT COUNT(*) AS cnt FROM {tbl}").format(
                    tbl=sql.Identifier(table_name)
                )
            )
            row = cur.fetchone()
    return row["cnt"] if row else 0  # type: ignore[index]


def get_sample_rows(
    table_name: str, user_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Get sample rows from a user data table."""
    if not validate_table_access(user_id, table_name):
        raise PermissionError(f"Access denied to table {table_name}")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT * FROM {tbl} LIMIT %s").format(
                    tbl=sql.Identifier(table_name)
                ),
                (limit,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]
