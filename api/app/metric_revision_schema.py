DDL = """
CREATE TABLE IF NOT EXISTS metric_definition_revisions (
    metric_id uuid NOT NULL REFERENCES dashboard_widgets(id) ON DELETE CASCADE,
    revision integer NOT NULL CHECK(revision>0),
    title text NOT NULL,
    definition jsonb NOT NULL,
    request_key uuid,
    request_hash text,
    restored_from_revision integer,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(metric_id,revision),
    UNIQUE(metric_id,request_key),
    CHECK ((request_key IS NULL) = (request_hash IS NULL))
);
"""
