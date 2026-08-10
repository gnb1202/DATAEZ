"""Prometheus metrics for HTTP traffic and the LLM agent.

Replaces a hand-rolled exporter that could only report a mean (it stored a
sum and a count, no buckets), emitted no HELP/TYPE lines, and labelled
HTTP series with the raw request path — so every project and conversation
UUID minted a new time series.

The agent-side metrics are the point of this module: token spend, cost,
per-tool outcomes, and orchestrator routing decisions are what make agent
behaviour and its cost visible.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

# Seconds. Tuned for LLM latency: agent turns routinely run past 10s, and a
# default web bucket set tops out far too early to show that tail.
_LLM_LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120)
_HTTP_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

# ── HTTP ──────────────────────────────────────────────────────────────
http_requests_total = Counter(
    "dataez_http_requests_total",
    "HTTP requests by method, route template, and status class.",
    ["method", "route", "status"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "dataez_http_request_duration_seconds",
    "HTTP request latency by method and route template.",
    ["method", "route"],
    buckets=_HTTP_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# ── LLM calls ─────────────────────────────────────────────────────────
# `role` separates the cheap routing call from the expensive reasoning
# loop, which is the whole point of the two-stage architecture: without it
# a single token total cannot show where spend actually goes.
llm_calls_total = Counter(
    "dataez_llm_calls_total",
    "LLM API calls by model, role (orchestrator|worker|judge|embedding), and outcome.",
    ["model", "role", "outcome"],
    registry=REGISTRY,
)

llm_tokens_total = Counter(
    "dataez_llm_tokens_total",
    "LLM tokens consumed by model, role, and kind (prompt|completion).",
    ["model", "role", "kind"],
    registry=REGISTRY,
)

llm_cost_usd_total = Counter(
    "dataez_llm_cost_usd_total",
    "Estimated LLM spend in USD by model and role.",
    ["model", "role"],
    registry=REGISTRY,
)

llm_call_duration_seconds = Histogram(
    "dataez_llm_call_duration_seconds",
    "LLM call latency by model and role.",
    ["model", "role"],
    buckets=_LLM_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# ── Agent loop ────────────────────────────────────────────────────────
agent_turns_total = Counter(
    "dataez_agent_turns_total",
    "Agent turns by mode (sync|streaming) and outcome.",
    ["mode", "outcome"],
    registry=REGISTRY,
)

agent_iterations = Histogram(
    "dataez_agent_iterations",
    "Loop iterations consumed per agent turn.",
    ["mode"],
    buckets=(1, 2, 3, 4, 5, 8, 12, 16, 20, 25),
    registry=REGISTRY,
)

agent_tool_calls_total = Counter(
    "dataez_agent_tool_calls_total",
    "Tool invocations by tool name and outcome (ok|error).",
    ["tool", "outcome"],
    registry=REGISTRY,
)

agent_tool_duration_seconds = Histogram(
    "dataez_agent_tool_duration_seconds",
    "Tool execution latency by tool name.",
    ["tool"],
    buckets=(0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 30),
    registry=REGISTRY,
)

# `outcome` distinguishes a real routing decision from every degraded path.
# A silent fallback to the full toolset defeats the orchestrator entirely,
# so its rate has to be observable rather than merely logged.
orchestrator_decisions_total = Counter(
    "dataez_orchestrator_decisions_total",
    "Orchestrator routing outcomes (llm_selected|greeting_shortcut|"
    "attachment_shortcut|fallback_parse_error|fallback_api_error|fallback_no_key).",
    ["outcome"],
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """Return (payload, content_type) for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def route_label(request) -> str:
    """Route template (``/api/projects/{project_id}``) rather than the raw path.

    Falling back to the literal path would reintroduce UUID cardinality, so
    unmatched requests collapse to a single ``__unmatched__`` series.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "__unmatched__"
