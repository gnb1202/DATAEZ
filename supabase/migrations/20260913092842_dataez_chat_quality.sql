-- Private chat observations for the existing custom-JWT backend.
BEGIN;
SET LOCAL ROLE dataez_app;

CREATE TABLE IF NOT EXISTS quality_runs (
 id UUID PRIMARY KEY,
 conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 user_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
 assistant_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
 status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
 started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
 duration_ms INTEGER, error_code TEXT, version JSONB NOT NULL,
 review JSONB, reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
 reviewed_at TIMESTAMPTZ, candidate JSONB
);
CREATE INDEX IF NOT EXISTS quality_runs_recent ON quality_runs(started_at DESC, id);
CREATE INDEX IF NOT EXISTS quality_runs_conversation ON quality_runs(conversation_id);
CREATE TABLE IF NOT EXISTS message_feedback (
 message_id UUID PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
 rating INTEGER NOT NULL CHECK(rating IN (-1,1)),
 reason TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL DEFAULT '',
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE quality_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_feedback ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON quality_runs, message_feedback FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
  REVOKE ALL ON quality_runs, message_feedback FROM anon;
 END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
  REVOKE ALL ON quality_runs, message_feedback FROM authenticated;
 END IF;
END $$;

COMMIT;
