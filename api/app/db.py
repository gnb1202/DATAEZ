import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import json
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Return the shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            timeout=settings.db_pool_timeout,
            kwargs={"row_factory": dict_row},
            # Explicit: psycopg_pool's default flips to False in a future release.
            open=True,
        )
        logger.info("DB connection pool created (min=%d, max=%d)", settings.db_pool_min_size, settings.db_pool_max_size)
    return _pool


def close_pool() -> None:
    """Shut down the connection pool (call on app shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("DB connection pool closed")


@contextmanager
def _connect():
    """Get a connection from the pool (drop-in replacement for old _connect)."""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def run_startup_migrations() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                  id UUID PRIMARY KEY,
                  user_id UUID NOT NULL REFERENCES users(id),
                  token_hash TEXT UNIQUE NOT NULL,
                  expires_at TIMESTAMP NOT NULL,
                  revoked_at TIMESTAMP NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            # Backfill query_history.user_id where possible.
            cur.execute(
                """
                UPDATE query_history q
                SET user_id = f.user_id
                FROM files f
                WHERE q.user_id IS NULL
                  AND q.file_id = f.id
                  AND f.user_id IS NOT NULL
                """
            )
            # Remove orphan legacy rows that cannot be mapped safely.
            cur.execute("DELETE FROM query_history WHERE user_id IS NULL")
            cur.execute("DELETE FROM files WHERE user_id IS NULL")
            # Enforce non-null ownership on core tables.
            cur.execute("ALTER TABLE files ALTER COLUMN user_id SET NOT NULL")
            cur.execute("ALTER TABLE query_history ALTER COLUMN user_id SET NOT NULL")
        conn.commit()


def ensure_performance_indexes() -> None:
    """Create composite indexes for common query patterns."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_files_user_created ON files(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at ASC)",
        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_query_history_user_created ON query_history(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_projects_user_updated ON projects(user_id, updated_at DESC)",
    ]
    with _connect() as conn:
        with conn.cursor() as cur:
            for idx_sql in indexes:
                cur.execute(idx_sql)
        conn.commit()
    logger.info("Performance indexes ensured")


def ensure_project_tables() -> None:
    """Create projects & table_meta tables, and add new columns to existing tables."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id UUID NOT NULL REFERENCES users(id),
                  name VARCHAR(255) NOT NULL,
                  description TEXT DEFAULT '',
                  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS table_meta (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                  user_id UUID NOT NULL REFERENCES users(id),
                  name VARCHAR(255) NOT NULL,
                  description TEXT DEFAULT '',
                  columns_schema JSONB NOT NULL DEFAULT '[]',
                  row_count INTEGER NOT NULL DEFAULT 0,
                  source_file_id UUID REFERENCES files(id),
                  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_table_meta_project ON table_meta(project_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_table_meta_user ON table_meta(user_id)"
            )
            # Add project_id and table_id to conversations (backward-compatible)
            cur.execute(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='conversations' AND column_name='project_id'
                  ) THEN
                    ALTER TABLE conversations ADD COLUMN project_id UUID REFERENCES projects(id);
                  END IF;
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='conversations' AND column_name='table_id'
                  ) THEN
                    ALTER TABLE conversations ADD COLUMN table_id UUID REFERENCES table_meta(id);
                  END IF;
                END $$;
                """
            )
            # Add deleted_at for soft delete (backward-compatible)
            cur.execute(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='projects' AND column_name='deleted_at'
                  ) THEN
                    ALTER TABLE projects ADD COLUMN deleted_at TIMESTAMP NULL;
                  END IF;
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='table_meta' AND column_name='deleted_at'
                  ) THEN
                    ALTER TABLE table_meta ADD COLUMN deleted_at TIMESTAMP NULL;
                  END IF;
                END $$;
                """
            )
            # Add project_id to dashboard_widgets (backward-compatible)
            cur.execute(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='dashboard_widgets' AND column_name='project_id'
                  ) THEN
                    ALTER TABLE dashboard_widgets ADD COLUMN project_id UUID REFERENCES projects(id);
                  END IF;
                END $$;
                """
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Projects (프로젝트 / 사업장)
# ---------------------------------------------------------------------------

def create_project(project_id: str, user_id: str, name: str, description: str = "") -> dict[str, Any]:
    """Insert a new project and return the created row."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (id, user_id, name, description)
                VALUES (%s, %s, %s, %s)
                RETURNING id, user_id, name, description, created_at, updated_at
                """,
                (project_id, user_id, name, description),
            )
            row = cur.fetchone()
        conn.commit()
    return row  # type: ignore[return-value]


