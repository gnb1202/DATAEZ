# Configuration

All settings come from environment variables. The authoritative defaults live
in [`api/app/config.py`](../api/app/config.py); [`.env.example`](../.env.example)
is a working local template.

Updated 2026-09-13. Defaults below describe code, not a fresh dump of production secrets. [Deployment state](CURRENT_STATUS.md). Docker Compose reads the root `.env` and passes configured
values to the API. A directly started Python process does not automatically
read that file: export its variables or use `uvicorn --env-file ../.env` from
`api/`. Override `DATABASE_URL` and `LOCAL_STORAGE_PATH` for a host
process; Compose network names and container paths are not host defaults.

The [persistent demo runner](DEMO_RUNBOOK.md) generates and retains separate
DB/JWT secrets in ignored `.local-test/demo/settings.json`. It overrides storage
to a local volume, binds `WEB_PORT`/`API_PORT` to loopback with `WEB_BIND`/`API_BIND`,
and sets matching build-time API and CORS URLs. Model configuration still comes
from the root `.env` or process environment.

Validation runs at startup and **fails fast** — a misconfigured deployment does
not boot into a half-working state.

## Local Compose setup

| Variable | Notes |
|---|---|
| `OPENAI_API_KEY` | Startup fails without it |

The template supplies the remaining local Compose settings. This is not a production template; serverless storage, database, authentication and maintenance require separate configuration.

## Environment

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` tightens secret validation |
| `RUNTIME_MODE` | `persistent` | `serverless` changes pool, workers, limits and startup defaults |
| `STARTUP_MIGRATIONS_ENABLED` | `true` (persistent), `false` (serverless) | Apply schema separately before a serverless release |

`APP_ENV=production` rejects a `JWT_SECRET_KEY` that is under 32 characters or
contains `dev` / `insecure`. The development secret shipped in `.env.example`
is deliberately self-describing so this check catches it — the convenient
default cannot reach production by accident.

## Auth

| Variable | Default | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | — | Required. Placeholders are rejected in every environment |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_EXP_MINUTES` | `120` | Access token lifetime |
| `JWT_REFRESH_EXP_DAYS` | `14` | Refresh token lifetime |

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Passwords are hashed with PBKDF2-SHA256 at 200k iterations. Refresh tokens are
rotated on use and stored as hashes.

## Database

| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql://dataez:dataez@db:5432/dataez` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | compose only |
| `DB_POOL_MIN_SIZE` | `2` |
| `DB_POOL_MAX_SIZE` | `10` |
| `DB_POOL_TIMEOUT` | `30` |
| `DB_CONNECT_TIMEOUT` | `10` seconds |
| `DB_POOL_MAX_IDLE` | `600` seconds |
| `DB_PREPARED_STATEMENTS` | `true` |

Requires the `vector` extension. The compose stack uses `pgvector/pgvector:pg16`.

`RUNTIME_MODE=persistent` is the default. `RUNTIME_MODE=serverless` defaults to
pool min/max `0/2`, pool wait `5s`, idle `60s`, and disabled prepared statements.
`STARTUP_MIGRATIONS_ENABLED` defaults to `true` for persistent deployments and
`false` for serverless. Serverless rejects startup migrations, persistent workers,
local storage, and enabled prepared statements. Use the separate migration command
and connection setup in [serverless foundation](SERVERLESS_FOUNDATION.md).

## Storage

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `s3`, or `supabase`; serverless rejects local disk |
| `LOCAL_STORAGE_PATH` | `./data/uploads` | compose mounts a named volume at `/data/uploads` |
| `S3_BUCKET` | — | Required when `STORAGE_BACKEND=s3` |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | — | S3 only |
| `S3_PREFIX` | `uploads` | |
| `S3_ENDPOINT_URL` | empty | Optional private S3-compatible endpoint |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | empty | Explicit server-side credentials for the S3-compatible client |
| `SUPABASE_URL` | empty | HTTPS project origin, required for the Supabase Storage backend |
| `SUPABASE_SECRET_KEY` | empty | Server-only secret API key or legacy service-role JWT; never expose as `NEXT_PUBLIC_*` |
| `SUPABASE_STORAGE_BUCKET` | `dataez-files` | Private bucket for the Supabase Storage backend |
| `MAX_UPLOAD_SIZE_MB` | `20` | |

