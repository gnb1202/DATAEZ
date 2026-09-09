"""Durable search-index outbox, independent of the optional vector extension."""

DDL = r"""
CREATE TABLE IF NOT EXISTS search_index_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
    table_meta_id uuid UNIQUE REFERENCES table_meta(id) ON DELETE CASCADE,
    file_id uuid UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    file_sha256 text,
    generation bigint NOT NULL DEFAULT 1 CHECK (generation > 0),
    completed_generation bigint NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','retry','succeeded','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_token uuid,
    lease_until timestamptz,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_error_code text,
    last_error text,
    last_success_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (num_nonnulls(table_meta_id,file_id)=1),
    CHECK (table_meta_id IS NULL OR project_id IS NOT NULL),
    CHECK ((status='processing') = (lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS search_index_jobs_due ON search_index_jobs(next_attempt_at,id)
    WHERE status IN ('pending','retry','processing');
CREATE INDEX IF NOT EXISTS search_index_jobs_scope ON search_index_jobs(user_id,project_id,updated_at DESC,id);

CREATE OR REPLACE FUNCTION dataez_enqueue_schema(target uuid) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO search_index_jobs(user_id,project_id,table_meta_id)
    SELECT t.user_id,t.project_id,t.id FROM table_meta t JOIN projects p ON p.id=t.project_id AND p.user_id=t.user_id
    WHERE t.id=target AND t.deleted_at IS NULL AND p.deleted_at IS NULL
    ON CONFLICT(table_meta_id) DO UPDATE SET generation=search_index_jobs.generation+1,
        status='pending',attempts=0,lease_token=NULL,lease_until=NULL,next_attempt_at=clock_timestamp(),
        last_error_code=NULL,last_error=NULL,updated_at=clock_timestamp();
END $$;

-- Deferred triggers enqueue after the mutation has acquired all its source /
-- metadata locks. Workers acquire metadata before the job fence, never vice versa.
CREATE OR REPLACE FUNCTION dataez_index_table_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM dataez_enqueue_schema(NEW.id);
    UPDATE search_index_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp()
    WHERE table_meta_id=NEW.id AND EXISTS(SELECT 1 FROM table_meta WHERE id=NEW.id AND deleted_at IS NOT NULL);
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS dataez_index_table ON table_meta;
CREATE CONSTRAINT TRIGGER dataez_index_table AFTER INSERT OR UPDATE ON table_meta
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dataez_index_table_changed();

CREATE OR REPLACE FUNCTION dataez_index_source_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM dataez_enqueue_schema(NEW.table_id);
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS dataez_index_source ON ledger_sources;
CREATE CONSTRAINT TRIGGER dataez_index_source AFTER INSERT OR UPDATE ON ledger_sources
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dataez_index_source_changed();

CREATE OR REPLACE FUNCTION dataez_index_batch_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status='committed' AND (TG_OP='INSERT' OR OLD.status IS DISTINCT FROM 'committed') THEN
        PERFORM dataez_enqueue_schema(table_id) FROM ledger_sources WHERE id=NEW.source_id;
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS dataez_index_batch ON import_batches;
CREATE CONSTRAINT TRIGGER dataez_index_batch AFTER INSERT OR UPDATE ON import_batches
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dataez_index_batch_changed();

CREATE OR REPLACE FUNCTION dataez_index_project_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.deleted_at IS NOT NULL THEN
        UPDATE search_index_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp()
        WHERE project_id=NEW.id;
    ELSE
        PERFORM dataez_enqueue_schema(id) FROM table_meta WHERE project_id=NEW.id ORDER BY id;
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS dataez_index_project ON projects;
CREATE CONSTRAINT TRIGGER dataez_index_project AFTER UPDATE ON projects
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dataez_index_project_changed();

-- First installation discovers existing tables, including missing or old indexes.
-- Subsequent starts preserve attempt counts, leases and failed states.
INSERT INTO search_index_jobs(user_id,project_id,table_meta_id)
SELECT t.user_id,t.project_id,t.id FROM table_meta t JOIN projects p ON p.id=t.project_id AND p.user_id=t.user_id
WHERE t.deleted_at IS NULL AND p.deleted_at IS NULL ON CONFLICT(table_meta_id) DO NOTHING;
"""
