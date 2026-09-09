"""Hybrid Agentic RAG — schema retrieval + document search over pgvector.

Two retrieval channels share the same architecture:
  - schema_embeddings: one row per user table, used to route NL questions to
    the right table/columns before query_data is invoked.
  - document_chunks:   chunked user-uploaded manuals/policies, used for
    questions that cannot be answered from structured data.

Both use Hybrid search (dense vector cosine + PostgreSQL full-text ts_rank_cd) combined
with Reciprocal Rank Fusion (RRF). RRF avoids score normalization, so the
combination is a single SQL query.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any

from .config import settings
from .db import _connect
from .korean_text import to_tsquery_input, to_tsvector_input
from .tokens import count_tokens
from .llm import embed_one, generate_embeddings
from .exceptions import AppException, ResourceNotFound
from .rag_catalog import schema_snapshot, catalog_lines

logger = logging.getLogger(__name__)


def _require_rag():
    if not settings.rag_enabled:
        raise AppException(503, 'rag_disabled', '의미 검색이 꺼져 있습니다. 자료가 없다는 뜻은 아닙니다. 장부 목록으로 출처를 확인하세요.')


def _search_failure():
    return AppException(503, 'rag_unavailable', '의미 검색을 실행하지 못했습니다. 자료 없음으로 판단하지 마세요. 잠시 후 재시도하거나 장부 목록을 확인하세요.')


def _validate_vectors(vectors, count):
    if len(vectors) != count or any(len(v) != settings.openai_embedding_dim or any(not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('Embedding response count, dimensions or values are invalid')


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

    lines.extend(catalog_lines(table_meta))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Schema embeddings — write side
# ---------------------------------------------------------------------------

def index_schema(user_id: str, project_id: str, table_meta_id: str, *, job=None) -> str:
    """Strict worker entry point. Index and fenced job completion commit together."""
    _require_rag()
    from .index_jobs import fence, succeeded
    with _connect() as conn, conn.cursor() as cur:
        meta = schema_snapshot(cur, user_id, project_id, table_meta_id)
        if not meta:
            return 'missing'
        content = build_schema_doc(meta)
        content_hash = _hash_content(settings.openai_embedding_model + '\n' + content)
        cur.execute('SELECT content_hash FROM schema_embeddings WHERE table_meta_id=%s AND user_id=%s AND project_id=%s', (table_meta_id, user_id, project_id))
        previous = cur.fetchone()
        unchanged = previous and previous['content_hash'] == content_hash
    vec = None if unchanged else embed_one(content, background=bool(job))
    if vec is not None:
        _validate_vectors([vec], 1)
    tokens = None if unchanged else to_tsvector_input(content)
    with _connect() as conn, conn.cursor() as cur:
        current = schema_snapshot(cur, user_id, project_id, table_meta_id, lock=True)
        if not current:
            return 'missing'
        if build_schema_doc(current) != content:
            return 'stale'
        if job and not fence(cur, job):
            return 'superseded'
        if unchanged:
            # A concurrent administrative delete must not turn a skip into success.
            cur.execute('SELECT content_hash FROM schema_embeddings WHERE table_meta_id=%s AND user_id=%s AND project_id=%s', (table_meta_id, user_id, project_id))
            latest = cur.fetchone()
            if not latest or latest['content_hash'] != content_hash:
                return 'stale'
        else:
            cur.execute("""INSERT INTO schema_embeddings(table_meta_id,user_id,project_id,content,content_tsv,embedding,content_hash)
                VALUES (%s,%s,%s,%s,to_tsvector('simple',%s),%s::vector,%s)
                ON CONFLICT(table_meta_id) DO UPDATE SET user_id=EXCLUDED.user_id,project_id=EXCLUDED.project_id,
                content=EXCLUDED.content,content_tsv=EXCLUDED.content_tsv,embedding=EXCLUDED.embedding,
                content_hash=EXCLUDED.content_hash,updated_at=clock_timestamp()""",
                (table_meta_id, user_id, project_id, content, tokens, _vec_literal(vec), content_hash))
        if job:
            succeeded(cur, job)
        conn.commit()
    return 'current' if unchanged else 'updated'


def upsert_schema_embedding(user_id: str, project_id: str, table_meta_id: str) -> bool:
    """Compatibility for explicit CLI reindex; application writes use the outbox."""
    if not settings.rag_enabled:
        return False
    try:
        return index_schema(user_id, project_id, table_meta_id) == 'updated'
    except Exception:
        logger.exception('upsert_schema_embedding failed for table_meta=%s', table_meta_id)
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

# RRF over dense cosine + PostgreSQL full-text ts_rank_cd (not BM25).
# `<=>` is pgvector's cosine distance operator.
# `@@` matches a tsquery against a tsvector column.
# fused_score = sum over rankings of 1 / (rrf_k + rank).
_HYBRID_SCHEMA_SQL = """
WITH dense AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rnk
  FROM schema_embeddings
  WHERE user_id = %(uid)s AND project_id = %(pid)s
    AND EXISTS (SELECT 1 FROM table_meta t JOIN projects p ON p.id=t.project_id
      WHERE t.id=schema_embeddings.table_meta_id AND t.user_id=%(uid)s AND t.project_id=%(pid)s
        AND t.deleted_at IS NULL AND p.user_id=%(uid)s AND p.deleted_at IS NULL)
  ORDER BY embedding <=> %(qvec)s::vector
  LIMIT %(cand)s
),
sparse AS (
  SELECT id, ROW_NUMBER() OVER (
    ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('simple', %(qtok)s)) DESC
  ) AS rnk
  FROM schema_embeddings
  WHERE user_id = %(uid)s AND project_id = %(pid)s
    AND EXISTS (SELECT 1 FROM table_meta t JOIN projects p ON p.id=t.project_id
      WHERE t.id=schema_embeddings.table_meta_id AND t.user_id=%(uid)s AND t.project_id=%(pid)s
        AND t.deleted_at IS NULL AND p.user_id=%(uid)s AND p.deleted_at IS NULL)
    AND content_tsv @@ plainto_tsquery('simple', %(qtok)s)
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
    AND tm.user_id=%(uid)s AND tm.project_id=%(pid)s
