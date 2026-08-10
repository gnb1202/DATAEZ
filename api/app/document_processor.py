"""Document text extraction + recursive chunking for RAG ingestion.

Supports PDF (.pdf), Markdown (.md), plain text (.txt).
Chunking is char-based with paragraph/sentence-aware splitting and overlap,
mirroring LangChain's RecursiveCharacterTextSplitter behavior on a small scale.
"""

from __future__ import annotations

import io
import logging
from typing import Iterator

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100

# Tried in order — first separator that splits the chunk is used.
_SEPARATORS: list[str] = ["\n\n", "\n", ". ", "。", " ", ""]


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(content: bytes, filename: str) -> str:
    """Extract plain text from a document by extension. Returns empty string on failure."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_pdf(content)
    if name.endswith(".md") or name.endswith(".txt"):
        return _decode_text(content)
    raise ValueError(f"Unsupported document type: {filename}")


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            logger.warning("PDF page %d extraction failed", i, exc_info=True)
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _decode_text(content: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Recursive char splitter — tries paragraph → line → sentence → space → char.

    The result is a list of non-empty chunks, each at most chunk_size chars,
    with chunk_overlap chars carried over from the previous chunk to preserve
    context across boundaries.
    """
    text = text.strip()
    if not text:
        return []
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(chunk_size // 4, 0)

    pieces = list(_recursive_split(text, chunk_size, _SEPARATORS))
    return _merge_with_overlap(pieces, chunk_size, chunk_overlap)


def _recursive_split(text: str, chunk_size: int, separators: list[str]) -> Iterator[str]:
    """Yield sub-pieces ≤ chunk_size by recursively descending the separator list."""
    if len(text) <= chunk_size:
        if text.strip():
            yield text
        return

    sep = separators[0] if separators else ""
    rest = separators[1:] if separators else []

    if sep == "":
        # Final fallback: hard cut on chars.
        for i in range(0, len(text), chunk_size):
            piece = text[i : i + chunk_size]
            if piece.strip():
                yield piece
        return

    parts = text.split(sep)
    buf = ""
    for part in parts:
        candidate = (buf + sep + part) if buf else part
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        # Flush buf if it fits, otherwise descend.
        if buf:
            if len(buf) <= chunk_size:
                yield buf
            else:
                yield from _recursive_split(buf, chunk_size, rest)
        if len(part) <= chunk_size:
            buf = part
        else:
            yield from _recursive_split(part, chunk_size, rest)
            buf = ""
    if buf:
        if len(buf) <= chunk_size:
            yield buf
        else:
            yield from _recursive_split(buf, chunk_size, rest)


def _merge_with_overlap(pieces: list[str], chunk_size: int, overlap: int) -> list[str]:
    """Greedily merge small pieces into chunks of ~chunk_size with overlap tail."""
    chunks: list[str] = []
    cur = ""
    for p in pieces:
        if not cur:
            cur = p
            continue
        if len(cur) + 1 + len(p) <= chunk_size:
            cur = cur + "\n" + p if "\n" not in p[:1] else cur + p
        else:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap > 0 else ""
            cur = (tail + "\n" + p) if tail else p
            if len(cur) > chunk_size:
                # Overlap+piece exceeds — emit piece alone next round.
                chunks[-1] = cur[: -len(p) - 1] if len(p) + 1 < len(cur) else chunks[-1]
                cur = p
    if cur.strip():
        chunks.append(cur)
    return [c.strip() for c in chunks if c.strip()]
