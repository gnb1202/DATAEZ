# Deployment

Updated 2026-09-10. This is a local/deployment runbook; the current work has not
published a live service. [Integration and validation record](RELEASE_INTEGRATION.md)

For a persistent portfolio demo, use [the demo runbook](DEMO_RUNBOOK.md):
`python scripts/demo/run.py start`, `status`, `stop`, and `restart --no-build`.
It uses a separate Compose project with retained database/upload volumes,
generated local DB/JWT secrets, loopback-only ports and workspace ownership labels.
Ordinary Compose service names remain `db`, `api`, `web`; fixed container names
have been removed to let these environments coexist. Use `docker compose exec api`
instead of assuming a global container name.

## Local

```bash
cp .env.example .env      # fill in OPENAI_API_KEY
docker compose up --build
```

Brings up three services: PostgreSQL with pgvector, the API, and the web app,
with healthchecks, memory/CPU limits and log rotation. Postgres is not published
to the host — the API reaches it over the Compose network. Request limiting
runs inside the API; Redis is no longer a dependency.

Verify:

```bash
curl localhost:8000/health          # {"status":"ok","storage_backend":"local"}
curl localhost:8000/ready           # 503 if Postgres is unavailable
curl -s localhost:8000/metrics | head
```

## Migrations

Compose mounts **only `db/init.sql` and `001_pgvector_rag.sql`** into
`/docker-entrypoint-initdb.d`. Postgres executes those on a fresh data volume,
not on every startup. It does not automatically mount all numbered migrations.

For existing databases, `ensure_*` functions run at startup and converge the
schema — including migrating `content_tsv` off the generated column introduced
by 001, saved metric schedules, imports, indexing jobs, file scope and samples.
The numbered SQL files document equivalent schema changes; the API startup
code is also required for runtime initialization and existing-data adoption.
Back up an existing database before upgrading and verify `/ready` after startup.

| Migration | Purpose |
|---|---|
| `001_pgvector_rag.sql` | `schema_embeddings`, `document_chunks`, HNSW + GIN indexes |
| `002_korean_fts.sql` | `content_tsv` from generated column to app-populated |
| `003_metric_scheduling.sql` | Widget intervals, next due time and failures |
| `004_ledger_imports.sql` | Sources, import batches and row provenance |
| `005_event_review.sql` | Event decisions and duplicate/conflict review |
| `006_attribute_restoration.sql` | Optional payment-attribute restoration audit |
| `007_search_index_jobs.sql` | Durable catalog/document search work |
| `008_metric_definition_revisions.sql` | Definition revisions and restoration |
| `009_cash_entries.sql` | Reviewed cash records and idempotency |
| `010_file_library.sql` | Account-owned retained-file catalog |
| `011_widget_save_keys.sql` | Stable widget save keys and payload hashes |
| `012_original_file_analysis.sql` | Original-file analysis binding and write guard function |
| `013_sample_workspace.sql` | Per-account sample store mapping |
| `014_sample_restarts.sql` | Owner-scoped retry keys for non-destructive sample restarts |

`main.py` calls the idempotent `ensure_*` functions before serving requests.
`ensure_library()` includes the original-file schema and sample mapping. The
source-analysis write trigger is installed when the immutable table is created.
Do not remove a Docker volume merely to apply a newer schema.

### After 002: reindex

Rows written before 002 have an empty `content_tsv` and are invisible to the
sparse half of the hybrid search until re-analysed. Embeddings are untouched,
so this costs no API calls and is safe to re-run:

```bash
# The image copies app/, not repository scripts/. Copy this helper explicitly.
docker compose cp scripts/reindex_fts.py api:/tmp/reindex_fts.py
docker compose exec -e PYTHONPATH=/app api python /tmp/reindex_fts.py
# Or locally with database/model/JWT environment configured:
cd api && python ../scripts/reindex_fts.py
```

## Production checklist

**Required**

- [ ] `APP_ENV=production` — enables strict secret validation
- [ ] `JWT_SECRET_KEY` regenerated (`secrets.token_urlsafe(32)`); the dev value is rejected
- [ ] `POSTGRES_PASSWORD` set to something other than the compose default
- [ ] `ALLOWED_ORIGINS` restricted to real frontend origins
- [ ] `NEXT_PUBLIC_API_URL` set **as a build arg** and the web image rebuilt —
      it is inlined into the client bundle and cannot be changed at runtime
