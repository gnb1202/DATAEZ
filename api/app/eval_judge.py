"""LLM as a Judge — Prompt evaluation module for DATAEZ.

Evaluates agent response quality using LLM-based automated assessment.
Inspired by Kakao CodeBuddy's LLM as a Judge methodology.

Supports three evaluation modes:
1. Pointwise: Individual response scoring (1-5 scale)
2. Pairwise: A/B comparison of two responses (with position bias mitigation)
3. Batch: Run pointwise evaluation across a test suite

Reference: https://tech.kakao.com/posts/690

Usage:
    from app.eval_judge import pointwise_evaluate, pairwise_evaluate, run_eval_suite

    # Single response evaluation
    result = pointwise_evaluate(
        user_question="매출 추이 보여줘",
        agent_answer="...",
        tool_calls=[...],
        tables_context="...",
    )

    # A/B comparison (e.g., prompt v1 vs v2)
    result = pairwise_evaluate(
        user_question="매출 추이 보여줘",
        response_a="...",
        response_b="...",
        tool_calls_a=[...],
        tool_calls_b=[...],
    )

    # Full test suite
    results = run_eval_suite(test_cases, eval_model="gpt-4o")
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PointwiseResult:
    """Result of a pointwise (individual) evaluation."""
    overall_score: float  # 1-5
    criteria_scores: dict[str, float] = field(default_factory=dict)
    explanation: str = ""
    raw_response: str = ""


@dataclass
class PairwiseResult:
    """Result of a pairwise (A/B comparison) evaluation."""
    winner: str  # "A", "B", or "tie"
    score_a: float  # 1-5
    score_b: float  # 1-5
    explanation: str = ""
    position_bias_check: bool = False  # True if position swap was performed
    raw_response: str = ""


@dataclass
class EvalTestCase:
    """A single test case for batch evaluation."""
    id: str
    user_question: str
    expected_intent: str = ""  # schema, crud, analysis, greeting, general
    expected_tools: list[str] = field(default_factory=list)
    tables_context: str = ""
    # For pairwise: two responses to compare
    response_a: str = ""
    response_b: str = ""
    tool_calls_a: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_b: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvalSuiteResult:
    """Aggregated results from a batch evaluation run."""
    total: int = 0
    avg_score: float = 0.0
    criteria_averages: dict[str, float] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Evaluation criteria — specific to DATAEZ agent behavior
# ---------------------------------------------------------------------------

EVAL_CRITERIA = {
    "tool_selection": "올바른 도구를 선택했는가? (사용자 의도에 맞는 도구 호출)",
    "execution_accuracy": "도구 파라미터가 정확한가? (테이블명, 컬럼명, 조건 등)",
    "response_quality": "응답이 명확하고 구체적인가? (수치 포함, 비즈니스 인사이트)",
    "rule_compliance": "실행 규칙을 준수했는가? (확인 없이 즉시 실행, 보고 형식)",
    "user_experience": "소상공인 비전문가가 이해할 수 있는 답변인가?",
}


# ---------------------------------------------------------------------------
# Pointwise evaluation prompt
# ---------------------------------------------------------------------------

POINTWISE_SYSTEM_PROMPT = """당신은 DATAEZ AI 에이전트의 응답 품질을 평가하는 전문 평가자입니다.

DATAEZ는 소상공인을 위한 AI 데이터 관리 플랫폼입니다. 에이전트는 자연어 요청을 받아
장부(테이블) 관리, 데이터 CRUD, 분석, 시각화를 수행합니다.

## 평가 기준 (각 1~5점)

1. **tool_selection** (도구 선택 정확성)
   - 5점: 사용자 의도에 완벽히 맞는 도구 선택
   - 3점: 대체로 맞지만 불필요한 도구 호출이 있음
   - 1점: 완전히 잘못된 도구 선택 (예: "추가해줘"에 query_data 호출)

2. **execution_accuracy** (실행 정확성)
   - 5점: 파라미터가 모두 정확 (테이블명, 컬럼명, WHERE 조건 등)
   - 3점: 일부 파라미터 오류가 있지만 결과에 큰 영향 없음
   - 1점: 파라미터 오류로 실행 실패 또는 잘못된 결과

3. **response_quality** (응답 품질)
   - 5점: 구체적 수치 포함, 핵심 결과 + 비즈니스 인사이트
   - 3점: 결과는 전달하지만 인사이트 부족
   - 1점: 모호하거나 수치 없는 답변

