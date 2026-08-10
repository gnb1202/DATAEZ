-- =========================================================
-- 001_pgvector_rag.sql
-- Hybrid Agentic RAG: schema_embeddings + document_chunks
--
-- Mounted at /docker-entrypoint-initdb.d/02_pgvector_rag.sql
-- so it runs after 01_init.sql on a fresh DB. For existing DBs
-- the same logic runs idempotently from db.py:ensure_rag_tables().
-- =========================================================

CREATE EXTENSION IF NOT EXISTS vector;

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
