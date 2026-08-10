"""Shared OpenAI client singletons — avoids creating a new client per call."""

from openai import AsyncOpenAI, OpenAI

from .config import settings

_sync_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def get_openai_client() -> OpenAI:
    """Return a reusable sync OpenAI client with retry on 429/5xx."""
    global _sync_client
    if _sync_client is None:
        _sync_client = OpenAI(
            api_key=settings.openai_api_key,
            max_retries=3,
            timeout=60.0,
        )
    return _sync_client


def get_async_openai_client() -> AsyncOpenAI:
    """Return a reusable async OpenAI client with retry on 429/5xx."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=3,
            timeout=60.0,
        )
    return _async_client
