"""Korean tokenization for full-text search.

Postgres has no Korean text-search configuration. Indexing Korean with the
`simple` config splits on whitespace only, and Korean is agglutinative: 매출이,
매출을, and 매출은 become three unrelated tokens, none of which matches a query
for 매출. The sparse half of the hybrid search therefore only ever fired on an
exact surface-form match, which for a Korean-language product is most of the
time never.

Morphemes are extracted in the application and written into an ordinary
tsvector column, so the same analysis applies on both write and query. This
keeps the standard pgvector image — no pgroonga or pg_bigm extension — and
works on managed Postgres where installing extensions is not an option.
"""

from __future__ import annotations

import logging
import re
import threading

logger = logging.getLogger(__name__)

# Postfixes, endings, and other function morphemes. They carry no search
# signal and would otherwise dominate the index: every Korean sentence has
# several, so they behave like unindexed stopwords.
_FUNCTION_TAGS = frozenset(
    {
        "JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC",  # 조사
        "EP", "EF", "EC", "ETN", "ETM",                               # 어미
        "XSN", "XSV", "XSA",                                          # 접미사
        "SF", "SP", "SS", "SE", "SO", "SW",                           # 문장부호
    }
)

_MIN_TOKEN_LEN = 1
_ASCII_WORD = re.compile(r"[A-Za-z0-9_]+")

_kiwi = None
_kiwi_lock = threading.Lock()


def _get_kiwi():
    """Build the analyzer once. Loading its model is expensive."""
    global _kiwi
    if _kiwi is None:
        with _kiwi_lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi

                _kiwi = Kiwi()
                logger.info("Korean morphological analyzer initialised")
    return _kiwi


def tokenize_korean(text: str) -> list[str]:
    """Return searchable morphemes plus ASCII words, lowercased.

    ASCII runs are kept whole: an analyzer trained on Korean has no useful
    decomposition for identifiers like `order_id` or `CSV`, and splitting them
    would lose exact matches that already work.
    """
    if not text or not text.strip():
        return []

    tokens: list[str] = []
    try:
        for token in _get_kiwi().tokenize(text):
            if token.tag in _FUNCTION_TAGS:
                continue
            form = token.form.strip().lower()
            if len(form) >= _MIN_TOKEN_LEN and not _is_punctuation(form):
                tokens.append(form)
    except Exception:
        # Indexing must not fail because analysis did. Falling back to plain
        # word splitting reproduces the old behaviour for this one document
        # rather than dropping it from the index entirely.
        logger.warning("Korean tokenization failed; indexing raw words", exc_info=True)
        return [w.lower() for w in text.split() if w.strip()]

    tokens.extend(m.group().lower() for m in _ASCII_WORD.finditer(text))
    return _dedupe_preserving_order(tokens)


def _is_punctuation(token: str) -> bool:
    return all(not ch.isalnum() for ch in token)


def _dedupe_preserving_order(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def to_tsvector_input(text: str) -> str:
    """Analysed text to store in a tsvector column via to_tsvector('simple', …).

    The `simple` config is retained deliberately: it does no stemming, which is
    correct once the input is already morphemes.
    """
    return " ".join(tokenize_korean(text))


def to_tsquery_input(text: str) -> str:
    """Analysed query text for plainto_tsquery('simple', …).

    Uses the same analysis as the write path — a query analysed differently
    from the index cannot match it.
    """
    return " ".join(tokenize_korean(text))
