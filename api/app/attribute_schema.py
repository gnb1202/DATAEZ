"""H: durable previews and append-only restoration evidence (migration 006)."""
DDL = """
CREATE TABLE IF NOT EXISTS source_attribute_restorations (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES ledger_sources(id),
    status TEXT NOT NULL CHECK (status IN ('ready','blocked','applied')),
    additions JSONB NOT NULL,
    mapping JSONB NOT NULL,
    old_rule_version INTEGER NOT NULL,
    new_rule_version INTEGER NOT NULL,
    snapshot_hash CHAR(64) NOT NULL,
    report JSONB NOT NULL,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '30 minutes',
    applied_at TIMESTAMPTZ,
    UNIQUE(id, source_id),
    CHECK ((status='applied') = (result IS NOT NULL AND applied_at IS NOT NULL)),
    CHECK (new_rule_version=old_rule_version+1)
);
CREATE INDEX IF NOT EXISTS idx_attribute_restorations_history ON source_attribute_restorations(source_id,created_at DESC,id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_attribute_restoration_version ON source_attribute_restorations(source_id,new_rule_version) WHERE status='applied';
CREATE TABLE IF NOT EXISTS source_attribute_changes (
    restoration_id UUID NOT NULL,
    source_id UUID NOT NULL,
    target_row_id BIGINT NOT NULL,
    before_normalized JSONB NOT NULL,
    after_normalized JSONB NOT NULL,
    origin_batch_id UUID,
    origin_row_number INTEGER NOT NULL,
    PRIMARY KEY(restoration_id,target_row_id),
    FOREIGN KEY(restoration_id,source_id) REFERENCES source_attribute_restorations(id,source_id),
    FOREIGN KEY(source_id,target_row_id) REFERENCES source_events(source_id,target_row_id),
    FOREIGN KEY(origin_batch_id,source_id) REFERENCES import_batches(id,source_id)
);
CREATE INDEX IF NOT EXISTS idx_attribute_changes_event ON source_attribute_changes(source_id,target_row_id);
CREATE INDEX IF NOT EXISTS idx_attribute_changes_origin ON source_attribute_changes(origin_batch_id,source_id);
"""
