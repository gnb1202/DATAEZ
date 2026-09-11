# Vercel API feasibility probes

These tools verify dependencies and selected pure functions, not the complete DATA:EZ backend.
Neither tool runs the application lifespan, connects to a database, nor calls a model.
See [findings and acceptance criteria](../../docs/VERCEL_API_FEASIBILITY.md).

## Offline Linux measurement

Build the current `api/Dockerfile`, or use an existing image only if its dependency versions match.
The probe checks every direct requirement and records installed transitive versions.
Mount the current API directory at `/candidate` and this directory at `/audit`:

```powershell
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=256m --memory 2g --cpus 1 --env PYTHONDONTWRITEBYTECODE=1 --mount type=bind,source=D:/Github/DATAEZ/api,target=/candidate,readonly --mount type=bind,source=D:/Github/DATAEZ/scripts/vercel-audit,target=/audit,readonly --entrypoint python dataez-public-check-20260910t165457z-06e7e735-api:latest /audit/probe.py
```

The measured image ID was `sha256:a21c1f89f8daf2b66d7211d06a10dcae5e54beee171621729b718fdcac9f4b22`.
The image is local and not a public prerequisite; a fresh build can have different transitive versions and measurements.
The fake configuration values are isolated probe inputs. Never use them in a real service.

## Temporary Vercel measurement

The 2026-09-11 probe used a separate Hobby project, subsequently deleted.
It did not change the existing `dataez` frontend project.

1. Extract committed `api/app` and `api/requirements.txt` to a clean staging directory.
2. Copy `entrypoint.py` to staging `index.py`, next to `app/` and `requirements.txt`.
3. Add `.python-version` containing `3.12`, and this `vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "fastapi",
  "functions": {"index.py": {"maxDuration": 300}},
  "regions": ["icn1"]
}
```

4. Link only a dedicated temporary project. Exclude `.env*`, `.vercel`, `.git`.
   The CLI can create an `.env.local` with an OIDC token while linking; it must not be uploaded.
   Inspect `vercel deploy --dry --json` and allow only the source and configuration above.
5. Deploy with the existing Hobby account. The first deployment of a new project can be assigned to production;
   it is still a separate disposable project. Never point this probe at the product frontend project.
6. Use `vercel curl / --deployment URL` from the linked staging directory for authenticated probe access.
   Assert JSON scope, `source_routes_mounted=false`, `source_lifespan_executed=false` and the expected route count.
7. Assert `/probe` returns 1,000 rows and 12,000,000 total; `/stream` emits `data: 0`, `data: 1`, `data: 2`.
   POST binary bodies to `/payload`: 1,000,000 bytes returns HTTP 200 and its exact length;
   6,000,000 bytes returns HTTP 413 with `FUNCTION_PAYLOAD_TOO_LARGE`.
8. Save only sanitized results, then remove the temporary project. Do not retain or publish CLI bypass tokens.

Use CLI `--help` before replaying commands because flags can change. CLI 59.15.1 was used for this run.
An unauthenticated request can redirect to a Vercel login page that returns HTTP 200;
that is not a successful API check. Validate the response type and contents.