def list_projects(user_id: str, limit: int = 50, offset: int = 0, search: str | None = None) -> list[dict[str, Any]]:
    """List projects owned by user with optional name/description search."""
    conditions = ["p.user_id = %s", "p.deleted_at IS NULL"]
    params: list[Any] = [user_id]
    if search:
        conditions.append("(p.name ILIKE %s OR p.description ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    where = " AND ".join(conditions)
    params.extend([limit, offset])
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT p.id, p.name, p.description, p.created_at, p.updated_at,
                       COALESCE(tc.table_count, 0) AS table_count
                FROM projects p
                LEFT JOIN (
                  SELECT project_id, COUNT(*) AS table_count
                  FROM table_meta
                  GROUP BY project_id
                ) tc ON tc.project_id = p.id
                WHERE {where}
                ORDER BY p.updated_at DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cur.fetchall()
    return rows


def get_project(project_id: str, user_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, name, description, created_at, updated_at
                FROM projects
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                """,
                (project_id, user_id),
            )
            row = cur.fetchone()
    return row


def update_project(project_id: str, user_id: str, name: str | None = None, description: str | None = None) -> bool:
    # Column names are hardcoded constants — safe to use in f-string SET clause.
    # Values are always parameterized via %s.
    sets: list[sql.Composable] = []
    params: list[Any] = []
    if name is not None:
        sets.append(sql.SQL("{} = %s").format(sql.Identifier("name")))
        params.append(name)
    if description is not None:
        sets.append(sql.SQL("{} = %s").format(sql.Identifier("description")))
        params.append(description)
    if not sets:
        return False
    sets.append(sql.SQL("updated_at = NOW()"))
    params.extend([project_id, user_id])
    query = sql.SQL("UPDATE projects SET {} WHERE id = %s AND user_id = %s").format(
        sql.SQL(", ").join(sets)
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def delete_project(project_id: str, user_id: str) -> bool:
    """Soft-delete a project and its tables (sets deleted_at)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE projects SET deleted_at = NOW()
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                """,
                (project_id, user_id),
            )
            deleted = cur.rowcount > 0
            if deleted:
                cur.execute(
                    """
                    UPDATE table_meta SET deleted_at = NOW()
                    WHERE project_id = %s AND user_id = %s AND deleted_at IS NULL
                    """,
                    (project_id, user_id),
                )
        conn.commit()
    if deleted:
        logger.info("Soft-deleted project %s", project_id)
    return deleted


# ---------------------------------------------------------------------------
# Table Meta (장부 메타데이터)
# ---------------------------------------------------------------------------

def create_table_meta(
    table_id: str,
    project_id: str,
    user_id: str,
    name: str,
    columns_schema: list[dict[str, Any]],
    description: str = "",
    source_file_id: str | None = None,
    row_count: int = 0,
) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO table_meta (id, project_id, user_id, name, description, columns_schema, row_count, source_file_id)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id, project_id, user_id, name, description, columns_schema, row_count, source_file_id, created_at, updated_at
                """,
                (table_id, project_id, user_id, name, description, json.dumps(columns_schema), row_count, source_file_id),
            )
            row = cur.fetchone()
        conn.commit()
    return row  # type: ignore[return-value]


def list_table_metas(project_id: str, user_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, name, description, columns_schema, row_count, source_file_id, created_at, updated_at
                FROM table_meta
                WHERE project_id = %s AND user_id = %s AND deleted_at IS NULL
                ORDER BY created_at DESC
                """,
                (project_id, user_id),
            )
            rows = cur.fetchall()
    return rows


def get_table_meta(table_id: str, user_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, user_id, name, description, columns_schema, row_count, source_file_id, created_at, updated_at
                FROM table_meta
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                """,
                (table_id, user_id),
            )
            row = cur.fetchone()
    return row


def update_table_meta(
    table_id: str,
    user_id: str,
    name: str | None = None,
    description: str | None = None,
    columns_schema: list[dict[str, Any]] | None = None,
    row_count: int | None = None,
) -> bool:
    sets: list[sql.Composable] = []
    params: list[Any] = []
    if name is not None:
        sets.append(sql.SQL("{} = %s").format(sql.Identifier("name")))
        params.append(name)
    if description is not None:
        sets.append(sql.SQL("{} = %s").format(sql.Identifier("description")))
        params.append(description)
    if columns_schema is not None:
        sets.append(sql.SQL("{} = %s::jsonb").format(sql.Identifier("columns_schema")))
        params.append(json.dumps(columns_schema))
    if row_count is not None:
        sets.append(sql.SQL("{} = %s").format(sql.Identifier("row_count")))
        params.append(row_count)
    if not sets:
        return False
    sets.append(sql.SQL("updated_at = NOW()"))
    params.extend([table_id, user_id])
    query = sql.SQL("UPDATE table_meta SET {} WHERE id = %s AND user_id = %s").format(
        sql.SQL(", ").join(sets)
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def delete_table_meta(table_id: str, user_id: str) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE table_meta SET deleted_at = NOW()
                WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                """,
                (table_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


# ---------------------------------------------------------------------------
# Dynamic User Data Tables (동적 사용자 데이터 테이블)
# ---------------------------------------------------------------------------

def get_user_table_name(user_id: str, table_id: str) -> str:
    """Derive the PostgreSQL table name from user_id and table_id."""
    uid = user_id.replace("-", "")[:8]
    tid = table_id.replace("-", "")[:8]
    return f"ut_{uid}_{tid}"


def create_user_data_table(user_id: str, table_id: str, columns_schema: list[dict[str, Any]]) -> str:
    """Create a PostgreSQL table for user data. Returns the table name."""
    table_name = get_user_table_name(user_id, table_id)
    col_defs = [
        sql.SQL("{col} {typ}").format(
            col=sql.Identifier(col["name"]),
            typ=sql.SQL(col["type"]),
        )
        for col in columns_schema
    ]
    # Add internal row id
    all_cols = [sql.SQL("_row_id SERIAL PRIMARY KEY")] + col_defs
    query = sql.SQL("CREATE TABLE IF NOT EXISTS {tbl} ({cols})").format(
        tbl=sql.Identifier(table_name),
        cols=sql.SQL(", ").join(all_cols),
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()
    return table_name


def drop_user_data_table(user_id: str, table_id: str) -> None:
    """Drop a dynamic user data table."""
    table_name = get_user_table_name(user_id, table_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP TABLE IF EXISTS {tbl} CASCADE").format(
                    tbl=sql.Identifier(table_name),
                )
            )
        conn.commit()


def create_user(user_id: str, email: str, password_hash: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                (user_id, email, password_hash),
            )
        conn.commit()


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, password_hash
                FROM users
                WHERE email = %s
                """,
                (email,),
            )
            row = cur.fetchone()
    return row


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
    return row


def save_file(user_id: str, file_id: str, filename: str, storage_key: str, size_bytes: int) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO files (id, user_id, filename, storage_key, size_bytes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (file_id, user_id, filename, storage_key, size_bytes),
            )
        conn.commit()


def get_file(user_id: str, file_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, filename, storage_key, size_bytes, created_at
                FROM files
                WHERE id = %s AND user_id = %s
                """,
                (file_id, user_id),
            )
            row = cur.fetchone()
    return row


def list_files(user_id: str, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total_count)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM files WHERE user_id = %s",
                (user_id,),
            )
            total = cur.fetchone()["cnt"]  # type: ignore[index]
            cur.execute(
                """
                SELECT id, filename, size_bytes, created_at
                FROM files
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, limit, offset),
            )
            rows = cur.fetchall()
    return rows, total


