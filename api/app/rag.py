"""Hybrid Agentic RAG — schema retrieval + document search over pgvector.

Two retrieval channels share the same architecture:
  - schema_embeddings: one row per user table, used to route NL questions to
    the right table/columns before query_data is invoked.
  - document_chunks:   chunked user-uploaded manuals/policies, used for
    questions that cannot be answered from structured data.

Both use Hybrid search (dense vector cosine + BM25 via tsvector) combined
with Reciprocal Rank Fusion (RRF). RRF avoids score normalization, so the
combination is a single SQL query.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from .config import settings
from .db import _connect
from .llm import embed_one, generate_embeddings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec_literal(vec: list[float]) -> str:
    """pgvector accepts text input like '[1.0,2.0,3.0]' which is then cast via ::vector."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_schema_doc(table_meta: dict[str, Any]) -> str:
    """Render a table_meta row + its columns_schema into a natural-language doc.

    The output is what gets embedded — it must be readable Korean prose so the
    embedding model picks up semantic intent (e.g. '매출' ≈ 'revenue').
    """
    name = table_meta.get("name", "")
    description = (table_meta.get("description") or "").strip()
    columns_schema = table_meta.get("columns_schema") or []
    if isinstance(columns_schema, str):
        try:
            columns_schema = json.loads(columns_schema)
        except json.JSONDecodeError:
            columns_schema = []

    lines: list[str] = [f"테이블명: {name}"]
    if description:
        lines.append(f"설명: {description}")

    if columns_schema:
        lines.append("컬럼:")
        for col in columns_schema:
            col_name = col.get("name", "")
            col_type = col.get("type", "")
            col_desc = (col.get("description") or "").strip()
            entry = f"- {col_name} ({col_type})"
            if col_desc:
                entry += f": {col_desc}"
            lines.append(entry)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Schema embeddings — write side
# ---------------------------------------------------------------------------

def upsert_schema_embedding(
    user_id: str,
    project_id: str,
    table_meta_id: str,
) -> bool:
    """Re-embed and persist the schema doc for a table_meta row.

    Skips the OpenAI call if content is unchanged (compared via SHA-256 hash).
    Returns True if the embedding was inserted or updated, False if skipped.
    Errors are logged but not raised — embedding failure must never break a
    successful CSV import or schema edit.
    """
    if not settings.rag_enabled:
        return False

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, description, columns_schema, project_id, user_id
                    FROM table_meta
                    WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                    """,
                    (table_meta_id, user_id),
                )
                meta = cur.fetchone()
                if not meta:
                    logger.warning("upsert_schema_embedding: table_meta %s not found", table_meta_id)
                    return False

                content = build_schema_doc(meta)
                content_hash = _hash_content(content)

                cur.execute(
                    "SELECT content_hash FROM schema_embeddings WHERE table_meta_id = %s",
                    (table_meta_id,),
                )
                existing = cur.fetchone()
                if existing and existing["content_hash"] == content_hash:
                    return False  # no-op: identical content

                vec = embed_one(content)
                vec_str = _vec_literal(vec)

                if existing:
                    cur.execute(
                        """
                        UPDATE schema_embeddings
                        SET content = %s,
                            embedding = %s::vector,
                            content_hash = %s,
                            updated_at = NOW()
                        WHERE table_meta_id = %s
                        """,
                        (content, vec_str, content_hash, table_meta_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO schema_embeddings
                          (table_meta_id, user_id, project_id, content, embedding, content_hash)
                        VALUES (%s, %s, %s, %s, %s::vector, %s)
                        """,
                        (table_meta_id, user_id, project_id, content, vec_str, content_hash),
                    )
            conn.commit()
        logger.info("schema_embedding upserted for table_meta=%s", table_meta_id)
        return True
    except Exception:
        logger.exception("upsert_schema_embedding failed for table_meta=%s", table_meta_id)
        return False


def delete_schema_embedding(table_meta_id: str) -> None:
    """Best-effort cleanup. CASCADE on table_meta drop already handles this,
    but call sites may want explicit invalidation."""
    if not settings.rag_enabled:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM schema_embeddings WHERE table_meta_id = %s",
                    (table_meta_id,),
                )
            conn.commit()
    except Exception:
        logger.exception("delete_schema_embedding failed for %s", table_meta_id)


# ---------------------------------------------------------------------------
# Hybrid search — read side
# ---------------------------------------------------------------------------

# RRF over (dense ranking by cosine distance) + (sparse ranking by ts_rank_cd).
# `<=>` is pgvector's cosine distance operator.
# `@@` matches a tsquery against a tsvector column.
# fused_score = sum over rankings of 1 / (rrf_k + rank).
_HYBRID_SCHEMA_SQL = """
WITH dense AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rnk
  FROM schema_embeddings
  WHERE user_id = %(uid)s AND project_id = %(pid)s
  ORDER BY embedding <=> %(qvec)s::vector
  LIMIT %(cand)s
),
sparse AS (
  SELECT id, ROW_NUMBER() OVER (
    ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('simple', %(qtext)s)) DESC
  ) AS rnk
  FROM schema_embeddings
  WHERE user_id = %(uid)s AND project_id = %(pid)s
    AND content_tsv @@ plainto_tsquery('simple', %(qtext)s)
  LIMIT %(cand)s
),
fused AS (
  SELECT id, SUM(1.0 / (%(rrf)s + rnk)) AS score
  FROM (SELECT id, rnk FROM dense UNION ALL SELECT id, rnk FROM sparse) u
  GROUP BY id
)
SELECT s.table_meta_id, s.content, f.score::float AS score,
       tm.name AS table_name, tm.project_id
FROM fused f
JOIN schema_embeddings s ON s.id = f.id
JOIN table_meta tm ON tm.id = s.table_meta_id AND tm.deleted_at IS NULL
ORDER BY f.score DESC
LIMIT %(k)s
"""