- [ ] `NEXT_PUBLIC_SITE_URL` set to the public HTTPS origin as a build arg —
      Open Graph and X/Twitter image URLs are resolved from this value

**Recommended**

- [ ] TLS terminated at a reverse proxy; keep `X-Accel-Buffering: no` intact for SSE
- [ ] `/metrics` restricted at the proxy — it is not authenticated
- [ ] `STORAGE_BACKEND=s3` if more than one API replica runs; the local backend
      writes to a container-local volume
- [ ] Scheduled `db/backup.sh`, and a restore actually tested with `db/restore.sh`
- [ ] Pricing rows in `api/app/llm_cost.py` matching the deployed models

### Pending public site origin (2026-09-11)

No public service domain is recorded in the repository or the local configuration
reviewed during Gathered Ledger integration. `http://localhost:3000` is a local
development default only; assigning the real `NEXT_PUBLIC_SITE_URL` remains an
open deployment task. Use the frontend HTTPS origin, without a path, query, or
fragment. For a direct Next.js build, supply it in the build environment or
`web/.env.local`; the root `.env` is used by Compose.

After the domain is assigned, set `NEXT_PUBLIC_SITE_URL` in the Compose `.env`,
rebuild with `docker compose build web`, and use that image for deployment.
Verify that the rendered `og:image` and `twitter:image` URLs resolve to
`/og-dataez.png` on the real HTTPS origin and return the 1200×630 PNG publicly.
Changing only the running container's environment does not update the built
metadata. No push or deployment was performed during this integration.

## Scaling notes

Known constraints, stated rather than discovered later:

- **Metrics are per-process.** `prometheus_client` here has no multiprocess
  collector, so with `--workers > 1` a scrape reports whichever worker answered.
  Run one worker per container and scale containers, or add
  `PROMETHEUS_MULTIPROC_DIR`.
- **Run one API worker and one replica for the demo.** The image uses
  `--workers 1`. Request limits share a lock across threads, expire inactive
  keys and reset on API restart. They do not share counts across processes.
  Revisit a shared limiter before using multiple workers/replicas.
- **Local storage is container-local.** Multiple replicas need S3.
- **Import and indexing are distinct.** File parsing and transactional row
  import use request paths. Search chunking/embedding runs through durable DB
  jobs with retries; a retained file is not necessarily ready for document search.
- **Schedulers run in API processes.** Due metrics and indexing workers stop
  while all API processes are offline. Widget due times and job state persist
  in PostgreSQL and are picked up after restart.
- **Load validation is pending.** Row locks prevent workers claiming the same
  due metric, but synthetic acceptance does not establish production capacity.

## Streaming behind a proxy

The SSE endpoint sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
Proxies that buffer responses will defeat token streaming — the response still
arrives, but all at once, which is the behaviour this design exists to avoid.

nginx:

```nginx
location /api/conversations/ {
    proxy_pass              http://api:8000;
    proxy_buffering         off;
    proxy_read_timeout      600s;
    proxy_set_header        Connection '';
    proxy_http_version      1.1;
}
```

The server emits a heartbeat every 15s while the agent is busy, so idle
timeouts below that will cut healthy turns.

## Backups

```bash
./db/backup.sh              # pg_dump to db/backups/
./db/restore.sh <file>      # restore
```

Both scripts are pinned to LF line endings via `.gitattributes`; a CRLF
checkout would break them inside a Linux container.

## CI

### Redis removal verification (2026-09-10)

After removing Redis, the local API suite passed **487 tests / 239 skipped**
(external test DBs and optional SQL dependencies were not configured). New
coverage exercises concurrent admission, expiry boundaries, inactive-key cleanup,
blocked requests and readiness with/without PostgreSQL.

A freshly built API image and a disposable PostgreSQL container also passed
`/health` and `/ready` over HTTP. The image had no installed `redis` package;
with the test login limit set to two, three attempts returned `401, 401, 429`.
No LLM calls were made. The temporary containers and volumes were cleaned up.
This verifies API container startup and request limiting; it is not a public
deployment or a rerun of the full browser/LLM acceptance.

### Repository checks

`.github/workflows/`:

- `test.yml` — pytest, golden-dataset validation, Next.js type-check and build
- `docker.yml` — both images build

The eval gate that spends tokens (`make eval`) is **not** in CI. It is run on
demand before merging changes to routing or prompts.
