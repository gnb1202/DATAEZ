"""Token counting.

The RAG pipeline stored `len(text)` in a column named `token_count`, and the
conversation-context budget measured characters while calling them tokens. For
Korean both are wrong in the same direction: a Korean character is typically
more than one token under cl100k/o200k, so a character-based budget
underestimates real usage several-fold and a "token count" column reports a
number that is not a token count.
"""

from __future__ import annotations

import functools
import logging

logger = logging.getLogger(__name__)

DEFAULT_ENCODING = "o200k_base"


@functools.lru_cache(maxsize=4)
def _encoding(name: str):
    import tiktoken

    return tiktoken.get_encoding(name)


def count_tokens(text: str, encoding: str = DEFAULT_ENCODING) -> int:
    """Exact token count, falling back to a Korean-aware estimate.

    The fallback is only reached if tiktoken cannot load its encoding (for
    example with no network on first use and no cached vocabulary). It errs
    high rather than low, since underestimating a budget is what causes the
    overruns this module exists to prevent.
    """
    if not text:
        return 0
    try:
        return len(_encoding(encoding).encode(text))
    except Exception:
        logger.warning("tiktoken unavailable; estimating token count", exc_info=True)
        return estimate_tokens(text)


def estimate_tokens(text: str) -> int:
    """Heuristic count used only when tiktoken is unavailable.

    Korean characters are charged at 1.5 tokens each and everything else at
    roughly 4 characters per token.
    """
    korean = sum(1 for ch in text if "가" <= ch <= "힣")
    other = len(text) - korean
    return int(korean * 1.5 + other / 4) + 1


def truncate_to_tokens(text: str, max_tokens: int, encoding: str = DEFAULT_ENCODING) -> str:
    """Cut `text` to at most `max_tokens`, on a token boundary."""
    if max_tokens <= 0 or not text:
        return ""
    try:
        enc = _encoding(encoding)
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    except Exception:
        logger.warning("tiktoken unavailable; truncating by characters", exc_info=True)
        return text[: max_tokens * 2]
