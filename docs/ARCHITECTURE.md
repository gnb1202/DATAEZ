# DATAEZ Architecture

## Overview

Users upload CSV/XLSX files that become tables ("장부"), then manage and analyse
them in natural language. An LLM agent plans the work, calls tools, and every
data access goes through a SQL layer the model cannot bypass.

Two design decisions shape everything else:

1. **Two-stage routing.** A cheap classification call selects a subset of the
   14 tools before the reasoning loop starts. This narrows both the tool space
   and the prompt, and it is why observability here is organised by *pipeline
   stage* rather than by model.
2. **The model never writes SQL.** It fills in parameters on typed tools; the
   SQL layer composes statements with quoted identifiers, an operator
   allowlist, and a mandatory WHERE clause on mutations.

## Request flow

```
Browser
  │  POST /api/conversations/{id}/messages/stream   (multipart)
  ▼
FastAPI middleware ── request id, route-template metrics, security headers
  │
  ▼
run_agent_streaming
  │
  ├─► select_tools_via_orchestrator ──────────────┐
  │     1. greeting keyword pre-filter (no LLM)   │  TurnLedger
  │     2. attachment short-circuit               │  records every
  │     3. orchestrator LLM, strict json_schema   │  call's tokens,
  │        └ failure → retry → read-only fallback │  cost, latency
  │                                                │  by role
  ├─► build_system_prompt                          │
  │     intent × table-state × attachments         │
  │     + trust-boundary rule (always)             │
  │                                                │
  └─► loop (≤ 25 iterations, token budget)         │
        ├ stream completion ──────────────────────┘
        │   ├ content delta      → yield token frame
        │   └ tool_call delta    → accumulate by index
        ├ execute tool (thread) → yield step frame
        └ finish → yield answer + meta(usage) frames
```

SSE frames are typed: `token`, `step`, `error`, `heartbeat`, `done`. The
generator is wrapped so an exception raised after headers are sent still
reaches the client as an `error` frame rather than truncating the stream.

## Layers

### Frontend — `web/`

- `app/dashboard/page.tsx` — section routing and shared state
- `app/hooks/use-auth.ts` — JWT handling; the access token stays in memory
- `app/hooks/use-streaming.ts` — SSE reader. Renders `token` frames as they
  arrive, handles `error`, and uses a 60s **idle** timeout reset by any frame
  (heartbeats included) rather than a fixed wall-clock abort
- `components/dashboard/sections/` — lazily loaded sections
- `components/ui/` — shadcn/ui primitives

### API — `api/app/`

| Module | Responsibility |
|---|---|
| `main.py` | HTTP endpoints, SSE assembly, middleware |
| `agent.py` | Agent loop, sync and streaming |
| `agent_tools.py` | 14 tool specs, `TOOL_META`, structured errors, per-tool metrics, audit |
| `router.py` | Orchestrator: intent + tool subset, schema-enforced |
| `prompts.py` | Conditional system prompt assembly |
| `untrusted.py` | Identifier sanitising and content fencing |
| `sql_executor.py` | Safe SQL composition and execution |
| `rag.py` | Hybrid retrieval (dense + sparse, RRF) |
| `korean_text.py` | Morphological analysis for full-text search |
| `tokens.py` | tiktoken counting and truncation |
| `llm_telemetry.py` | `TurnLedger`: per-turn, per-role usage |
| `llm_cost.py` | Model pricing table |
| `metrics.py` | Prometheus metric definitions |
| `eval/` | Golden set, deterministic scoring, CI gate |
| `eval_judge.py` | LLM-as-a-judge (pointwise, pairwise) |

## Orchestration

The orchestrator returns `{intent, tools}` under a strict JSON schema. Three
paths avoid the LLM entirely: a greeting keyword pre-filter, an attachment
short-circuit, and the missing-key case.