4. **rule_compliance** (규칙 준수)
   - 5점: 확인 없이 즉시 실행, 올바른 보고 형식
   - 3점: 대체로 준수하지만 불필요한 확인 질문 포함
   - 1점: "진행할까요?" 등 확인 요청, 도구 미호출

5. **user_experience** (사용자 경험)
   - 5점: 비전문가도 바로 이해 가능, 자연스러운 한국어
   - 3점: 이해 가능하지만 전문 용어 남용
   - 1점: 기술 용어 과다, 이해 어려움

## 중요: 편향 방지
- 답변의 길이가 품질과 비례하지 않습니다. 간결하면서 핵심을 전달하는 답변이 더 좋을 수 있습니다.
- 실제 도구 호출 여부와 정확성을 가장 중요하게 평가하세요.

## 출력 형식 (반드시 JSON)
```json
{
  "tool_selection": <1-5>,
  "execution_accuracy": <1-5>,
  "response_quality": <1-5>,
  "rule_compliance": <1-5>,
  "user_experience": <1-5>,
  "overall_score": <1-5 (가중 평균)>,
  "explanation": "<한국어로 평가 근거 2~3문장>"
}
```"""


POINTWISE_USER_TEMPLATE = """## 평가 대상

### 사용자 질문
{user_question}

### 프로젝트 컨텍스트 (장부 목록)
{tables_context}

### 에이전트의 도구 호출
{tool_calls}

### 에이전트의 최종 응답
{agent_answer}

위 응답을 평가 기준에 따라 점수를 매기고 JSON으로 출력하세요."""


# ---------------------------------------------------------------------------
# Pairwise evaluation prompt
# ---------------------------------------------------------------------------

PAIRWISE_SYSTEM_PROMPT = """당신은 DATAEZ AI 에이전트의 두 응답을 비교 평가하는 전문 평가자입니다.

DATAEZ는 소상공인을 위한 AI 데이터 관리 플랫폼입니다. 에이전트는 자연어 요청을 받아
장부 관리, 데이터 CRUD, 분석, 시각화를 수행합니다.

## 평가 기준
1. **도구 선택 정확성**: 사용자 의도에 맞는 올바른 도구를 선택했는가?
2. **실행 정확성**: 파라미터가 정확하고 실행 결과가 올바른가?
3. **응답 품질**: 구체적 수치, 비즈니스 인사이트가 포함되었는가?
4. **규칙 준수**: 확인 없이 즉시 실행, 올바른 보고 형식을 따랐는가?
5. **사용자 경험**: 비전문가가 이해할 수 있는 명확한 한국어 답변인가?

## 중요: 편향 방지 지침
- **길이 편향 주의**: 답변이 길다고 반드시 좋은 것은 아닙니다. 간결하면서 핵심을 전달하면 더 좋습니다.
- **위치 편향 주의**: Response A가 먼저 제시되었다고 유리하게 평가하지 마세요. 내용만으로 판단하세요.
- **익명 처리**: 어떤 모델/프롬프트 버전인지 알 수 없습니다. 순수하게 품질만 평가하세요.

위 평가 기준에 따라 두 응답을 비교하세요. 평가 기준을 다시 한번 상기하세요.

## 출력 형식 (반드시 JSON)
```json
{
  "winner": "<A 또는 B 또는 tie>",
  "score_a": <1-5>,
  "score_b": <1-5>,
  "explanation": "<한국어로 비교 평가 근거 2~4문장>"
}
```"""


PAIRWISE_USER_TEMPLATE = """## 평가 대상

### 사용자 질문
{user_question}

### 프로젝트 컨텍스트 (장부 목록)
{tables_context}

---

### Response {label_a}

**도구 호출:**
{tool_calls_a}

**최종 응답:**
{response_a}

---

### Response {label_b}

**도구 호출:**
{tool_calls_b}

**최종 응답:**
{response_b}

---

