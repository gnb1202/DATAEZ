"""Orchestrator: gpt-5.4 기반 동적 툴 선택.

기존 키워드 휴리스틱 + intent 분류를 대체.
Orchestrator LLM이 질문을 보고 필요한 툴을 직접 선택한다.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from .config import settings
from .openai_clients import get_openai_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 인사 키워드 pre-filter (LLM 비용 절약용)
# ---------------------------------------------------------------------------

_GREETING_KW = [
    "안녕", "하이", "헬로", "hello", "hi",
    "감사", "고마워", "수고",
    "도움말", "사용법", "뭐야", "뭘 할 수 있",
    "어떻게 사용", "사용 방법",
]

_DATA_KW = [
    "추가", "수정", "삭제", "변경", "조회", "분석", "차트", "그래프",
    "보여", "알려", "통계", "장부", "테이블", "컬럼", "데이터", "파일",
]


def _is_pure_greeting(question: str) -> bool:
    """데이터 관련 키워드 없이 인사만 포함된 경우 True."""
    q = question.lower().strip()
    has_greeting = any(kw in q for kw in _GREETING_KW)
    has_data = any(kw in q for kw in _DATA_KW)
    return has_greeting and not has_data


# ---------------------------------------------------------------------------
# 툴 요약 목록 (Orchestrator 프롬프트용 — 토큰 절약)
# ---------------------------------------------------------------------------

_TOOL_SUMMARIES: dict[str, str] = {
    "list_tables": "[조회] 프로젝트 내 모든 장부 목록 반환",
    "describe_table": "[조회] 특정 장부의 구조/샘플 데이터 조회",
    "query_data": "[조회] 데이터 조회/집계/필터링 (SELECT)",
    "insert_rows": "[변경] 장부에 새 행 추가",
    "update_rows": "[변경] 장부의 기존 행 수정",
    "delete_rows": "[변경] 장부에서 행 삭제",
    "generate_chart": "[조회] 쿼리 결과를 차트로 시각화",
    "recommend_charts": "[조회] 데이터에 적합한 차트 유형 추천",
    "create_table": "[변경] 새 장부(테이블) 생성",
    "alter_table": "[변경] 장부 구조 변경 (컬럼 추가/삭제/변경)",
    "cross_query": "[조회] 여러 장부를 JOIN하여 교차 분석",
    "import_file": "[변경] CSV/XLSX 파일을 장부로 가져오기",
    "search_schema": "[조회] 자연어로 관련 장부/컬럼 의미 검색 (Hybrid RAG, SQL 도구 호출 전 사용)",
    "search_documents": "[조회] 업로드된 매뉴얼/정책 문서에서 답 검색 (Hybrid RAG)",
}

ORCHESTRATOR_PROMPT = """사용자의 데이터 분석 요청을 분석하여 intent와 필요한 툴을 선택하세요.

사용 가능한 툴:
{tool_list}

규칙:
- 아래 JSON 형식으로만 반환하세요. 설명 없이 JSON만:
{{"intent": "<intent>", "tools": ["tool_a", "tool_b"]}}
- intent는 다음 중 하나: "schema", "crud", "analysis", "general"
  - schema: 장부 생성, 구조 변경 (create_table, alter_table)
  - crud: 데이터 추가/수정/삭제/조회 (insert_rows, update_rows, delete_rows, query_data)
  - analysis: 분석, 시각화, 비교 (query_data+generate_chart, cross_query)
  - general: 위에 해당하지 않는 요청
- 어떤 장부/컬럼을 봐야 할지 불명확하면 SQL 도구와 함께 search_schema도 포함하세요.
- 정의·규칙·정책 등 데이터로 답할 수 없는 질문이면 search_documents를 포함하세요.
- 인사/일반 대화처럼 툴이 필요 없으면: {{"intent": "general", "tools": []}}
- 반드시 위 목록에 있는 툴 이름만 사용하세요"""


@dataclass
class OrchestratorResult:
    """Orchestrator의 반환 결과: 선택된 툴 + 분류된 intent."""
    tools: list[str] | None  # None이면 전체 툴 fallback
    intent: str  # "schema", "crud", "analysis", "general"


def select_tools_via_orchestrator(
    question: str,
    has_attachments: bool = False,
    all_tool_names: list[str] | None = None,
) -> OrchestratorResult:
    """Orchestrator LLM을 이용해 intent와 필요한 툴 이름 목록을 반환."""
    # Pre-filter: 순수 인사 → LLM 호출 없이 빈 배열 반환
    if _is_pure_greeting(question):
        logger.info("Orchestrator pre-filter: pure greeting detected, no tools")
        return OrchestratorResult(tools=[], intent="general")

    # 파일 첨부 → import_file 포함 필수
    if has_attachments:
        logger.info("Orchestrator pre-filter: attachment detected, forcing import_file")
        return OrchestratorResult(tools=["list_tables", "describe_table", "import_file"], intent="crud")

    if not settings.openai_api_key:
        logger.warning("Orchestrator: no API key, returning fallback")
        return OrchestratorResult(tools=None, intent="general")

    tool_list = "\n".join(
        f"- {name}: {desc}" for name, desc in _TOOL_SUMMARIES.items()
    )
    prompt = ORCHESTRATOR_PROMPT.format(tool_list=tool_list)

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=settings.openai_orchestrator_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            max_completion_tokens=150,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        logger.info("Orchestrator raw response: %s", raw)

        parsed: Any = json.loads(raw)

        # 새 형식: {"intent": "...", "tools": [...]}
        if isinstance(parsed, dict):
            intent = parsed.get("intent", "general")
            selected = parsed.get("tools", [])
        # 하위 호환: 기존 배열 형식 ["tool_a", "tool_b"]
        elif isinstance(parsed, list):
            selected = parsed
            intent = "general"
        else:
            raise ValueError(f"Unexpected response type: {type(parsed)}")

        # Validate intent
        if intent not in ("schema", "crud", "analysis", "general"):
            intent = "general"

        # Validate: 존재하는 툴 이름만 허용
        valid_names = set(all_tool_names or list(_TOOL_SUMMARIES.keys()))
        filtered = [name for name in selected if name in valid_names]
        logger.info("Orchestrator selected tools: %s, intent: %s", filtered, intent)
        return OrchestratorResult(tools=filtered, intent=intent)

    except json.JSONDecodeError as exc:
        logger.warning("Orchestrator JSON parse failed: %s — fallback to all tools", exc)
        return OrchestratorResult(tools=None, intent="general")
    except Exception as exc:
        logger.warning("Orchestrator call failed: %s — fallback to all tools", exc)
        return OrchestratorResult(tools=None, intent="general")