The S3 client is constructed lazily, so a local-only deployment never needs AWS
configuration present.

Original download authorization uses API owner/store checks; depending on the route, bytes are proxied or a short-lived signed download URL is returned. Supabase private Storage direct upload/download was verified in the [public acceptance](PUBLIC_DEMO_ACCEPTANCE.md).
The S3-compatible adapter is available, but remote provider acceptance has not
been performed in the latest workspace test. Storage credentials must remain
server-side and must not use a `NEXT_PUBLIC_` prefix.

## Models

| Variable | Default | Role |
|---|---|---|
| `OPENAI_MODEL` | `gpt-5.4` | Worker — the multi-step reasoning loop |
| `OPENAI_ORCHESTRATOR_MODEL` | `gpt-5.4-nano` | Router — one short classification |
| `OPENAI_JUDGE_MODEL` | `gpt-4o` | Evaluation only |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | |
| `OPENAI_EMBEDDING_DIM` | `1536` | Must match the migration's `vector(n)` |

Tiering follows task difficulty. The worker plans SQL, reads schemas, and
recovers from tool errors; the orchestrator emits one object under a fixed
schema. Pricing per model lives in
[`api/app/llm_cost.py`](../api/app/llm_cost.py) — add a row there when changing
models, or spend is counted at zero and logged as a warning.

> `OPENAI_EMBEDDING_DIM` is declared but the migrations hardcode `vector(1536)`.
> Switching to a 3072-dimension model requires editing the migration too.

## RAG

| Variable | Default | Notes |
|---|---|---|
| `RAG_ENABLED` | `true` | |
| `RAG_TOP_K` | `5` | Results returned; the candidate pool is `4 × k` |
| `RAG_RRF_K` | `60` | RRF damping constant |
| `INDEX_WORKER_ENABLED` | `true` (persistent), `false` (serverless) | Enables the resident index loop. With it disabled, jobs need the maintenance runner or an explicit supported retry/run path |

