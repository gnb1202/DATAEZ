"""LLM utility functions for summarization and other lightweight calls.

[Changelog]
- v2: system/user role separation, Korean-only prompts,
      structured output, max_tokens/temperature control.
"""

import json
import logging

from .config import settings
from .llm_telemetry import ROLE_EMBEDDING, track_llm_call
from .openai_clients import get_openai_client

logger = logging.getLogger(__name__)


def summarize_result(question: str, table_data: list[dict], reasoning_meta: dict) -> str:
    """Summarize query results for the user in Korean."""
    if not settings.openai_api_key:
        return _fallback_summary(question, table_data)

    try:
        client = get_openai_client()
        preview = table_data[:5]

        system_msg = (
            "당신은 소상공인을 위한 데이터 분석 어시스턴트입니다.\n"
            "주어진 데이터 결과를 바탕으로 핵심 인사이트를 한국어로 요약하세요.\n\n"
            "규칙:\n"
            "- 2~4문장으로 간결하게 작성\n"
            "- 구체적인 수치를 반드시 포함\n"
            "- 데이터에 근거한 사실만 제시 (추측 금지)\n"
            "- 비즈니스에 도움되는 인사이트가 있다면 한 줄 추가"
        )

        user_msg = (
            f"질문: {question}\n\n"
            f"결과 데이터 (상위 {len(preview)}건):\n"
            f"{json.dumps(preview, ensure_ascii=False, indent=2)}\n\n"
            f"총 행 수: {reasoning_meta.get('total_count', len(table_data))}\n"
            f"사용된 집계: {reasoning_meta.get('operation', 'none')}"
        )

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        return response.choices[0].message.content or _fallback_summary(question, table_data)
    except Exception:
        logger.warning("LLM summarization failed, using fallback", exc_info=True)
        return _fallback_summary(question, table_data)


def _fallback_summary(question: str, table_data: list[dict]) -> str:
    if not table_data:
        return "질의 결과가 비어 있습니다. 필터 조건이나 컬럼 지정을 완화해서 다시 시도해 주세요."
    return f"요청하신 '{question}'에 대한 결과를 생성했습니다. 상위 {min(len(table_data), 5)}개 행을 먼저 확인해 주세요."


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via OpenAI. Returns float vectors aligned to input order.

    Raises on API failure — callers should decide whether to retry or skip.
    """
    if not texts:
        return []
    client = get_openai_client()
    with track_llm_call(
        model=settings.openai_embedding_model, role=ROLE_EMBEDDING
    ) as call:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
        )
        call.record_usage(response.usage)
    return [item.embedding for item in response.data]


def embed_one(text: str) -> list[float]:
    """Convenience wrapper for single-text embedding."""
    vectors = generate_embeddings([text])
    return vectors[0]