def delete_file(user_id: str, file_id: str) -> bool:
    """Hard-delete a files row. document_chunks rows are removed via ON DELETE CASCADE."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM files WHERE id = %s AND user_id = %s",
                (file_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def list_project_documents(user_id: str, project_id: str) -> list[dict[str, Any]]:
    """List files that have been ingested as RAG documents in a project."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.id, f.filename, f.size_bytes, f.created_at,
                       COUNT(d.id) AS chunk_count
                FROM files f
                JOIN document_chunks d ON d.file_id = f.id
                WHERE f.user_id = %s AND d.project_id = %s
                GROUP BY f.id, f.filename, f.size_bytes, f.created_at
                ORDER BY f.created_at DESC
                """,
                (user_id, project_id),
            )
            rows = cur.fetchall()
    return rows


def save_query_history(
    user_id: str, query_id: str, file_id: str, question: str, response_summary: str
) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO query_history (id, user_id, file_id, question, response_summary)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (query_id, user_id, file_id, question, response_summary),
            )
        conn.commit()


def list_query_history(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, file_id, question, response_summary, created_at
                FROM query_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
    return rows


def create_refresh_token_record(token_id: str, user_id: str, token_hash: str, expires_at: datetime) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (token_id, user_id, token_hash, expires_at),
            )
        conn.commit()


def get_refresh_token_record(token_hash: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, token_hash, expires_at, revoked_at, created_at
                FROM refresh_tokens
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = cur.fetchone()
    return row


def revoke_refresh_token(token_hash: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE refresh_tokens
                SET revoked_at = NOW()
                WHERE token_hash = %s
                  AND revoked_at IS NULL
                """,
                (token_hash,),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Conversations & Messages
