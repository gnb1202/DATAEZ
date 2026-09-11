-- DATAEZ initial schema, assembled from existing verified SQL migrations.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
SET search_path TO public, extensions;

-- Source: db/init.sql
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255),
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS files (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  filename TEXT NOT NULL,
  storage_key TEXT,
  size_bytes BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS query_history (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  file_id UUID REFERENCES files(id),
  question TEXT NOT NULL,
  response_summary TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash TEXT UNIQUE NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  revoked_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  file_id UUID REFERENCES files(id),
  title TEXT NOT NULL DEFAULT 'New conversation',
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  steps JSONB,
  charts JSONB,
  table_data JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboard_widgets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  file_id UUID REFERENCES files(id),
  widget_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  widget_data JSONB NOT NULL,
  layout JSONB NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =========================================================
-- Projects & Table Meta (코어 기능 재정의)
-- =========================================================

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT '',
  deleted_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);

CREATE TABLE IF NOT EXISTS table_meta (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT '',
  columns_schema JSONB NOT NULL DEFAULT '[]',
  row_count INTEGER NOT NULL DEFAULT 0,
  source_file_id UUID REFERENCES files(id),
  deleted_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_table_meta_project ON table_meta(project_id);
CREATE INDEX IF NOT EXISTS idx_table_meta_user ON table_meta(user_id);

-- =========================================================
-- Performance indexes for common query patterns
-- =========================================================
CREATE INDEX IF NOT EXISTS idx_files_user_created ON files(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_query_history_user_created ON query_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_user_updated ON projects(user_id, updated_at DESC);

-- =========================================================
-- Table & Column Comments (for documentation / tooling)
-- =========================================================
COMMENT ON TABLE users IS 'Registered user accounts';
COMMENT ON TABLE files IS 'Uploaded file metadata (CSV/XLSX). Actual data in S3 or local storage';
COMMENT ON TABLE query_history IS 'Legacy query log — retained for audit purposes';
COMMENT ON TABLE refresh_tokens IS 'JWT refresh token hashes for token rotation';
COMMENT ON TABLE conversations IS 'AI chat conversations, scoped to a project';
COMMENT ON TABLE messages IS 'Individual messages within a conversation (user + assistant)';
COMMENT ON TABLE dashboard_widgets IS 'Pinned charts and KPIs on the dashboard';
COMMENT ON TABLE projects IS 'Top-level workspace — groups tables and conversations';
COMMENT ON TABLE table_meta IS 'Metadata for user data tables (schema, row count, source file)';

COMMENT ON COLUMN messages.steps IS 'JSON array of agent reasoning steps (tool calls, outputs)';
COMMENT ON COLUMN messages.charts IS 'JSON array of generated chart configs';
COMMENT ON COLUMN messages.table_data IS 'JSON array of query result rows';
COMMENT ON COLUMN table_meta.columns_schema IS 'JSON array of {name, type, nullable} column definitions';
COMMENT ON COLUMN dashboard_widgets.widget_data IS 'JSON blob with chart config or KPI data';
COMMENT ON COLUMN dashboard_widgets.layout IS 'JSON object with grid position {x, y, w, h}';

-- =========================================================
-- Audit Log (변경 이력 추적)
-- =========================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT,
  detail JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id);
COMMENT ON TABLE audit_log IS 'Tracks who changed what and when — for compliance and undo support';

-- Source: db/migrations/001_pgvector_rag.sql
-- =========================================================
-- 001_pgvector_rag.sql
-- Hybrid Agentic RAG: schema_embeddings + document_chunks
--
-- Mounted at /docker-entrypoint-initdb.d/02_pgvector_rag.sql
-- so it runs after 01_init.sql on a fresh DB. For existing DBs
-- the same logic runs idempotently from db.py:ensure_rag_tables().
-- =========================================================


-- ---------------------------------------------------------
-- Schema Embeddings: one row per table_meta. Used to route
-- natural-language questions to the right user table/columns
-- before query_data is called.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  table_meta_id UUID NOT NULL UNIQUE REFERENCES table_meta(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  embedding vector(1536) NOT NULL,
  content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_schema_emb_vec
  ON schema_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_schema_emb_tsv
  ON schema_embeddings USING GIN (content_tsv);

CREATE INDEX IF NOT EXISTS idx_schema_emb_user_project
  ON schema_embeddings(user_id, project_id);

COMMENT ON TABLE schema_embeddings IS
  'One row per table_meta. Natural-language description of the table + its columns, '
  'used by search_schema for retrieval-augmented Text-to-SQL.';

-- ---------------------------------------------------------
-- Document Chunks: chunked + embedded user-uploaded docs
-- (manuals, policies). Phase 5 — table is created now so
-- the search_documents tool can be wired in cleanly.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding vector(1536) NOT NULL,
  content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  metadata JSONB NOT NULL DEFAULT '{}',
  token_count INTEGER,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE (file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_vec
  ON document_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_tsv
  ON document_chunks USING GIN (content_tsv);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_user_project
  ON document_chunks(user_id, project_id);

COMMENT ON TABLE document_chunks IS
  'Chunked + embedded user-uploaded documents (PDF/MD). Used by search_documents '
  'for unstructured questions that the SQL tools cannot answer.';

-- Source: db/migrations/002_korean_fts.sql
-- Korean full-text search.
--
-- 001 defined content_tsv as GENERATED ALWAYS AS (to_tsvector('simple', content)),
-- which splits Korean on whitespace only. Korean is agglutinative, so 매출이,
-- 매출을, and 매출은 became three unrelated tokens and none of them matched a
-- query for 매출. The sparse half of the hybrid search was effectively dead for
-- the product's only language while still paying for its GIN index.
--
-- A generated column cannot call application code, so the column becomes an
-- ordinary tsvector that the app populates from morpheme-analysed text. The
-- 'simple' config is kept on purpose: it does no stemming, which is what we
-- want once the input is already morphemes.
--
-- Existing rows are left with an empty tsvector until reindexed; run
--   python -m scripts.reindex_fts
-- which re-analyses stored content without re-embedding it.


-- ── schema_embeddings ────────────────────────────────────────────────────
ALTER TABLE schema_embeddings DROP COLUMN IF EXISTS content_tsv;
ALTER TABLE schema_embeddings ADD COLUMN content_tsv tsvector;

CREATE INDEX IF NOT EXISTS idx_schema_emb_tsv
  ON schema_embeddings USING GIN (content_tsv);

-- ── document_chunks ──────────────────────────────────────────────────────
ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_tsv;
ALTER TABLE document_chunks ADD COLUMN content_tsv tsvector;

CREATE INDEX IF NOT EXISTS idx_doc_chunks_tsv
  ON document_chunks USING GIN (content_tsv);


-- Source: db/migrations/003_metric_scheduling.sql
-- Also applied idempotently by ensure_dashboard_widgets_table on startup.
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS refresh_interval_seconds INTEGER NOT NULL DEFAULT 0
  CHECK (refresh_interval_seconds IN (0, 3600, 86400));
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS next_refresh_at TIMESTAMPTZ;
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS refresh_failures INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_widgets_due ON dashboard_widgets(next_refresh_at)
  WHERE next_refresh_at IS NOT NULL AND refresh_interval_seconds > 0;

-- Source: db/migrations/004_ledger_imports.sql
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

-- Source: db/migrations/005_event_review.sql
-- Event review and explicit ledger baselines.

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

-- Source: db/migrations/006_attribute_restoration.sql
-- H: source attribute restoration previews and provenance.
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

-- Source: db/migrations/007_search_index_jobs.sql
-- I: durable search indexing jobs; apply after 006.

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

-- Source: db/migrations/008_metric_definition_revisions.sql

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

-- Source: db/migrations/009_cash_entries.sql
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

-- Source: db/migrations/010_file_library.sql

CREATE TABLE IF NOT EXISTS library_entries (
    file_id UUID PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    content_hash CHAR(64),
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_library_owner_store ON library_entries(user_id,project_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_library_content ON library_entries
    (user_id,project_id,content_hash)
    WHERE content_hash IS NOT NULL AND deleted_at IS NULL;
ALTER TABLE library_entries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON library_entries FROM PUBLIC;

-- Source: db/migrations/011_widget_save_keys.sql
-- Columns otherwise added by app.db's persistent startup migrations.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS table_id UUID REFERENCES table_meta(id);
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS total_tokens INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12,6);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS usage JSONB;
-- Idempotent saves from analysis results. Schema mirror: app/widget_saves.py.
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS save_key TEXT;
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS save_fingerprint CHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_widget_save_key ON dashboard_widgets(user_id,project_id,save_key)
    WHERE save_key IS NOT NULL;

-- Source: db/migrations/012_original_file_analysis.sql

ALTER TABLE table_meta ADD COLUMN IF NOT EXISTS original_file_id UUID REFERENCES files(id);
ALTER TABLE table_meta ADD COLUMN IF NOT EXISTS original_content_hash CHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_original_file_analysis
    ON table_meta(user_id,project_id,original_file_id) WHERE original_file_id IS NOT NULL;
CREATE OR REPLACE FUNCTION reject_original_file_write() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Original file analysis rows are read-only' USING ERRCODE='55000';
END $$;

-- Source: db/migrations/013_sample_workspace.sql
CREATE TABLE IF NOT EXISTS sample_workspaces (
    user_id UUID PRIMARY KEY,
    project_id UUID NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE
);
ALTER TABLE sample_workspaces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sample_workspaces FROM PUBLIC;

-- Source: db/migrations/014_sample_restarts.sql
-- Runtime ensure_library() applies the same additive migration.
CREATE TABLE IF NOT EXISTS sample_workspace_restarts (
    user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    previous_project_id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, request_id)
);
ALTER TABLE sample_workspace_restarts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sample_workspace_restarts FROM PUBLIC;

-- This application authenticates through FastAPI, never the public Data API.
-- Protect the initial installation in the same transaction as table creation.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
  END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;
