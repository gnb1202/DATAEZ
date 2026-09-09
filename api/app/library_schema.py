"""Account-owned retained files, separate from expiring import staging."""

DDL = """
CREATE TABLE IF NOT EXISTS library_entries (
    file_id UUID PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    content_hash CHAR(64),
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_library_owner_store ON library_entries(user_id,project_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_library_content ON library_entries
    (user_id,project_id,content_hash)
    WHERE content_hash IS NOT NULL AND deleted_at IS NULL;
ALTER TABLE library_entries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON library_entries FROM PUBLIC;
CREATE TABLE IF NOT EXISTS sample_workspaces (
    user_id UUID PRIMARY KEY,
    project_id UUID NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE
);
ALTER TABLE sample_workspaces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sample_workspaces FROM PUBLIC;
"""


def ensure_library():
    from . import db
    with db._connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('dataez-library-migration'))")
        conn.execute(DDL)
        from .file_scope_schema import DDL as SCOPE_DDL
        conn.execute(SCOPE_DDL)