# ---------------------------------------------------------------------------

def ensure_conversation_tables() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                  id UUID PRIMARY KEY,
                  user_id UUID NOT NULL REFERENCES users(id),
                  file_id UUID REFERENCES files(id),
                  title TEXT NOT NULL DEFAULT 'New conversation',
                  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                  id UUID PRIMARY KEY,
                  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL DEFAULT '',
                  steps JSONB,
                  charts JSONB,
                  table_data JSONB,
                  created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            # Per-message LLM accounting. Without these, spend can only be read
            # from logs, so there is no way to attribute cost to a conversation
            # or a user after the fact.
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS total_tokens INTEGER")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6)")
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS usage JSONB")
        conn.commit()


def create_conversation(
    conversation_id: str,
    user_id: str,
    file_id: str | None,
    title: str = "New conversation",
    project_id: str | None = None,
    table_id: str | None = None,
) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (id, user_id, file_id, project_id, table_id, title)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (conversation_id, user_id, file_id, project_id, table_id, title),
            )
        conn.commit()


def list_conversations(
    user_id: str,
    file_id: str | None = None,
    project_id: str | None = None,
    table_id: str | None = None,
    search: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total_count)."""
    conditions = ["user_id = %s"]
    params: list[Any] = [user_id]
    if project_id:
        conditions.append("project_id = %s")
        params.append(project_id)
    if table_id:
        conditions.append("table_id = %s")
        params.append(table_id)
    if file_id:
        conditions.append("file_id = %s")
        params.append(file_id)
    if search:
        conditions.append("title ILIKE %s")
        params.append(f"%{search}%")
    where = " AND ".join(conditions)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM conversations WHERE {where}",
                params,
            )
            total = cur.fetchone()["cnt"]  # type: ignore[index]
            cur.execute(
                f"""
                SELECT id, file_id, project_id, table_id, title, created_at, updated_at
                FROM conversations
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()
    return rows, total


def get_conversation(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, file_id, project_id, table_id, title, created_at, updated_at
                FROM conversations
                WHERE id = %s AND user_id = %s
                """,
                (conversation_id, user_id),
            )
            row = cur.fetchone()
    return row


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    """Delete a conversation owned by user. Returns True if a row was deleted."""
    """Delete a conversation and its messages (CASCADE)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def update_conversation_title(conversation_id: str, title: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE conversations
                SET title = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (title, conversation_id),
            )
        conn.commit()


def touch_conversation(conversation_id: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                (conversation_id,),
            )
        conn.commit()


def save_message(
    message_id: str,
    conversation_id: str,
    role: str,
    content: str,
    steps: Any = None,
    charts: Any = None,
    table_data: Any = None,
    usage: dict[str, Any] | None = None,
) -> None:
    import json

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages
                    (id, conversation_id, role, content, steps, charts, table_data,
                     total_tokens, cost_usd, usage)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    json.dumps(steps, default=str) if steps else None,
                    json.dumps(charts, default=str) if charts else None,
                    json.dumps(table_data, default=str) if table_data else None,
                    (usage or {}).get("total_tokens"),
                    (usage or {}).get("cost_usd"),
                    json.dumps(usage, default=str) if usage else None,
                ),
            )
        conn.commit()


