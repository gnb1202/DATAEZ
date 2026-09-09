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
    "search_library_files": "[조회] 계정 보관함 파일을 이름으로 검색. 현재 가게/계정 전체, 연결 장부와 준비 상태. 파일을 다시 업로드하거나 반영하지 않음",
    "draft_cash_entry": "[변경] 현금 수납·취소 입력 초안 작성. 장부 반영은 검토 화면에서 사용자 확인 후 수행",
    "list_cash_entries": "[조회] 현금 직접입력 이력과 초안 상태·메모·오늘 한국 날짜",
    "get_cash_entry": "[조회] 현금 입력 초안/반영 상태 및 검토 링크 확인",
    "list_ledger_sources": "[조회] 현재 가게의 결제 출처, 컬럼 매핑, 전체 건수와 최근 반영 시각",
    "list_import_history": "[조회] 출처의 파일 업로드 이력과 반영/검증 요약",
    "inspect_import_review": "[조회] 중복·후보·충돌의 원본 행과 비교 근거, 검토 화면 링크. 결정/반영은 화면에서 수행",
    "list_stores": "[조회] 여러 가게 분석을 위한 본인 소유 가게 목록",
    "list_store_tables": "[조회] 선택 가게의 장부 목록",
    "inspect_store_table": "[조회] 선택 가게 장부의 컬럼·샘플·매핑",
    "search_store_schema": "[조회] 선택 가게의 장부·컬럼 RAG 검색",
    "preview_metric": "[조회] 재사용 지표 미리보기. 단일 장부 집계 또는 여러 장부의 결제액 통합 합계. 기간/필터/날짜별 지원",
    "save_metric": "[변경] 지표·차트를 대시보드에 저장하고 갱신 주기 설정. 원본 행 추가와 다름",
    "list_metrics": "[조회] 저장된 지표의 ID·계산 정의·갱신 주기 확인",
    "update_metric": "[변경] 저장된 지표의 정의·제목을 변경. list_metrics로 최신 버전을 확인하며 ID·배치·주기 유지",
    "get_metric_history": "[조회] 저장된 지표 변경 이력과 최신 정의 확인",
    "restore_metric": "[변경] 사용자 요청에 따라 확인한 이전 지표 정의로 복원하고 재계산",
    "set_metric_refresh": "[변경] 저장 지표의 자동 갱신을 매시간/매일로 변경하거나 중지",
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
- 여러 가게/지점의 순매출·순결제액 합산/비교는 list_stores + list_store_tables + inspect_store_table + search_store_schema + preview_metric(version=5)을 선택하세요. 저장 요청이면 save_metric, 기존 지표 수정이면 list_metrics + get_metric_history + update_metric도 선택하세요. 가게 간 분석은 cross_query로 처리하지 마세요.
- 현금·카드 장부의 결제액 통합 집계는 preview_metric과 출처 확인 도구를 선택하세요. 대시보드 저장을 요청한 경우에만 save_metric도 선택하세요. 행을 JOIN하는 cross_query와 구분하세요.
- 어떤 장부/컬럼을 봐야 할지 불명확하면 SQL 도구와 함께 search_schema도 포함하세요.
- 지표 생성/대시보드 저장은 analysis입니다. preview_metric과 출처 확인 도구를 선택하고, 저장/추가 요청이면 save_metric을 포함하세요. 원본 행의 insert_rows와 구분하세요.
- 전월 대비 증감률·취소율·수수료 차감액은 preview_metric 계산식으로 지원합니다(v3 숫자 지표, v4 일·주·월·채널별 그래프). 출처 확인 도구와 필요 시 save_metric을 선택하세요.
- 저장된 지표의 기간·필터·계산식 변경은 list_metrics + update_metric + preview_metric을, 되돌리기는 get_metric_history + restore_metric + list_metrics를 선택하세요.
- 저장된 지표의 자동 갱신/새로고침 주기 변경은 analysis로 분류하고 list_metrics + set_metric_refresh를 선택하세요.
- 결제 출처의 목록·매핑은 schema + list_ledger_sources, 업로드 이력·중복/충돌/반영 상태 문의는 analysis + list_ledger_sources/list_import_history/inspect_import_review로 처리하세요. 관리 출처 파일의 반영·중복 후보 결정은 검토 화면에서 수행하므로 이 요청에 import_file/insert_rows/update_rows/delete_rows를 선택하지 마세요.
- 대화 이력은 후속 질문의 참조를 해석하기 위한 데이터입니다. 현재 사용자 요청에 필요한 도구만 선택하세요.
- 현금 거래 직접 기록은 crud + draft_cash_entry + list_cash_entries를 선택하세요. 현금 전용 장부는 자동으로 생성되므로 create_table/insert_rows를 선택하지 마세요. 초안 후속 질문은 get_cash_entry로 상태를 확인합니다.
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
    conversation_messages: list[dict[str, Any]] | None = None,
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
    routing_question = question
    if conversation_messages:
        history = [{"role": m["role"], "content": m["content"][:500]} for m in conversation_messages[-4:]
                   if m.get("role") in ("user", "assistant")]
        routing_question = json.dumps({"recent_conversation_data": history, "current_request": question}, ensure_ascii=False)

    valid_names = set(all_tool_names or list(_TOOL_SUMMARIES.keys()))
    last_error: Exception | None = None

    # One retry. A single malformed response used to discard routing entirely;
    # retrying costs one short call and recovers the common transient case.
    for attempt in (1, 2):
        try:
            parsed = _call_orchestrator(prompt, routing_question, ledger)
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