JOIN projects p ON p.id=tm.project_id AND p.user_id=%(uid)s AND p.deleted_at IS NULL
ORDER BY f.score DESC
LIMIT %(k)s
"""

_HYBRID_DOCS_SQL = """
WITH dense AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS rnk
  FROM document_chunks
  WHERE user_id = %(uid)s
    AND (%(file_ids)s::uuid[] IS NULL OR file_id=ANY(%(file_ids)s::uuid[]))
    AND (%(pid)s::uuid IS NULL OR project_id = %(pid)s::uuid)
    AND EXISTS (SELECT 1 FROM files f WHERE f.id=document_chunks.file_id AND f.user_id=%(uid)s)
    AND (project_id IS NULL OR EXISTS (SELECT 1 FROM projects p WHERE p.id=document_chunks.project_id
         AND p.user_id=%(uid)s AND p.deleted_at IS NULL))
  ORDER BY embedding <=> %(qvec)s::vector
  LIMIT %(cand)s
),
sparse AS (
  SELECT id, ROW_NUMBER() OVER (
    ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('simple', %(qtok)s)) DESC
  ) AS rnk
  FROM document_chunks
  WHERE user_id = %(uid)s
    AND (%(file_ids)s::uuid[] IS NULL OR file_id=ANY(%(file_ids)s::uuid[]))
    AND (%(pid)s::uuid IS NULL OR project_id = %(pid)s::uuid)
    AND EXISTS (SELECT 1 FROM files f WHERE f.id=document_chunks.file_id AND f.user_id=%(uid)s)
    AND (project_id IS NULL OR EXISTS (SELECT 1 FROM projects p WHERE p.id=document_chunks.project_id
         AND p.user_id=%(uid)s AND p.deleted_at IS NULL))
    AND content_tsv @@ plainto_tsquery('simple', %(qtok)s)
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
JOIN files fi ON fi.id=d.file_id AND fi.user_id=%(uid)s
LEFT JOIN projects p ON p.id=d.project_id AND p.user_id=%(uid)s AND p.deleted_at IS NULL
WHERE d.project_id IS NULL OR p.id IS NOT NULL
ORDER BY f.score DESC
LIMIT %(k)s
"""


def hybrid_search_schema(
    user_id: str,
    project_id: str,
    query: str,
    top_k: int | None = None,
    ledger=None,
) -> list[dict[str, Any]]:
    """Hybrid-search schema_embeddings for a NL query within a project.

    Returns rows: {table_meta_id, table_name, content, score, project_id}.
    Empty list means no candidates. Disabled/unavailable search raises a typed error.
    """
    _require_rag()
    if not query.strip():
        return []
    k = max(1, min(top_k or settings.rag_top_k, 10))
    try:
        qvec = embed_one(query, ledger=ledger)
        _validate_vectors([qvec], 1)
        params = {
            "qvec": _vec_literal(qvec),
            "qtext": query,
            "qtok": to_tsquery_input(query),
            "uid": user_id,
            "pid": project_id,
            "cand": k * 4,
            "rrf": settings.rag_rrf_k,
            "k": k,
        }
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(settings.query_timeout_ms),))
                cur.execute(_HYBRID_SCHEMA_SQL, params)
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("hybrid_search_schema failed for query=%r", query[:100])
        raise _search_failure() from None


def schema_index_coverage(user_id, project_id):
    """Distinguish unindexed tables from a successful search with no matches."""
    _require_rag()
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT count(*) AS total,count(s.id) AS indexed,
                    count(*) FILTER(WHERE j.status IN ('pending','processing','retry','failed')) AS updating
                FROM table_meta t JOIN projects p ON p.id=t.project_id AND p.user_id=t.user_id
                LEFT JOIN schema_embeddings s ON s.table_meta_id=t.id AND s.user_id=t.user_id AND s.project_id=t.project_id
                LEFT JOIN search_index_jobs j ON j.table_meta_id=t.id AND j.user_id=t.user_id AND j.project_id=t.project_id
                WHERE t.user_id=%s AND t.project_id=%s AND t.deleted_at IS NULL AND p.deleted_at IS NULL AND to_jsonb(t)->>'original_file_id' IS NULL""", (user_id, project_id))
            result = dict(cur.fetchone())
        return {**result, 'missing': result['total'] - result['indexed']}
    except Exception:
        logger.exception('Schema coverage lookup failed')
        raise _search_failure() from None