def list_messages(conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, steps, charts, table_data, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
            rows = cur.fetchall()
    return rows


# ---------------------------------------------------------------------------
# Dashboard Widgets
# ---------------------------------------------------------------------------

def ensure_dashboard_widgets_table() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_widgets (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  user_id UUID NOT NULL REFERENCES users(id),
                  file_id UUID REFERENCES files(id),
                  widget_type TEXT NOT NULL,
                  title TEXT NOT NULL DEFAULT '',
                  widget_data JSONB NOT NULL,
                  layout JSONB NOT NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            # Drop NOT NULL on file_id if it exists (backward-compatible migration)
            cur.execute(
                """
                ALTER TABLE dashboard_widgets ALTER COLUMN file_id DROP NOT NULL
                """
            )
        conn.commit()


def list_widgets(user_id: str, project_id: str | None = None, file_id: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            if project_id:
                cur.execute(
                    """
                    SELECT id, widget_type, title, widget_data, layout, created_at
                    FROM dashboard_widgets
                    WHERE user_id = %s AND project_id = %s
                    ORDER BY created_at ASC
                    """,
                    (user_id, project_id),
                )
            elif file_id:
                cur.execute(
                    """
                    SELECT id, widget_type, title, widget_data, layout, created_at
                    FROM dashboard_widgets
                    WHERE user_id = %s AND file_id = %s
                    ORDER BY created_at ASC
                    """,
                    (user_id, file_id),
                )
            else:
                return []
            rows = cur.fetchall()
    return rows


def create_widget(
    widget_id: str,
    user_id: str,
    widget_type: str,
    title: str,
    widget_data: Any,
    layout: Any,
    project_id: str | None = None,
    file_id: str | None = None,
) -> dict[str, Any]:
    import json

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dashboard_widgets (id, user_id, file_id, project_id, widget_type, title, widget_data, layout)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                RETURNING id, widget_type, title, widget_data, layout, created_at
                """,
                (
                    widget_id,
                    user_id,
                    file_id,
                    project_id,
                    widget_type,
                    title,
                    json.dumps(widget_data),
                    json.dumps(layout),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row  # type: ignore[return-value]


def update_widgets_layout(user_id: str, layouts: list[dict[str, Any]]) -> None:
    """Batch update widget layouts after drag/resize."""
    import json

    with _connect() as conn:
        with conn.cursor() as cur:
            for item in layouts:
                cur.execute(
                    """
                    UPDATE dashboard_widgets
                    SET layout = %s::jsonb
                    WHERE id = %s AND user_id = %s
                    """,
                    (json.dumps(item["layout"]), item["id"], user_id),
                )
        conn.commit()


def delete_widget(widget_id: str, user_id: str) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM dashboard_widgets
                WHERE id = %s AND user_id = %s
                """,
                (widget_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


# ---------------------------------------------------------------------------
# Conversation history TTL cleanup
# ---------------------------------------------------------------------------

def cleanup_old_conversations(ttl_days: int | None = None) -> int:
    """Delete conversations (and their messages via CASCADE) older than ttl_days.

    Returns the number of conversations deleted.
    """
    if ttl_days is None:
        ttl_days = settings.conversation_ttl_days
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM conversations
                WHERE updated_at < NOW() - INTERVAL '%s days'
                """,
                (ttl_days,),
            )
            deleted = cur.rowcount
        conn.commit()
    if deleted:
        logger.info("Cleaned up %d old conversations (TTL=%d days)", deleted, ttl_days)
    return deleted


# ---------------------------------------------------------------------------
# Audit Log (감사 로그)
# ---------------------------------------------------------------------------

def ensure_rag_tables() -> None:
    """Create pgvector extension and RAG tables idempotently.

    Safe to call on every startup. Mirrors db/migrations/001_pgvector_rag.sql
    so existing deployments pick up the schema without `docker compose down -v`.
    Skipped silently if pgvector is unavailable (e.g. plain postgres image) —
    the RAG features will return errors at call time, not at boot.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_embeddings (
                      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                      table_meta_id UUID NOT NULL UNIQUE REFERENCES table_meta(id) ON DELETE CASCADE,
                      user_id UUID NOT NULL REFERENCES users(id),
                      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                      content TEXT NOT NULL,
                      embedding vector(1536) NOT NULL,
                      -- Populated by the app from morpheme-analysed text; a
                      -- generated column cannot call the Korean analyzer, and
                      -- to_tsvector('simple', content) splits Korean on
                      -- whitespace only. See db/migrations/002_korean_fts.sql.
                      content_tsv tsvector,
                      content_hash TEXT NOT NULL,
                      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                      updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_schema_emb_vec
                      ON schema_embeddings USING hnsw (embedding vector_cosine_ops)
                      WITH (m = 16, ef_construction = 64)
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_schema_emb_tsv ON schema_embeddings USING GIN (content_tsv)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_schema_emb_user_project ON schema_embeddings(user_id, project_id)"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS document_chunks (
                      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                      file_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                      user_id UUID NOT NULL REFERENCES users(id),
                      project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
                      chunk_index INTEGER NOT NULL,
                      content TEXT NOT NULL,
                      embedding vector(1536) NOT NULL,
                      -- Populated by the app from morpheme-analysed text; a
                      -- generated column cannot call the Korean analyzer, and
                      -- to_tsvector('simple', content) splits Korean on
                      -- whitespace only. See db/migrations/002_korean_fts.sql.
                      content_tsv tsvector,
                      metadata JSONB NOT NULL DEFAULT '{}',
                      token_count INTEGER,
                      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                      UNIQUE (file_id, chunk_index)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_doc_chunks_vec
                      ON document_chunks USING hnsw (embedding vector_cosine_ops)
                      WITH (m = 16, ef_construction = 64)
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_doc_chunks_tsv ON document_chunks USING GIN (content_tsv)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_doc_chunks_user_project ON document_chunks(user_id, project_id)"
                )
                # Converge databases created before 002, where content_tsv is
                # still a generated column and cannot be written by the app.
                for table in ("schema_embeddings", "document_chunks"):
                    cur.execute(
                        """
                        SELECT is_generated FROM information_schema.columns
                        WHERE table_name = %s AND column_name = 'content_tsv'
                        """,
                        (table,),
                    )
                    row = cur.fetchone()
                    if row and row["is_generated"] == "ALWAYS":
                        logger.info("Migrating %s.content_tsv off generated column", table)
                        cur.execute(
                            sql.SQL("ALTER TABLE {} DROP COLUMN content_tsv").format(
                                sql.Identifier(table)
                            )
                        )
                        cur.execute(
                            sql.SQL("ALTER TABLE {} ADD COLUMN content_tsv tsvector").format(
                                sql.Identifier(table)
                            )
                        )
            conn.commit()
        logger.info("RAG tables ensured (pgvector + schema_embeddings + document_chunks)")
    except psycopg.errors.UndefinedFile:
        logger.warning("pgvector extension not installed in this Postgres image — RAG features disabled")
    except Exception:
        logger.exception("Failed to ensure RAG tables — RAG features may not work")


def ensure_audit_log_table() -> None:
    """Create audit_log table if it doesn't exist."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                  id BIGSERIAL PRIMARY KEY,
                  user_id UUID NOT NULL REFERENCES users(id),
                  action TEXT NOT NULL,
                  resource_type TEXT NOT NULL,
                  resource_id TEXT,
                  detail JSONB,
                  created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id)")
        conn.commit()


def record_audit(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record an audit log entry. Fire-and-forget — errors are logged, not raised."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource_type, resource_id, detail)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (user_id, action, resource_type, resource_id, json.dumps(detail) if detail else None),
                )
            conn.commit()
    except Exception:
        logger.warning("Failed to record audit log: %s %s %s", action, resource_type, resource_id, exc_info=True)


def purge_soft_deleted(days: int = 30) -> int:
    """Hard-delete records that were soft-deleted more than `days` ago."""
    total = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            # Purge table_meta first (FK on projects)
            cur.execute(
                "SELECT id, user_id FROM table_meta WHERE deleted_at < NOW() - INTERVAL '%s days'",
                (days,),
            )
            old_tables = cur.fetchall()
            for t in old_tables:
                pg_name = get_user_table_name(str(t["user_id"]), str(t["id"]))
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(pg_name))
                )
            cur.execute(
                "DELETE FROM table_meta WHERE deleted_at < NOW() - INTERVAL '%s days'",
                (days,),
            )
            total += cur.rowcount
            cur.execute(
                "DELETE FROM projects WHERE deleted_at < NOW() - INTERVAL '%s days'",
                (days,),
            )
            total += cur.rowcount
        conn.commit()
    if total:
        logger.info("Purged %d soft-deleted records (TTL=%d days)", total, days)
    return total


def list_audit_logs(
    user_id: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query audit logs with optional filters."""
    conditions = ["user_id = %s"]
    params: list[Any] = [user_id]
    if resource_type:
        conditions.append("resource_type = %s")
        params.append(resource_type)
    if resource_id:
        conditions.append("resource_id = %s")
        params.append(resource_id)
    where = " AND ".join(conditions)
    params.extend([limit, offset])
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, user_id, action, resource_type, resource_id, detail, created_at
                FROM audit_log
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cur.fetchall()
    return rows


def cleanup_expired_refresh_tokens() -> int:
    """Remove expired or revoked refresh tokens."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM refresh_tokens
                WHERE expires_at < NOW() OR revoked_at IS NOT NULL
                """
            )
            deleted = cur.rowcount
        conn.commit()
    return deleted
