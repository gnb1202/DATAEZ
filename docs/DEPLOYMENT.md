# Deployment

## Local

```bash
cp .env.example .env      # fill in OPENAI_API_KEY
docker compose up --build
```

Brings up pgvector, Redis, the API, and the web app with healthchecks, memory
and CPU limits, and log rotation. Postgres and Redis are not published to the
host — the API reaches them over the compose network.

Verify:

```bash
curl localhost:8000/health          # {"status":"ok","storage_backend":"local"}
curl localhost:8000/ready           # 503 if Postgres or Redis is down
curl -s localhost:8000/metrics | head
```

## Migrations

`db/migrations/*.sql` runs automatically on a **fresh** database, mounted into
`/docker-entrypoint-initdb.d`. Postgres only executes those on first
initialisation, so an existing volume never sees them.

For existing databases, `ensure_*` functions run at startup and converge the
schema — including migrating `content_tsv` off the generated column introduced
by 001.

| Migration | Purpose |
|---|---|
| `001_pgvector_rag.sql` | `schema_embeddings`, `document_chunks`, HNSW + GIN indexes |
| `002_korean_fts.sql` | `content_tsv` from generated column to app-populated |

### After 002: reindex

Rows written before 002 have an empty `content_tsv` and are invisible to the
sparse half of the hybrid search until re-analysed. Embeddings are untouched,
so this costs no API calls and is safe to re-run:

```bash
docker compose exec api python /app/../scripts/reindex_fts.py
# or locally:
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

**Recommended**

- [ ] TLS terminated at a reverse proxy; keep `X-Accel-Buffering: no` intact for SSE
- [ ] `/metrics` restricted at the proxy — it is not authenticated
- [ ] `STORAGE_BACKEND=s3` if more than one API replica runs; the local backend
      writes to a container-local volume
- [ ] Scheduled `db/backup.sh`, and a restore actually tested with `db/restore.sh`
- [ ] Pricing rows in `api/app/llm_cost.py` matching the deployed models

## Scaling notes

Known constraints, stated rather than discovered later:

- **Metrics are per-process.** `prometheus_client` here has no multiprocess
  collector, so with `--workers > 1` a scrape reports whichever worker answered.
  Run one worker per container and scale containers, or add
  `PROMETHEUS_MULTIPROC_DIR`.
- **In-memory rate limiting is per-process.** Keep Redis reachable in any
  multi-replica deployment; the fallback is a degraded mode, not a design.
- **Local storage is container-local.** Multiple replicas need S3.
- **Ingestion is synchronous.** Chunking and embedding run inside the upload
  request, so a large PDF holds a connection for its duration.

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

`.github/workflows/`:

- `test.yml` — pytest, golden-dataset validation, Next.js type-check and build
- `docker.yml` — both images build

The eval gate that spends tokens (`make eval`) is **not** in CI. It is run on
demand before merging changes to routing or prompts.