Korean text is analysed into morphemes before indexing and querying. See
[ARCHITECTURE.md](ARCHITECTURE.md#retrieval) for why.

## Agent limits

| Variable | Default | Notes |
|---|---|---|
| `AGENT_MAX_ITERATIONS` | `25` (persistent), `8` (serverless) | Tool-call rounds per turn |
| `AGENT_MAX_TOKEN_BUDGET` | `100000` (persistent), `24000` (serverless) | Checked before each iteration |
| `MAX_SELECT_ROWS` | `10000` | Hard cap on any SELECT |
| `QUERY_TIMEOUT_MS` | `30000` | Postgres `statement_timeout` |

The budget is checked *before* each iteration against tokens already spent, so
a single call can overshoot it. It is a circuit breaker, not a hard ceiling.

## Rate limiting

| Variable | Default |
|---|---|
| `AUTH_RATE_LIMIT_PER_MINUTE` | `20` |
| `QUERY_RATE_LIMIT_PER_MINUTE` | `60` |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | `10` |
| `DELETE_RATE_LIMIT_PER_MINUTE` | `20` |

In `persistent` mode the sliding-window limiter runs in process memory and needs no external service.
A lock protects admission across request threads, monotonic time avoids wall-clock
adjustments, and incoming requests trigger expired-key cleanup at most once per
minute. Rejected requests do not extend the window or add history.

Run one API worker/replica with this configuration. Counters reset when the API
restarts and are not shared across processes. In `serverless` mode the API already uses atomic PostgreSQL windows shared across instances. A DB check failure returns 503 and an exhausted window returns 429; Redis is not required. `/ready` checks PostgreSQL, not admission behavior. See [`rate_limiter.py`](../api/app/rate_limiter.py).

## CORS and frontend

| Variable | Default | Notes |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated |
| `NEXT_PUBLIC_API_URL` | Development: `http://localhost:8000`; production: unset | **Build-time**; an unset production URL disables authentication and API requests |
| `NEXT_PUBLIC_SITE_URL` | Vercel production/deployment hostname, otherwise `http://localhost:3000` | **Build-time**; explicit value overrides the origin for social preview URLs |

Both `NEXT_PUBLIC_*` values are resolved while Next.js builds the application.
Setting them only at runtime has no effect — compose passes them as build args.
Deploying to another host requires rebuilding the web image.

The public web is already connected to `https://dataez-api.vercel.app`; authentication is enabled. Docker Compose passes its local API default explicitly. Vercel can publish the
frontend before the API is available: leave `NEXT_PUBLIC_API_URL` unset to show
the service preparation notice and disable authentication. Once the HTTPS API
is ready, configure this variable and redeploy. API/model/database secrets do
not belong in frontend environment variables.

When `NEXT_PUBLIC_SITE_URL` is omitted on Vercel, server-side metadata uses
`VERCEL_PROJECT_PRODUCTION_URL`, falling back to `VERCEL_URL`. Set an explicit
site URL when a custom canonical domain is selected.

## Retention

| Variable | Default |
|---|---|
| `CONVERSATION_TTL_DAYS` | `90` |

The cutoff uses the last conversation update. Cleanup runs in `initialize_database()`; serverless startup skips that initializer. This is not a guaranteed daily deletion schedule. Deleting a conversation cascades to its messages, quality runs and feedback; exported candidate files remain separate. See [quality retention](CHAT_QUALITY_OBSERVABILITY.md).

## Background jobs

| Variable | Default | Effect |
|---|---|---|
| `METRIC_SCHEDULER_ENABLED` | `true` (persistent), `false` (serverless) | Executes due saved metrics; poll interval 15 seconds |
| `INDEX_WORKER_ENABLED` | `true` (persistent), `false` (serverless) | Executes search indexing/retry jobs; poll interval 5 seconds |
| `IMPORT_CLEANUP_ENABLED` | `true` (persistent), `false` (serverless) | Expires pending import staging; poll interval 60 seconds |
| `MAINTENANCE_ENABLED` | `false` | Enables the authenticated bounded runner for Supabase Cron |
| `MAINTENANCE_SECRET` | empty | Separate server-only ASCII secret, at least 32 characters |

Widget schedules are stored separately: `0` (manual), `3600` (hourly) or
`86400` (every 24 hours). These are recalculation schedules, not PG collection
schedules. Persistent workers require a running API process. The serverless profile
disables those loops and uses [Supabase scheduled maintenance](SERVERLESS_MAINTENANCE.md)
instead. Each invocation has a 120-second child-process deadline and DB lease. Details
and retained-file policy: [Deployment](DEPLOYMENT.md), [file scope](FILE_SCOPE_AND_FIRST_USE.md).

## Serverless AI admission and execution

Serverless instances share PostgreSQL request counters; database failures reject admission (503).
`AI_USER_REQUESTS_PER_DAY=30` and `AI_TOTAL_REQUESTS_PER_DAY=100` count attempts in a
24-hour window beginning at first admission, including failed/interrupted turns. These are
request limits, not billing caps; background embeddings are separate.
`AGENT_TIMEOUT_SECONDS=200` (10–240) bounds a disposable child process. Serverless
defaults also set `AGENT_MAX_ITERATIONS=8`, `AGENT_MAX_TOKEN_BUDGET=24000`; worker
completions are capped at 4096 tokens per call. Chat messages allow 1–8000 characters.
See [release guards](SERVERLESS_RELEASE_GUARDS.md) for upload paths, recovery and validation.

## Conversation quality

| Variable | Default | Effect |
|---|---|---|
| `QUALITY_ADMIN_USER_IDS` | empty | Comma-separated UUIDs from the API's own `users` table. Empty means no quality administrators; email/client input does not grant access |
| `QUALITY_RELEASE` | `local` | API release label saved with new runs; distinct from the web deployment ID |

Quality observation is attached to authenticated, owned chat endpoints. It does
not backfill old runs or guarantee that every observation write succeeds.
`completed` means execution completion, not a correct answer. Administrators can
inspect other users' recorded conversations. Keep their UUID allowlist server-side;
do not publish account identifiers in release evidence. See [behavior, access,
retention and verification](CHAT_QUALITY_OBSERVABILITY.md).