_HYBRID_DOCS_SQL = """
WITH dense AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rnk
  FROM document_chunks
  WHERE user_id = %(uid)s
    AND (%(pid)s::uuid IS NULL OR project_id = %(pid)s::uuid)
  ORDER BY embedding <=> %(qvec)s::vector
  LIMIT %(cand)s
),
sparse AS (
  SELECT id, ROW_NUMBER() OVER (
    ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('simple', %(qtext)s)) DESC
  ) AS rnk
  FROM document_chunks
  WHERE user_id = %(uid)s
    AND (%(pid)s::uuid IS NULL OR project_id = %(pid)s::uuid)
    AND content_tsv @@ plainto_tsquery('simple', %(qtext)s)
  LIMIT %(cand)s
),
fused AS (
  SELECT id, SUM(1.0 / (%(rrf)s + rnk)) AS score
  FROM (SELECT id, rnk FROM dense UNION ALL SELECT id, rnk FROM sparse) u
  GROUP BY id
)
SELECT d.id, d.file_id, d.chunk_index, d.content, d.metadata,
       f.score::float AS score
FROM fused f
JOIN document_chunks d ON d.id = f.id
ORDER BY f.score DESC
LIMIT %(k)s
"""


def hybrid_search_schema(
    user_id: str,
    project_id: str,
    query: str,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Hybrid-search schema_embeddings for a NL query within a project.

    Returns rows: {table_meta_id, table_name, content, score, project_id}.
    Empty list on failure or when RAG is disabled.
    """
    if not settings.rag_enabled or not query.strip():
        return []
    k = top_k or settings.rag_top_k
    try:
        qvec = embed_one(query)
        params = {
            "qvec": _vec_literal(qvec),
            "qtext": query,
            "uid": user_id,
            "pid": project_id,
            "cand": k * 4,
            "rrf": settings.rag_rrf_k,
            "k": k,
        }
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_HYBRID_SCHEMA_SQL, params)
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("hybrid_search_schema failed for query=%r", query[:100])
        return []


# ---------------------------------------------------------------------------
# Document chunks — write side
# ---------------------------------------------------------------------------

# OpenAI embeddings API hard-caps batch size; 96 keeps us well under the limit
# and means most documents fit in 1-2 round trips.
_EMBED_BATCH_SIZE = 96


def chunk_and_embed_document(
    file_id: str,
    user_id: str,
    project_id: str | None,
    chunks: list[str],
    metadata_per_chunk: list[dict[str, Any]] | None = None,
) -> int:
    """Embed pre-chunked document text and insert into document_chunks.

    Caller is responsible for text extraction + chunking (document_processor.py).
    Returns the number of chunks inserted. Embedding is done in batches to
    avoid hitting OpenAI's per-request input limit.
    """
    if not settings.rag_enabled:
        return 0
    if not chunks:
        return 0

    metas = metadata_per_chunk or [{} for _ in chunks]
    if len(metas) != len(chunks):
        raise ValueError("metadata_per_chunk must align with chunks")

    inserted = 0
    try:
        # Drop any prior chunks for this file (re-ingest replaces).
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_chunks WHERE file_id = %s AND user_id = %s",
                    (file_id, user_id),
                )
            conn.commit()

        # Embed in batches.
        for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + _EMBED_BATCH_SIZE]
            vectors = generate_embeddings(batch)

            with _connect() as conn:
                with conn.cursor() as cur:
                    for offset, (text, vec) in enumerate(zip(batch, vectors)):
                        idx = batch_start + offset
                        meta = metas[idx]
                        cur.execute(
                            """
                            INSERT INTO document_chunks
                              (file_id, user_id, project_id, chunk_index,
                               content, embedding, metadata, token_count)
                            VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb, %s)
                            """,
                            (
                                file_id, user_id, project_id, idx,
                                text, _vec_literal(vec), json.dumps(meta), len(text),
                            ),
                        )
                conn.commit()
            inserted += len(batch)
        logger.info("Embedded %d chunks for file_id=%s", inserted, file_id)
        return inserted
    except Exception:
        logger.exception("chunk_and_embed_document failed for file_id=%s", file_id)
        return inserted


def delete_document_chunks(file_id: str, user_id: str) -> int:
    """Remove all chunks for a file. CASCADE handles this when the file is deleted,
    but call sites may want explicit invalidation before re-ingest."""
    if not settings.rag_enabled:
        return 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_chunks WHERE file_id = %s AND user_id = %s",
                    (file_id, user_id),
                )
                count = cur.rowcount
            conn.commit()
        return count
    except Exception:
        logger.exception("delete_document_chunks failed for %s", file_id)
        return 0


def hybrid_search_documents(
    user_id: str,
    query: str,
    project_id: str | None = None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Hybrid-search document_chunks. project_id None searches all of the user's docs."""
    if not settings.rag_enabled or not query.strip():
        return []
    k = top_k or settings.rag_top_k
    try:
        qvec = embed_one(query)
        params = {
            "qvec": _vec_literal(qvec),
            "qtext": query,
            "uid": user_id,
            "pid": project_id,
            "cand": k * 4,
            "rrf": settings.rag_rrf_k,
            "k": k,
        }
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_HYBRID_DOCS_SQL, params)
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("hybrid_search_documents failed for query=%r", query[:100])
        return []
