"""Orchestrator: gpt-5.4 기반 동적 툴 선택.

기존 키워드 휴리스틱 + intent 분류를 대체.
Orchestrator LLM이 질문을 보고 필요한 툴을 직접 선택한다.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .config import settings
from .llm_telemetry import ROLE_ORCHESTRATOR, TurnLedger, track_llm_call
from .metrics import orchestrator_decisions_total
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

# Characters that may remain once greeting words are stripped before the
# message stops counting as "only a greeting". Sized from the polite endings
# Korean greetings carry — 안녕**하세요**, 고마워**요 잘 쓸게요** — and below the
# length of the shortest real request.
_GREETING_RESIDUE_MAX = 5

_NON_WORD = re.compile(r"[^0-9a-z가-힣]+")


def _is_pure_greeting(question: str) -> bool:
    """True when the message is nothing but a greeting.

    The earlier rule was "contains a greeting word and no data keyword", which
    made `_DATA_KW` a whitelist that has to enumerate every way a user might
    phrase a request. It cannot be complete, and each gap silently discards a
    real request without ever consulting the model: "수고하셨습니다. 어제 것 좀
    정리해주세요" matched 수고, missed on 정리, and was answered as a greeting.

    Asking what is *left* after removing the greeting is a bounded question.
    The data keywords are kept as a fast reject — their presence settles the
    matter — but they are no longer what the decision rests on.
    """
    q = question.lower().strip()
    if not q or not any(kw in q for kw in _GREETING_KW):
        return False
    if any(kw in q for kw in _DATA_KW):
        return False

    residue = q
    for kw in _GREETING_KW:
        residue = residue.replace(kw, " ")
    residue = _NON_WORD.sub("", residue)
    return len(residue) <= _GREETING_RESIDUE_MAX


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
    "cross_query": "[조회] 2~3개 장부를 JOIN하여 교차 분석. 서로 다른 두 대상을 대조·비교·차이를 묻는 질문(예: 'A 건수와 B 건수 차이')이면 query_data가 아니라 이 도구",
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
  판단 축은 **"장부의 구조에 관한 것인가, 장부 안의 행에 관한 것인가"**입니다.
  읽기냐 쓰기냐로 나누지 마세요 — 구조를 조회하는 것도 schema입니다.
  - schema: 장부의 **구조**. 조회와 변경을 모두 포함합니다.
    · 어떤 장부가 있는지, 장부가 몇 개인지 (list_tables)
    · 어떤 컬럼이 있는지, 컬럼 타입이 무엇인지 (describe_table)
    · 어떤 장부를 봐야 하는지 찾기 (search_schema)
    · 장부 생성, 컬럼 추가/삭제/이름변경/타입변경 (create_table, alter_table)
  - crud: 장부 **안의 행**을 추가/수정/삭제하거나 그대로 조회
    (insert_rows, update_rows, delete_rows, query_data)
  - analysis: 행을 집계·비교·시각화 (query_data+generate_chart, cross_query)
  - general: 위 어디에도 해당하지 않는 요청 (인사, 능력 질문, 문서 검색 등)
- 질문이 서로 다른 두 대상을 대조·비교하거나 그 차이를 물으면 cross_query를 선택하세요.
  ("예약 건수와 결제 건수 차이", "장부A와 장부B 비교" 등 — query_data 단독으로는 답할 수 없음)
- 어떤 장부/컬럼을 봐야 할지 불명확하면 SQL 도구와 함께 search_schema도 포함하세요.
- 정의·규칙·정책 등 데이터로 답할 수 없는 질문이면 search_documents를 포함하세요.
- 인사/일반 대화처럼 툴이 필요 없으면: {{"intent": "general", "tools": []}}
- 반드시 위 목록에 있는 툴 이름만 사용하세요"""


# Schema enforced by the API rather than requested in prose. The orchestrator's
# entire value depends on returning parseable JSON, so the one place where JSON
# reliability matters should not be left to instruction-following.
ORCHESTRATOR_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "tool_routing",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["schema", "crud", "analysis", "general"],
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["intent", "tools"],
            "additionalProperties": False,
        },
    },
}

# Degraded routing exposes only read-only tools. The previous behaviour handed
# back all 14 — including delete_rows and alter_table — and the caller then
# forced a tool call on the first iteration, so a parse failure could push a
# greeting straight into a destructive tool.
SAFE_FALLBACK_TOOLS = [
    "list_tables",
    "describe_table",
    "query_data",
    "search_schema",
    "search_documents",
]