On failure it retries once, then degrades to a **read-only** tool set
(`list_tables`, `describe_table`, `query_data`, `search_schema`,
`search_documents`) and marks the result `degraded`, which also suppresses the
first-iteration forced tool call. The earlier behaviour — returning all 14
tools, including `delete_rows`, while still forcing a call — made the failure
path more dangerous than having no router.

Model tiering follows task difficulty: the worker runs the multi-step loop
(`OPENAI_MODEL`), the orchestrator does one short classification
(`OPENAI_ORCHESTRATOR_MODEL`).

## Tool layer

`TOOL_META` carries three flags per tool — `read_only`, `needs_table`,
`mutation` — and drives three behaviours:

- **Read-before-write**: a mutation on a table not yet described triggers an
  automatic `describe_table` first, so the model does not guess column names.
- **Audit**: successful mutations write an audit row. Detail carries affected
  counts, not row payloads.
- **Metrics**: per-tool call counts, outcomes, and latency, with the label
  bounded to known tool names.

Errors returned to the model are structured, not strings:

```json
{
  "error": "table_not_found",
  "message": "장부 '매츨'을(를) 찾을 수 없습니다.",
  "available_tables": ["매출장부", "결제내역"],
  "recovery": "list_tables로 정확한 이름을 확인하세요."
}
```

The `available_*` and `recovery` fields let the model correct itself on the
next iteration instead of repeating the same failing call.

## Data access

Every user table is `ut_{user8}_{table8}`. `sql_executor` validates the name
against the caller's own id, composes statements with `psycopg.sql.Identifier`,
allowlists operators and aggregate functions, caps rows, sets a statement
timeout, and refuses UPDATE/DELETE without a WHERE clause.

## Retrieval

Two channels fused with Reciprocal Rank Fusion in a single SQL statement:

- **dense** — pgvector cosine over `text-embedding-3-small`, HNSW index
- **sparse** — `tsvector` over **morpheme-analysed** text, GIN index

The sparse channel matters because Korean is agglutinative. Indexing raw text
with `to_tsvector('simple', …)` splits on whitespace, so 매출이 / 매출을 / 매출은
become unrelated tokens and a query for 매출 matches none of them. Morphemes are
extracted in the application — a generated column cannot call application code
— and the *same* analysis is applied to queries, since a query analysed
differently from the index cannot match it.

`'simple'` is retained deliberately: it does no stemming, which is correct once
the input is already morphemes.

Two corpora share this design: `schema_embeddings` (one row per table, for
natural-language → table routing) and `document_chunks` (uploaded PDF/MD/TXT).

## Trust boundary

Table names, column names, sample rows, and retrieved chunks are all
user-written. Identifiers are sanitised before entering the system prompt;
retrieved chunks are fenced and labelled with their source and cannot close
their own fence. The system prompt states the rule unconditionally, because
tool results can appear on any turn.

This does not make injected text harmless. It removes ambiguity the model would
otherwise resolve on its own.

## Observability

`TurnLedger` accumulates every LLM call made while answering one message —
orchestrator, worker, and embeddings — so cost can be attributed per stage and
persisted per message (`messages.total_tokens`, `cost_usd`, `usage`).

Prometheus metrics use route templates rather than raw paths, so project and
conversation UUIDs do not mint a time series each.

## Evaluation

Three layers, cheapest first:

| Layer | What it asserts | Cost | Runs in CI |
|---|---|---|---|
| L1 routing | intent accuracy, tool-selection F1 | 1 call/case | validation only |
| L2 behaviour | tool trace and DB state | agent run | on demand |
| L3 judge | answer quality | 1–2 judge calls | on demand |

L1 is deterministic given a model, so it can gate a build; the judge layer
cannot, because its variance would make builds flap.

## Known gaps

- No two-phase confirmation or undo for destructive operations
- Ingestion is synchronous and non-transactional; partial failure reports success
- No retrieval quality metrics (recall@k, MRR), reranker, or query rewriting
- `run_agent` and `run_agent_streaming` duplicate setup; `main.py` is not split
  into routers
