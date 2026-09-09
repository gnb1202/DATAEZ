"""C-stage migration; existing sources require an explicit baseline check."""
DDL = """
ALTER TABLE ledger_sources ADD COLUMN IF NOT EXISTS event_index_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ledger_sources ADD COLUMN IF NOT EXISTS storage_mode TEXT NOT NULL DEFAULT 'canonical';
ALTER TABLE ledger_sources ADD COLUMN IF NOT EXISTS baseline_report JSONB;
ALTER TABLE ledger_sources ADD COLUMN IF NOT EXISTS baseline_at TIMESTAMPTZ;
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS review_version INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS import_rows (
    batch_id UUID NOT NULL,
    source_id UUID NOT NULL,
    row_number INTEGER NOT NULL,
    normalized JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    candidate_hash CHAR(64) NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('new','duplicate','candidate','conflict')),
    reason TEXT NOT NULL,
    matched JSONB,
    decision TEXT CHECK (decision IN ('include','exclude')),
    target_row_id BIGINT,
    PRIMARY KEY (batch_id,row_number),
    FOREIGN KEY (batch_id,source_id) REFERENCES import_batches(id,source_id),
    CHECK (decision IS NULL OR classification='candidate')
);
CREATE INDEX IF NOT EXISTS idx_import_rows_review ON import_rows(batch_id,classification,row_number);
CREATE INDEX IF NOT EXISTS idx_import_rows_source ON import_rows(source_id);
-- NULL event_id rows carry provenance but have no confirmed deduplication key.
CREATE TABLE IF NOT EXISTS source_events (
    source_id UUID NOT NULL REFERENCES ledger_sources(id),
    target_row_id BIGINT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('payment','refund')),
    event_id TEXT,
    event_key_hash CHAR(64),
    normalized JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    candidate_hash CHAR(64) NOT NULL,
    first_batch_id UUID,
    first_row_number INTEGER NOT NULL,
    PRIMARY KEY (source_id,target_row_id),
    UNIQUE (source_id,event_key_hash),
    CHECK ((event_id IS NULL) = (event_key_hash IS NULL)),
    FOREIGN KEY (first_batch_id,source_id) REFERENCES import_batches(id,source_id)
);
CREATE INDEX IF NOT EXISTS idx_source_events_candidate ON source_events(source_id,candidate_hash);
CREATE INDEX IF NOT EXISTS idx_source_events_batch ON source_events(first_batch_id,source_id);
"""
