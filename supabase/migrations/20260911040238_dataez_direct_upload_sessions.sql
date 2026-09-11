
CREATE TABLE IF NOT EXISTS upload_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    project_id UUID REFERENCES projects(id),
    request_id UUID NOT NULL,
    filename TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 20971520),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + interval '2 hours'),
    file_id UUID REFERENCES files(id),
    UNIQUE(user_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_upload_sessions_expiry ON upload_sessions(expires_at) WHERE file_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_upload_sessions_project ON upload_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_upload_sessions_file ON upload_sessions(file_id);
ALTER TABLE upload_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON upload_sessions FROM PUBLIC;

REVOKE ALL ON upload_sessions FROM anon, authenticated;
ALTER TABLE upload_sessions OWNER TO dataez_app;