# ---------------------------------------------------------------------------
# Document chunks — write side
# ---------------------------------------------------------------------------

# OpenAI embeddings API hard-caps batch size; 96 keeps us well under the limit
# and means most documents fit in 1-2 round trips.
_EMBED_BATCH_SIZE = 96


def document_index_coverage(user_id, project_id=None):
    _require_rag()
    try:
        with _connect() as conn:
            row = conn.execute("""SELECT count(*) AS total,
                count(*) FILTER(WHERE j.status IN ('pending','processing','retry','failed')) AS updating
                FROM search_index_jobs j JOIN files f ON f.id=j.file_id AND f.user_id=j.user_id
                LEFT JOIN projects p ON p.id=j.project_id AND p.user_id=j.user_id AND p.deleted_at IS NULL
                WHERE j.user_id=%s AND (%s::uuid IS NULL OR j.project_id=%s::uuid)
                    AND (j.project_id IS NULL OR p.id IS NOT NULL)""", (user_id, project_id, project_id)).fetchone()
        return dict(row)
    except Exception:
        logger.exception('Document coverage lookup failed')
        raise _search_failure() from None


def chunk_and_embed_document(
    file_id: str,
    user_id: str,
    project_id: str | None,
    chunks: list[str],
    metadata_per_chunk: list[dict[str, Any]] | None = None,
    *, job=None, file_snapshot=None, file_digest=None,
) -> int:
    """Embed pre-chunked document text and insert into document_chunks.

    Caller is responsible for text extraction + chunking (document_processor.py).
    Returns the number of chunks inserted. Embedding is done in batches to
    avoid hitting OpenAI's per-request input limit.
    """
    _require_rag()
    if not chunks:
        raise AppException(422, 'document_empty', '문서에서 검색할 텍스트를 찾지 못했습니다.')

    metas = metadata_per_chunk or [{} for _ in chunks]
    if len(metas) != len(chunks):
        raise ValueError("metadata_per_chunk must align with chunks")

    def owned(cur, *, lock=False):
        cur.execute('SELECT * FROM files WHERE id=%s AND user_id=%s' + (' FOR UPDATE' if lock else ''), (file_id, user_id))
        current_file = cur.fetchone()
        if not current_file:
            raise ResourceNotFound('문서')
        if file_snapshot and dict(current_file) != file_snapshot:
            raise AppException(422, 'document_changed', '문서 등록 정보가 변경되었습니다. 원본을 다시 확인해 주세요.')
        if project_id is not None:
            cur.execute('SELECT id FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL' + (' FOR SHARE' if lock else ''), (project_id, user_id))
            if not cur.fetchone():
                raise ResourceNotFound('가게')
        cur.execute('SELECT 1 FROM document_chunks WHERE file_id=%s AND (user_id<>%s OR project_id IS DISTINCT FROM %s::uuid) LIMIT 1', (file_id, user_id, project_id))
        if cur.fetchone():
            raise ResourceNotFound('문서')

    try:
        with _connect() as conn, conn.cursor() as cur:
            owned(cur)
        prepared = []
        # Prepare every batch before replacing any searchable content.
        for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + _EMBED_BATCH_SIZE]
            vectors = generate_embeddings(batch, background=True) if job else generate_embeddings(batch)
            _validate_vectors(vectors, len(batch))
            for offset, (text, vec) in enumerate(zip(batch, vectors)):
                idx = batch_start + offset
                prepared.append((file_id, user_id, project_id, idx, text, to_tsvector_input(text),
                                 _vec_literal(vec), json.dumps(metas[idx]), count_tokens(text)))
        with _connect() as conn, conn.cursor() as cur:
            owned(cur, lock=True)
            if job:
                from .index_jobs import fence, succeeded
                if not fence(cur, job):
                    return 0
            cur.execute('DELETE FROM document_chunks WHERE file_id=%s AND user_id=%s', (file_id, user_id))
            cur.executemany("""INSERT INTO document_chunks(file_id,user_id,project_id,chunk_index,
                content,content_tsv,embedding,metadata,token_count)
                VALUES (%s,%s,%s,%s,%s,to_tsvector('simple',%s),%s::vector,%s::jsonb,%s)""", prepared)
            if job:
                cur.execute('UPDATE search_index_jobs SET file_sha256=%s WHERE id=%s', (file_digest, job['id']))
                succeeded(cur, job)
            conn.commit()
        return len(prepared)
    except AppException:
        raise
    except Exception:
        logger.exception("chunk_and_embed_document failed for file_id=%s", file_id)
        raise AppException(503, 'rag_index_failed', '문서 색인에 실패했습니다. 기존 검색 자료는 유지됩니다. 잠시 후 다시 시도해주세요.') from None


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
    ledger=None,
    file_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid-search document_chunks. project_id None searches all of the user's docs."""
    _require_rag()
    if not query.strip():
        return []
    k = max(1, min(top_k or settings.rag_top_k, 10))
    try:
        qvec = embed_one(query, ledger=ledger)
        _validate_vectors([qvec], 1)
        params = {
            "qvec": _vec_literal(qvec),
            "qtext": query,
            "qtok": to_tsquery_input(query),
            "uid": user_id,
            "pid": project_id,
            "file_ids": file_ids,
            "cand": k * 4,
            "rrf": settings.rag_rrf_k,
            "k": k,
        }
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(settings.query_timeout_ms),))
                cur.execute(_HYBRID_DOCS_SQL, params)
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("hybrid_search_documents failed for query=%r", query[:100])
        raise _search_failure() from None
