
CREATE TABLE IF NOT EXISTS maintenance_runs (
    kind TEXT PRIMARY KEY CHECK (kind IN ('index','metrics','cleanup')),
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    last_started_at TIMESTAMPTZ,
    last_finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle','running','succeeded','timeout','failed')),
    processed INTEGER NOT NULL DEFAULT 0,
    attempts BIGINT NOT NULL DEFAULT 0,
    failures BIGINT NOT NULL DEFAULT 0,
    CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);
ALTER TABLE maintenance_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON maintenance_runs FROM PUBLIC;
