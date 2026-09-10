# DATAEZ Architecture

Updated 2026-09-10 after [the three implementation merges](RELEASE_INTEGRATION.md).

## Overview

Users upload CSV/XLSX files that become tables ("장부"), then manage and analyse
them in natural language. An LLM agent plans the work, calls tools, and every
data access goes through a SQL layer the model cannot bypass.

Two design decisions shape everything else:

1. **Two-stage routing.** A cheap classification call selects a subset of the
   registered tools before the reasoning loop starts. This narrows both the tool space
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
- `app/hooks/use-workspace-analysis.ts` — selected analysis, history and sources
- `app/hooks/use-chart-saving.ts` — save review, stable request keys and retries
- `components/dashboard/chat-dock.tsx` — collapsible right chat and mobile modal
- `components/dashboard/file-library.tsx` — owned files, store and analysis scope
- `components/dashboard/metric-save-settings.tsx` — title, unit, period, preview and schedule
- `components/dashboard/echarts-chart.tsx` — lazy modular ECharts 6.1.0 with SVG,
  exact-value tooltips and accessible table/SQL evidence
- `app/theme.css`, `app/fonts/` — Charcoal + Blue and local Spoqa Han Sans Neo;
  dark, light and system modes
- `components/dashboard/sections/` — lazily loaded sections
- `components/ui/` — shadcn/ui primitives

### API — `api/app/`

| Module | Responsibility |
|---|---|
| `main.py` | HTTP endpoints, SSE assembly, middleware |
| `agent.py` | Agent loop, sync and streaming |
| `agent_tools.py` | Tool registry, `TOOL_META`, structured errors, per-tool metrics, audit |
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
| `metric_definitions.py`, `dashboard_metrics.py` | Typed definitions, validated SQL, preview and saved execution |
| `multi_metrics.py`, `formula_metrics.py`, `grouped_formula_metrics.py`, `store_metrics.py` | Multi-source, scalar/group formula and multi-store compilers |
| `metric_revisions.py`, `widget_saves.py` | Definition history, restoration and idempotent widget saves |
| `ledger_imports.py`, `event_review.py`, `cash_entries.py` | Transactional imports, event decisions and cash records |
| `file_library.py`, `file_snapshots.py`, `sample_workspace.py` | Retained originals, immutable analysis rows and sample setup |
| `rag_catalog.py`, `index_jobs.py` | Store/source catalog and durable asynchronous search indexing |
| `metric_scheduler.py` | Due metric execution without an LLM or an open browser |

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

## Files, stores and reusable metrics

A project is a store. The API verifies the account owner and store for file,
table, conversation and widget requests. Multi-store definitions record the
explicitly selected owned stores instead of widening a query to the account.

Retained file metadata and bytes are distinct from ledger rows. New library
selections default to `original_file`: hash-verified original bytes are parsed
into immutable analysis rows, with a unique owner/store/file binding and DB
write guards. `linked_ledger` uses the connected ledger including later imports.
Historical references without a scope retain the old linked-ledger meaning.
The original analysis table is excluded from ordinary ledger lists and catalog
indexing. [Scope and removal policy](FILE_SCOPE_AND_FIRST_USE.md)

The model fills typed definitions; compilers create parameterized, read-only
aggregate SQL. Search finds the source, while SQL computes over the selected
structured rows. Retrieved snippets are not a substitute for full aggregation.

| Definition | Scope |
|---|---|
| v1 | Single source aggregates, periods, filters and grouping |
| v2 | Explicit disjoint payment ledgers in one store |
| v3 | Two scalar aggregates with difference, ratio or change formulas |
| v4 | Date/category grouped formulas with aligned dimensions |
| v5 | Explicit owned stores and their payment mappings |

Money is calculated with PostgreSQL numeric/Decimal and transported as exact
strings. Chart coordinates use JavaScript numbers; the table and tooltip keep
the original values. Missing values, a zero denominator and zero are distinct.
Currency conversion and arbitrary Python/JavaScript execution are not provided.

The UI reviews title/unit/period/schedule and requires a current preview for a
recalculable metric. Definition edits invalidate that preview. Save keys are
scoped to owner/store; retries preserve the submitted payload and reuse an
existing widget instead of adding a duplicate. Legacy graphs without a metric
definition remain static snapshots.

## Background execution

- `metric_scheduler.py` polls every 15 seconds, claims due widgets with
  `FOR UPDATE SKIP LOCKED`, and executes their saved definitions without LLM calls.
  Manual, hourly and 24-hour policies are supported. Last success and failures
  are represented separately, and normal API restarts preserve due state.
- `index_jobs.py` polls durable indexing jobs every 5 seconds. It records status,
  retries failures and prevents older work from replacing newer source versions.
- `ledger_routes.py` runs pending import expiry every 60 seconds. Temporary
  staging expiry is distinct from retained originals and committed history.

All three loops run in the API process and are controlled by configuration.
Closing the browser does not stop them; stopping every API process does.
Database initialization is described in [Deployment](DEPLOYMENT.md#migrations).

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

L1 uses a deterministic scorer for the observed router output; the model output
itself can vary. CI validates the dataset without model calls. Live routing and
judge scores are reported separately from SQL, state and permission checks.

Current acceptance also includes real PostgreSQL tests, 50-question natural-language
evaluation, browser fixtures, and a real browser/API/DB/LLM workspace run. See
[the validation index](README.md#검증-근거) for scope, dates and skipped checks.

## Current boundaries

- The portfolio/demo deployment uses one API worker/replica. Request limits are
  process-local, locked across request threads and measured with monotonic time.
  Incoming requests periodically reclaim expired keys; restarting the process
  resets counters. Redis has been removed from code and the default stack.
  A shared limiter is future work if multi-process deployment becomes necessary.

- Actual PG ingestion/connectors, remote storage acceptance, user usability and
  production load remain separate work. Synthetic test results are not those validations.
- Metric changes have revision history; legacy arbitrary CRUD does not have a
  universal confirmation/undo journal.
- File parsing and transactional row import still occur in request paths.
  Search chunking/embedding is a durable background job with retry and status.
- Retrieval recall is measured on bounded fixtures. There is no general retrieval
  quality guarantee or implemented reranker.
- Due and manual refresh are implemented; an import does not immediately trigger
  every related widget. Data arrival and metric calculation are distinct.
