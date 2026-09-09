ALTER TABLE ledger_sources ADD COLUMN IF NOT EXISTS input_mode text NOT NULL DEFAULT 'file' CHECK(input_mode IN ('file','cash'));
ALTER TABLE ledger_sources ADD COLUMN IF NOT EXISTS last_manual_entry_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS ledger_sources_cash_store ON ledger_sources(project_id) WHERE input_mode='cash';
CREATE TABLE IF NOT EXISTS cash_entries (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    project_id uuid NOT NULL,
    request_key uuid NOT NULL,
    request_hash text NOT NULL,
    payload jsonb NOT NULL,
    confirmation_token uuid NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','committed','cancelled')),
    source_id uuid,
    target_row_id bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
    committed_at timestamptz,
    UNIQUE(user_id,project_id,request_key),
    FOREIGN KEY(project_id,user_id) REFERENCES projects(id,user_id),
    FOREIGN KEY(source_id,target_row_id) REFERENCES source_events(source_id,target_row_id),
    CHECK ((status='committed') = (source_id IS NOT NULL AND target_row_id IS NOT NULL AND committed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS cash_entries_history ON cash_entries(user_id,project_id,created_at DESC,id);
CREATE INDEX IF NOT EXISTS cash_entries_similar ON cash_entries(project_id,(payload->>'occurred_on'),(payload->>'amount'),(payload->>'kind'))
    WHERE status='committed';
