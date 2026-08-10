"""CSV/XLSX import pipeline: file -> schema inference -> CREATE TABLE -> bulk INSERT."""

import io
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

import pandas as pd
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .config import settings
from .db import _connect


def _sanitize_column_name(name: str) -> str:
    """Sanitize a column name for safe use as a PostgreSQL identifier."""
    name = name.strip()
    # Replace spaces and special chars with underscore
    name = re.sub(r"[^a-zA-Z0-9가-힣_]", "_", name)
    # Remove leading digits
    name = re.sub(r"^[0-9]+", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "col"
    return name.lower()


def _infer_pg_type(dtype: str) -> str:
    """Map pandas dtype string to PostgreSQL type."""
    dtype = str(dtype).lower()
    if "int" in dtype:
        return "BIGINT"
    if "float" in dtype:
        return "NUMERIC(15,2)"
    if "bool" in dtype:
        return "BOOLEAN"
    if "datetime" in dtype:
        return "TIMESTAMP"
    if "date" in dtype:
        return "DATE"
    return "TEXT"


def _infer_numeric_precision(series: pd.Series) -> str:
    """Determine NUMERIC precision based on actual data."""
    non_null = series.dropna()
    if non_null.empty:
        return "NUMERIC(15,2)"
    max_val = non_null.abs().max()
    # Determine integer digits needed
    int_digits = len(str(int(max_val))) if max_val >= 1 else 1
    # Check decimal places used
    decimal_places = 0
    for val in non_null.head(100):
        s = f"{val:.10f}".rstrip("0")
        if "." in s:
            dp = len(s.split(".")[1])
            decimal_places = max(decimal_places, dp)
    decimal_places = min(decimal_places, 6)
    if decimal_places == 0:
        decimal_places = 2
    total = max(int_digits + decimal_places, 10)
    return f"NUMERIC({total},{decimal_places})"


def infer_columns_schema(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Infer PostgreSQL column types from a pandas DataFrame.

    Returns: [{"name": "col", "type": "TEXT", "nullable": True}, ...]
    """
    SAMPLE_SIZE = 100
    schema = []
    for col in df.columns:
        clean_name = _sanitize_column_name(str(col))
        pg_type = _infer_pg_type(str(df[col].dtype))

        # Adaptive numeric precision
        if pg_type.startswith("NUMERIC"):
            pg_type = _infer_numeric_precision(df[col])

        # Try to detect date/timestamp columns stored as strings
        if pg_type == "TEXT" and df[col].notna().any():
            sample = df[col].dropna().head(SAMPLE_SIZE).astype(str)
            date_like = sample.str.match(r".*[\d]{2,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4}.*")
            if date_like.sum() > len(sample) * 0.8:
                try:
                    parsed = pd.to_datetime(sample, errors="coerce")
                    if parsed.notna().sum() > len(sample) * 0.8:
                        # Check if any values have time components
                        has_time = any(
                            " " in s and ":" in s
                            for s in sample
                        )
                        pg_type = "TIMESTAMP" if has_time else "DATE"
                except Exception:
                    logger.debug("Date detection failed for column %s", col)

        schema.append({
            "name": clean_name,
            "type": pg_type,
            "nullable": True,
        })

    # Deduplicate column names
    seen: dict[str, int] = {}
    for col_def in schema:
        name = col_def["name"]
        if name in seen:
            seen[name] += 1
            col_def["name"] = f"{name}_{seen[name]}"
        else:
            seen[name] = 0

    return schema


def _load_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    """Load a DataFrame from CSV or XLSX bytes.

    Handles BOM stripping and empty file detection.
    """
    if not content or not content.strip():
        raise ValueError("파일이 비어 있습니다 (empty file)")

    # Strip UTF-8 BOM if present
    if content[:3] == b"\xef\xbb\xbf":
        content = content[3:]

    buf = io.BytesIO(content)
    if filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"):
        df = pd.read_excel(buf)
    else:
        # Try various encodings
        for encoding in ("utf-8", "cp949", "euc-kr", "latin-1"):
            try:
                buf.seek(0)
                df = pd.read_csv(buf, encoding=encoding)
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        else:
            buf.seek(0)
            df = pd.read_csv(buf, encoding="utf-8", errors="replace")

    if df.empty and df.columns.empty:
        raise ValueError("파일에 데이터가 없습니다 (no columns found)")

    return df


def import_csv_to_table(
    content: bytes,
    filename: str,
    table_name: str,
    columns_schema: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse CSV/XLSX, create table, bulk insert data.

    If columns_schema is None, infer it from the file.
    Returns (columns_schema, row_count).
    """
    df = _load_dataframe(content, filename)

    if columns_schema is None:
        columns_schema = infer_columns_schema(df)

    # Create table
    col_defs = [
        sql.SQL("{col} {typ}").format(
            col=sql.Identifier(col["name"]),
            typ=sql.SQL(col["type"]),
        )
        for col in columns_schema
    ]
    all_cols = [sql.SQL("_row_id SERIAL PRIMARY KEY")] + col_defs
    create_query = sql.SQL("CREATE TABLE IF NOT EXISTS {tbl} ({cols})").format(
        tbl=sql.Identifier(table_name),
        cols=sql.SQL(", ").join(all_cols),
    )

    # Prepare insert
    col_names = [col["name"] for col in columns_schema]
    col_ids = [sql.Identifier(c) for c in col_names]
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in col_names)
    insert_query = sql.SQL("INSERT INTO {tbl} ({cols}) VALUES ({vals})").format(
        tbl=sql.Identifier(table_name),
        cols=sql.SQL(", ").join(col_ids),
        vals=placeholders,
    )

    # Map DataFrame columns to schema columns
    df_cols = list(df.columns)
    col_map: list[str | None] = []
    for schema_col in columns_schema:
        matched = None
        for df_col in df_cols:
            if _sanitize_column_name(str(df_col)) == schema_col["name"]:
                matched = df_col
                break
        col_map.append(matched)

    # Build all rows as tuples for bulk insert
    all_rows: list[tuple] = []
    for _, row in df.iterrows():
        values = []
        for i, schema_col in enumerate(columns_schema):
            df_col = col_map[i]
            if df_col is not None:
                val = row[df_col]
                if pd.isna(val):
                    val = None
                else:
                    val = _cast_value(val, schema_col["type"])
                values.append(val)
            else:
                values.append(None)
        all_rows.append(tuple(values))

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(create_query)
            cur.executemany(insert_query, all_rows)
        conn.commit()

    return columns_schema, len(all_rows)


def append_csv_to_table(
    content: bytes,
    filename: str,
    table_name: str,
    existing_schema: list[dict[str, Any]],
) -> int:
    """Append CSV data to an existing table. Returns rows inserted."""
    df = _load_dataframe(content, filename)

    col_names = [col["name"] for col in existing_schema]
    col_ids = [sql.Identifier(c) for c in col_names]
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in col_names)
    insert_query = sql.SQL("INSERT INTO {tbl} ({cols}) VALUES ({vals})").format(
        tbl=sql.Identifier(table_name),
        cols=sql.SQL(", ").join(col_ids),
        vals=placeholders,
    )

    # Map DataFrame columns
    df_cols = list(df.columns)
    col_map: list[str | None] = []
    for schema_col in existing_schema:
        matched = None
        for df_col in df_cols:
            if _sanitize_column_name(str(df_col)) == schema_col["name"]:
                matched = df_col
                break
        col_map.append(matched)

    all_rows: list[tuple] = []
    for _, row in df.iterrows():
        values = []
        for i, schema_col in enumerate(existing_schema):
            df_col = col_map[i]
            if df_col is not None:
                val = row[df_col]
                if pd.isna(val):
                    val = None
                else:
                    val = _cast_value(val, schema_col["type"])
                values.append(val)
            else:
                values.append(None)
        all_rows.append(tuple(values))

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(insert_query, all_rows)
        conn.commit()

    return len(all_rows)


def _cast_value(val: Any, pg_type: str) -> Any:
    """Cast a Python value to match the PostgreSQL type."""
    if val is None:
        return None
    pg_type = pg_type.upper()
    try:
        if pg_type == "BIGINT":
            return int(float(val))
        if pg_type.startswith("NUMERIC"):
            return float(val)
        if pg_type == "BOOLEAN":
            return bool(val)
        if pg_type in ("DATE", "TIMESTAMP"):
            s = str(val)
            # Validate it actually looks like a date before sending to PG
            parsed = pd.to_datetime(s, errors="coerce")
            if pd.isna(parsed):
                return None
            if pg_type == "DATE":
                return parsed.strftime("%Y-%m-%d")
            return parsed.isoformat()
    except (ValueError, TypeError):
        return str(val)
    return str(val)
