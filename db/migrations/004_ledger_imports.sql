-- Source profiles and durable file import batches.

CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_owner ON projects(id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_table_meta_store_owner ON table_meta(id, project_id, user_id);
CREATE TABLE IF NOT EXISTS ledger_sources (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    user_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    provider VARCHAR(120) NOT NULL,
    account VARCHAR(120) NOT NULL,
    feed VARCHAR(120) NOT NULL,
    table_id UUID NOT NULL UNIQUE,
    physical_table_name TEXT NOT NULL UNIQUE,
    mapping JSONB NOT NULL,
    rule_version INTEGER NOT NULL DEFAULT 1 CHECK (rule_version > 0),
    data_revision BIGINT NOT NULL DEFAULT 0 CHECK (data_revision >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, provider, account, feed),
    FOREIGN KEY (project_id, user_id) REFERENCES projects(id, user_id),
    FOREIGN KEY (table_id, project_id, user_id) REFERENCES table_meta(id, project_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_ledger_sources_owner ON ledger_sources(user_id, project_id);
CREATE TABLE IF NOT EXISTS import_batches (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES ledger_sources(id),
    file_id UUID REFERENCES files(id),
    storage_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    content_hash CHAR(64) NOT NULL,
    sheet_index INTEGER NOT NULL DEFAULT 0 CHECK (sheet_index = 0),
    rule_version INTEGER NOT NULL CHECK (rule_version > 0),
    status TEXT NOT NULL CHECK (status IN ('staging','uploaded','ready','committed','failed','expired')),
    preview_token UUID,
    preview_revision BIGINT,
    summary JSONB,
    result JSONB,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours',
    committed_at TIMESTAMPTZ,
    UNIQUE (source_id, content_hash, sheet_index, rule_version),
    UNIQUE (id, source_id),
    CHECK ((status = 'committed') = (result IS NOT NULL AND committed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_import_batches_history ON import_batches(source_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_import_batches_file ON import_batches(file_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_expiry ON import_batches(expires_at)
    WHERE status NOT IN ('committed','expired');
CREATE INDEX IF NOT EXISTS idx_import_batches_hash ON import_batches(content_hash, source_id);
CREATE TABLE IF NOT EXISTS import_requests (
    source_id UUID NOT NULL REFERENCES ledger_sources(id),
    request_key UUID NOT NULL,
    batch_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, request_key),
    FOREIGN KEY (batch_id, source_id) REFERENCES import_batches(id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_import_requests_batch ON import_requests(batch_id, source_id);
