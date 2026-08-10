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

BEGIN;

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

COMMIT;