위 두 응답을 평가 기준에 따라 비교하고 JSON으로 출력하세요."""


# ---------------------------------------------------------------------------
# Core evaluation functions
# ---------------------------------------------------------------------------

def _get_eval_client(eval_model: str | None = None) -> tuple[OpenAI, str]:
    """Get OpenAI client and model for evaluation.

    Uses a different model than the agent to avoid self-enhancement bias.
    """
    from .openai_clients import get_openai_client

    model = eval_model or "gpt-4o"  # Default: stronger model for evaluation
    client = get_openai_client()
    return client, model


def _parse_json_response(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    import re
    # Try to find JSON in code blocks first
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    # Strip any remaining whitespace
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON from eval response: %s", text[:200])
        return {}


def pointwise_evaluate(
    user_question: str,
    agent_answer: str,
    tool_calls: list[dict[str, Any]] | None = None,
    tables_context: str = "",
    eval_model: str | None = None,
) -> PointwiseResult:
    """Evaluate a single agent response using pointwise scoring (1-5 scale).

    Args:
        user_question: The user's original question
        agent_answer: The agent's final text response
        tool_calls: List of tool calls made by the agent [{name, input, output}, ...]
        tables_context: Description of available tables
        eval_model: Model to use for evaluation (default: gpt-4o)

    Returns:
        PointwiseResult with scores and explanation
    """
    if not settings.openai_api_key:
        return PointwiseResult(overall_score=0, explanation="API key not configured")

    client, model = _get_eval_client(eval_model)

    # Format tool calls for the prompt
    tool_calls_str = "없음"
    if tool_calls:
        formatted = []
        for tc in tool_calls:
            name = tc.get("tool_name", tc.get("name", "unknown"))
            inp = tc.get("tool_input", tc.get("input", {}))
            out = tc.get("tool_output", tc.get("output", {}))
            # Truncate large outputs
            out_str = json.dumps(out, ensure_ascii=False, default=str)
            if len(out_str) > 500:
                out_str = out_str[:500] + "..."
            formatted.append(f"- {name}({json.dumps(inp, ensure_ascii=False)}) → {out_str}")
        tool_calls_str = "\n".join(formatted)

    user_msg = POINTWISE_USER_TEMPLATE.format(
        user_question=user_question,
        tables_context=tables_context or "(컨텍스트 없음)",
        tool_calls=tool_calls_str,
        agent_answer=agent_answer,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": POINTWISE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_json_response(raw)

        if not parsed:
            return PointwiseResult(overall_score=0, explanation="평가 파싱 실패", raw_response=raw)

        criteria_scores = {
            k: float(parsed.get(k, 0))
            for k in EVAL_CRITERIA
            if k in parsed
        }
        overall = float(parsed.get("overall_score", 0))
        if not overall and criteria_scores:
            overall = sum(criteria_scores.values()) / len(criteria_scores)

        return PointwiseResult(
            overall_score=round(overall, 1),
            criteria_scores=criteria_scores,
            explanation=parsed.get("explanation", ""),
            raw_response=raw,
        )
    except Exception as exc:
        logger.error("Pointwise evaluation failed: %s", exc)
        return PointwiseResult(overall_score=0, explanation=f"평가 오류: {str(exc)}")


def pairwise_evaluate(
    user_question: str,
    response_a: str,
    response_b: str,
    tool_calls_a: list[dict[str, Any]] | None = None,
    tool_calls_b: list[dict[str, Any]] | None = None,
    tables_context: str = "",
    eval_model: str | None = None,
    mitigate_position_bias: bool = True,
) -> PairwiseResult:
    """Compare two agent responses using pairwise evaluation.

    Implements position bias mitigation by running the comparison twice
    with swapped order and averaging the results.

    Args:
        user_question: The user's original question
        response_a: First agent response
        response_b: Second agent response
        tool_calls_a: Tool calls for response A
        tool_calls_b: Tool calls for response B
        tables_context: Description of available tables
        eval_model: Model to use for evaluation
        mitigate_position_bias: If True, runs eval twice with swapped positions

    Returns:
        PairwiseResult with winner, scores, and explanation
    """
    if not settings.openai_api_key:
        return PairwiseResult(winner="tie", score_a=0, score_b=0, explanation="API key not configured")

    def _format_tools(tool_calls: list[dict[str, Any]] | None) -> str:
        if not tool_calls:
            return "없음"
        formatted = []
        for tc in tool_calls:
            name = tc.get("tool_name", tc.get("name", "unknown"))
            inp = tc.get("tool_input", tc.get("input", {}))
            formatted.append(f"- {name}({json.dumps(inp, ensure_ascii=False)})")
        return "\n".join(formatted)

    def _run_comparison(
        resp_first: str, resp_second: str,
        tools_first: list[dict[str, Any]] | None,
        tools_second: list[dict[str, Any]] | None,
        label_first: str, label_second: str,
    ) -> dict[str, Any]:
        client, model = _get_eval_client(eval_model)

        user_msg = PAIRWISE_USER_TEMPLATE.format(
            user_question=user_question,
            tables_context=tables_context or "(컨텍스트 없음)",
            label_a=label_first,
            label_b=label_second,
            tool_calls_a=_format_tools(tools_first),
            response_a=resp_first,
            tool_calls_b=_format_tools(tools_second),
            response_b=resp_second,
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PAIRWISE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        return _parse_json_response(raw)

    try:
        # Run 1: A first, B second
        result1 = _run_comparison(
            response_a, response_b, tool_calls_a, tool_calls_b, "A", "B"
        )

        if not mitigate_position_bias:
            winner = result1.get("winner", "tie").upper()
            return PairwiseResult(
                winner=winner,
                score_a=float(result1.get("score_a", 0)),
                score_b=float(result1.get("score_b", 0)),
                explanation=result1.get("explanation", ""),
            )

        # Run 2: B first, A second (position swap for bias mitigation)
        result2 = _run_comparison(
            response_b, response_a, tool_calls_b, tool_calls_a, "A", "B"
        )

        # Aggregate: in run2, "A" label = original B, "B" label = original A
        score_a_r1 = float(result1.get("score_a", 0))
        score_b_r1 = float(result1.get("score_b", 0))
        score_a_r2 = float(result2.get("score_b", 0))  # swapped
        score_b_r2 = float(result2.get("score_a", 0))  # swapped

        avg_score_a = (score_a_r1 + score_a_r2) / 2
        avg_score_b = (score_b_r1 + score_b_r2) / 2

        # Determine winner from averaged scores
        if abs(avg_score_a - avg_score_b) < 0.3:
            winner = "tie"
        elif avg_score_a > avg_score_b:
            winner = "A"
        else:
            winner = "B"

        # Combine explanations
        explanation = (
            f"[평가1] {result1.get('explanation', '')}\n"
            f"[평가2 (위치 교환)] {result2.get('explanation', '')}"
        )

        return PairwiseResult(
            winner=winner,
            score_a=round(avg_score_a, 1),
            score_b=round(avg_score_b, 1),
            explanation=explanation,
            position_bias_check=True,
        )
    except Exception as exc:
        logger.error("Pairwise evaluation failed: %s", exc)
        return PairwiseResult(
            winner="tie", score_a=0, score_b=0,
            explanation=f"평가 오류: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# Batch evaluation (test suite)
# ---------------------------------------------------------------------------

def run_eval_suite(
    test_cases: list[EvalTestCase],
    eval_model: str | None = None,
    mode: str = "pointwise",
) -> EvalSuiteResult:
    """Run evaluation across a suite of test cases.

    Args:
        test_cases: List of test cases to evaluate
        eval_model: Model for evaluation (default: gpt-4o)
        mode: "pointwise" or "pairwise"

    Returns:
        EvalSuiteResult with aggregated scores
    """
    results: list[dict[str, Any]] = []
    total_score = 0.0
    criteria_totals: dict[str, float] = {}
    criteria_counts: dict[str, int] = {}

    for tc in test_cases:
        if mode == "pointwise":
            result = pointwise_evaluate(
                user_question=tc.user_question,
                agent_answer=tc.response_a,
                tool_calls=tc.tool_calls_a,
                tables_context=tc.tables_context,
                eval_model=eval_model,
            )
            results.append({
                "id": tc.id,
                "question": tc.user_question,
                "overall_score": result.overall_score,
                "criteria_scores": result.criteria_scores,
                "explanation": result.explanation,
            })
            total_score += result.overall_score

            for k, v in result.criteria_scores.items():
                criteria_totals[k] = criteria_totals.get(k, 0) + v
                criteria_counts[k] = criteria_counts.get(k, 0) + 1

        elif mode == "pairwise":
            result = pairwise_evaluate(
                user_question=tc.user_question,
                response_a=tc.response_a,
                response_b=tc.response_b,
                tool_calls_a=tc.tool_calls_a,
                tool_calls_b=tc.tool_calls_b,
                tables_context=tc.tables_context,
                eval_model=eval_model,
            )
            results.append({
                "id": tc.id,
                "question": tc.user_question,
                "winner": result.winner,
                "score_a": result.score_a,
                "score_b": result.score_b,
                "explanation": result.explanation,
            })
            total_score += max(result.score_a, result.score_b)

    n = len(test_cases) or 1
    criteria_averages = {
        k: round(criteria_totals[k] / criteria_counts[k], 2)
        for k in criteria_totals
    }

    return EvalSuiteResult(
        total=len(test_cases),
        avg_score=round(total_score / n, 2),
        criteria_averages=criteria_averages,
        results=results,
    )


# ---------------------------------------------------------------------------
# Built-in test cases for DATAEZ prompt evaluation
# ---------------------------------------------------------------------------

BUILTIN_TEST_CASES: list[EvalTestCase] = [
    EvalTestCase(
        id="greeting_01",
        user_question="안녕하세요!",
        expected_intent="greeting",
        expected_tools=[],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="crud_insert_01",
        user_question="오늘 매출 추가해줘. 커피 5000원, 케이크 8000원",
        expected_intent="crud",
        expected_tools=["describe_table", "insert_rows"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="crud_query_01",
        user_question="전체 데이터 보여줘",
        expected_intent="crud",
        expected_tools=["query_data"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="analysis_chart_01",
        user_question="월별 매출 추이 차트로 보여줘",
        expected_intent="analysis",
        expected_tools=["query_data", "generate_chart"],
        tables_context="매출 (500행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="schema_create_01",
        user_question="재고 장부 만들어줘",
        expected_intent="schema",
        expected_tools=["create_table"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="crud_update_01",
        user_question="어제 커피 매출 5000원을 6000원으로 수정해줘",
        expected_intent="crud",
        expected_tools=["update_rows"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="analysis_cross_01",
        user_question="매출이랑 비용 비교해줘",
        expected_intent="analysis",
        expected_tools=["cross_query", "generate_chart"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)\n비용 (80행): 날짜(DATE), 항목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="edge_no_tables_01",
        user_question="데이터 보여줘",
        expected_intent="crud",
        expected_tools=[],
        tables_context="(장부 없음)",
    ),
    EvalTestCase(
        id="edge_offtopic_01",
        user_question="오늘 날씨 어때?",
        expected_intent="greeting",
        expected_tools=[],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="crud_delete_01",
        user_question="어제 케이크 매출 삭제해줘",
        expected_intent="crud",
        expected_tools=["delete_rows"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="schema_alter_01",
        user_question="매출 장부에 카테고리 컬럼 추가해줘",
        expected_intent="schema",
        expected_tools=["describe_table", "alter_table"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="mixed_intent_01",
        user_question="매출 추가하고 차트도 보여줘",
        expected_intent="general",
        expected_tools=["insert_rows", "query_data", "generate_chart"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    # --- Known failure scenarios ---
    EvalTestCase(
        id="confusion_insert_vs_query_01",
        user_question="커피 3000원, 케이크 5000원 추가해줘",
        expected_intent="crud",
        expected_tools=["describe_table", "insert_rows"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="confusion_insert_vs_query_02",
        user_question="오늘 비용 기록해줘. 재료비 50000원",
        expected_intent="crud",
        expected_tools=["describe_table", "insert_rows"],
        tables_context="비용 (50행): 날짜(DATE), 항목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="no_confirm_01",
        user_question="어제 데이터 전부 삭제해줘",
        expected_intent="crud",
        expected_tools=["delete_rows"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="multi_step_analysis_01",
        user_question="이번 달 매출 현황 분석해줘",
        expected_intent="analysis",
        expected_tools=["query_data", "generate_chart"],
        tables_context="매출 (500행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="cross_query_01",
        user_question="매출 대비 비용 비율이 어떻게 돼?",
        expected_intent="analysis",
        expected_tools=["cross_query"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)\n비용 (80행): 날짜(DATE), 항목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="schema_create_with_columns_01",
        user_question="직원 장부 만들어줘. 이름, 직급, 입사일, 급여 컬럼으로",
        expected_intent="schema",
        expected_tools=["create_table"],
        tables_context="매출 (100행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)",
    ),
    EvalTestCase(
        id="ambiguous_table_name_01",
        user_question="매출 현황 보여줘",
        expected_intent="crud",
        expected_tools=["query_data"],
        tables_context="매출관리 (200행): 날짜(DATE), 품목(TEXT), 금액(BIGINT)\n매출요약 (50행): 월(TEXT), 합계(BIGINT)",
    ),
    EvalTestCase(
        id="onboarding_no_tables_01",
        user_question="매출 분석해줘",
        expected_intent="analysis",
        expected_tools=[],
        tables_context="(장부 없음)",
    ),
]