@dataclass
class OrchestratorResult:
    """Orchestrator의 반환 결과: 선택된 툴 + 분류된 intent."""
    tools: list[str] | None  # None이면 안전 폴백 집합 사용
    intent: str  # "schema", "crud", "analysis", "general"
    degraded: bool = False  # True면 라우팅 실패로 폴백된 결과


def select_tools_via_orchestrator(
    question: str,
    has_attachments: bool = False,
    all_tool_names: list[str] | None = None,
    ledger: TurnLedger | None = None,
) -> OrchestratorResult:
    """Orchestrator LLM을 이용해 intent와 필요한 툴 이름 목록을 반환."""
    # Pre-filter: 순수 인사 → LLM 호출 없이 빈 배열 반환
    if _is_pure_greeting(question):
        logger.info("Orchestrator pre-filter: pure greeting detected, no tools")
        orchestrator_decisions_total.labels(outcome="greeting_shortcut").inc()
        return OrchestratorResult(tools=[], intent="general")

    # 파일 첨부 → import_file 포함 필수
    if has_attachments:
        logger.info("Orchestrator pre-filter: attachment detected, forcing import_file")
        orchestrator_decisions_total.labels(outcome="attachment_shortcut").inc()
        return OrchestratorResult(tools=["list_tables", "describe_table", "import_file"], intent="crud")

    if not settings.openai_api_key:
        logger.warning("Orchestrator: no API key, returning fallback")
        orchestrator_decisions_total.labels(outcome="fallback_no_key").inc()
        return OrchestratorResult(
            tools=list(SAFE_FALLBACK_TOOLS), intent="general", degraded=True
        )

    tool_list = "\n".join(
        f"- {name}: {desc}" for name, desc in _TOOL_SUMMARIES.items()
    )
    prompt = ORCHESTRATOR_PROMPT.format(tool_list=tool_list)

    valid_names = set(all_tool_names or list(_TOOL_SUMMARIES.keys()))
    last_error: Exception | None = None

    # One retry. A single malformed response used to discard routing entirely;
    # retrying costs one short call and recovers the common transient case.
    for attempt in (1, 2):
        try:
            parsed = _call_orchestrator(prompt, question, ledger)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning(
                "Orchestrator JSON parse failed (attempt %d/2): %s", attempt, exc
            )
            continue
        except Exception as exc:
            last_error = exc
            logger.warning("Orchestrator call failed (attempt %d/2): %s", attempt, exc)
            continue

        intent = parsed.get("intent", "general")
        if intent not in ("schema", "crud", "analysis", "general"):
            intent = "general"

        # Hallucinated tool names are dropped rather than trusted.
        filtered = [name for name in parsed.get("tools", []) if name in valid_names]
        logger.info("Orchestrator selected tools: %s, intent: %s", filtered, intent)
        orchestrator_decisions_total.labels(
            outcome="llm_selected" if attempt == 1 else "llm_selected_retry"
        ).inc()
        return OrchestratorResult(tools=filtered, intent=intent)

    outcome = (
        "fallback_parse_error"
        if isinstance(last_error, json.JSONDecodeError)
        else "fallback_api_error"
    )
    logger.warning("Orchestrator degraded to the read-only fallback set: %s", last_error)
    orchestrator_decisions_total.labels(outcome=outcome).inc()
    return OrchestratorResult(
        tools=[t for t in SAFE_FALLBACK_TOOLS if t in valid_names],
        intent="general",
        degraded=True,
    )


def _call_orchestrator(
    prompt: str, question: str, ledger: TurnLedger | None
) -> dict[str, Any]:
    """One orchestrator call. Raises on transport or parse failure."""
    client = get_openai_client()
    with track_llm_call(
        model=settings.openai_orchestrator_model,
        role=ROLE_ORCHESTRATOR,
        ledger=ledger,
    ) as call:
        response = client.chat.completions.create(
            model=settings.openai_orchestrator_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            max_completion_tokens=150,
            temperature=0,
            response_format=ORCHESTRATOR_SCHEMA,
        )
        call.record_usage(response.usage)

    raw = (response.choices[0].message.content or "").strip()
    logger.info("Orchestrator raw response: %s", raw)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed
