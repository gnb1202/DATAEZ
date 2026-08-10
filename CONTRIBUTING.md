# Contributing to DATAEZ

## Development Setup

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker & Docker Compose

### Backend (API)

```bash
cd api
pip install -r requirements.txt -r requirements-dev.txt

export APP_ENV=development
export JWT_SECRET_KEY="dev-insecure-local-jwt-secret-do-not-deploy"
export OPENAI_API_KEY="your-key"
export STORAGE_BACKEND=local

make test                                    # or: python -m pytest tests/ -q
uvicorn app.main:app --reload --port 8000
```

The test suite mocks Postgres, Redis, OpenAI, and S3, so it runs with no
infrastructure. The `OPENAI_API_KEY` above only has to satisfy startup
validation.

### Frontend (Web)

```bash
cd web
npm install
npm run dev
npx tsc --noEmit     # type check
npm run build
```

### Full stack

```bash
cp .env.example .env      # fill in OPENAI_API_KEY
docker compose up --build
```

## Branch strategy

- `main` — always green
- `feat/<description>`, `fix/<description>`, `docs/<description>`

Keep one concern per branch. A PR that changes routing behaviour and also
reformats a module is two reviews pretending to be one.

## Pull requests

1. Branch from `main`
2. Make the change **with tests that fail without it**
3. Verify:
   - `cd api && make test`
   - `cd api && make eval-validate` if you touched `app/eval/` or tool names
   - `cd web && npx tsc --noEmit && npm run build`
4. Write the PR body around *why*: what was broken, how you know, what the
   numbers were before and after
5. Wait for CI

### Commit messages

Explain the problem, not the patch. The diff already shows what changed.

```
fix(rag): index Korean by morpheme so the sparse channel actually matches

to_tsvector('simple', content) splits on whitespace only. Korean is
agglutinative, so 매출이 and 매출을 became unrelated tokens and a query
for 매출 matched neither.

  before: 0 hits
  after:  1 hit
```

Do not add co-author trailers.

## Evaluation workflow

Changes to `router.py`, `prompts.py`, or the tool specs affect agent behaviour
that unit tests cannot capture. Run the eval suite before merging those.

```bash
cd api
make eval-validate    # offline: schema-checks the golden set, no API calls
make eval             # live: one orchestrator call per case, gates on thresholds
make eval-report      # live + writes a Markdown scorecard for the PR body
```

CI runs `eval-validate` on every push. The live gate is manual because it
spends tokens.

### Adding golden cases

Golden cases live in `api/app/eval/golden/routing.yaml`:

```yaml
- id: ana-016
  question: "작년 대비 올해 객단가 어때?"
  expected_intent: analysis
  expected_tools: [query_data]
  tools_mode: subset      # or `exact` when selecting anything is the error
  tags: [aggregate, comparison]
  notes: "왜 이 라벨이 맞는지"
```

- Label the **minimum** tools that answer the question. The orchestrator's job
  is to narrow the tool space, so listing every plausible tool makes the target
  meaningless and inflates the score.
- Use `tools_mode: exact` only where selecting anything is itself the failure —
  a greeting, or a prompt-injection attempt.
- Adversarial cases are the valuable ones. A greeting followed by a real
  request, an ambiguous reference, an embedded instruction — those are where
  routing actually breaks.

## Coding conventions

### Python

- PEP 8, type hints on signatures, docstrings on public functions
- **Dynamic SQL goes through `psycopg.sql.SQL` / `sql.Identifier`.** Never
  f-strings. Identifiers reach this layer from an LLM
- Raise from `app.exceptions`, not bare `HTTPException`
- New LLM call sites are wrapped in `track_llm_call` with a `role`. An
  uninstrumented call is invisible to cost accounting
- Adding a model means adding a row to `app/llm_cost.py`, or its spend is
  counted at zero
- User-controlled text entering a prompt goes through `app/untrusted.py`

### TypeScript

- Strict mode, functional components
- `React.memo` for list-rendered components
- Korean UI text, English code and comments

### Comments

Explain why, not what. A comment restating the line below it is noise; a
comment recording a constraint that is not visible from the code is the only
kind worth writing.

## Testing

```bash
python -m pytest tests/ -q
python -m pytest tests/test_router.py -q
python -m pytest tests/ --cov=app --cov-report=term-missing
```

Write the test so it fails without the fix. A test that passes before and after
documents nothing.

### Test modules

| File | Covers |
|---|---|
| `test_auth.py` | Password hashing, JWT, refresh rotation, policy |
| `test_config.py` | Settings validation, env-aware secret rules |
| `test_agent.py` | Suggestion parsing |
| `test_agent_streaming.py` | Token frames, tool-call reassembly, error frames |
| `test_agent_tools.py` | Tool execution, mutation tracking |
| `test_agent_safety.py` | Audit parity, injection fencing |
| `test_router.py` | Routing, schema enforcement, degraded fallback |
| `test_prompts.py` | Conditional prompt assembly |
| `test_eval_routing.py` | Golden set validity, scoring, CI gates |
| `test_eval_judge.py` | Judge config, position bias, pairwise aggregation |
| `test_llm_telemetry.py` | Token and cost accounting |
| `test_korean_text.py` | Morpheme tokenization, token counting |
| `test_sql_executor.py` | Table access validation |
| `test_data_import.py` | CSV import, type inference |
| `test_document_processor.py` | Chunking |
| `test_rate_limiter.py` | Sliding window |
| `test_integration.py` | Endpoints via TestClient |
