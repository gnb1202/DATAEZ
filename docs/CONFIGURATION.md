# Configuration

All settings come from environment variables. The authoritative defaults live
in [`api/app/config.py`](../api/app/config.py); [`.env.example`](../.env.example)
is a working local template.

Validation runs at startup and **fails fast** — a misconfigured deployment does
not boot into a half-working state.

## The only value you must supply

| Variable | Notes |
|---|---|
| `OPENAI_API_KEY` | Startup fails without it |

Everything else in `.env.example` already works for a local run.

## Environment

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` tightens secret validation |

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

Requires the `vector` extension. The compose stack uses `pgvector/pgvector:pg16`.

## Storage

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local` or `s3`; any other value is rejected at startup |
| `LOCAL_STORAGE_PATH` | `./data/uploads` | compose mounts a named volume at `/data/uploads` |
| `S3_BUCKET` | — | Required when `STORAGE_BACKEND=s3` |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | — | S3 only |
| `S3_PREFIX` | `uploads` | |
| `MAX_UPLOAD_SIZE_MB` | `20` | |

The S3 client is constructed lazily, so a local-only deployment never needs AWS
configuration present.

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

Korean text is analysed into morphemes before indexing and querying. See
[ARCHITECTURE.md](ARCHITECTURE.md#retrieval) for why.

## Agent limits

| Variable | Default | Notes |
|---|---|---|
| `AGENT_MAX_ITERATIONS` | `25` | Tool-call rounds per turn |
| `AGENT_MAX_TOKEN_BUDGET` | `100000` | Checked before each iteration |
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
| `REDIS_URL` | `redis://redis:6379/0` |

Redis-backed sliding window, falling back to in-memory when Redis is
unreachable. In-memory is per-process and does not hold across replicas.

## CORS and frontend

| Variable | Default | Notes |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | **Build-time** |

`NEXT_PUBLIC_API_URL` is inlined into the client bundle by Next.js at build
time. Setting it only at runtime has no effect — compose passes it as a build
arg. Deploying to another host requires rebuilding the web image.

## Retention

| Variable | Default |
|---|---|
| `CONVERSATION_TTL_DAYS` | `90` |
