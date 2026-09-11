"""Bounded request counters, shared across serverless instances."""
DDL = """
CREATE TABLE IF NOT EXISTS request_limits (
    key_hash TEXT PRIMARY KEY,
    used INTEGER NOT NULL CHECK (used > 0),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_limits_expiry ON request_limits(expires_at);
ALTER TABLE request_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON request_limits FROM PUBLIC;
"""


def ensure_request_limits():
    from . import db
    with db._connect() as conn:
        conn.execute(DDL)
