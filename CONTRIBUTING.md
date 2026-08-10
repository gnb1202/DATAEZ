# Contributing to DATAEZ

## Development Setup

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker & Docker Compose
- PostgreSQL 16 (or use Docker)
- Redis 7 (or use Docker)

### Backend (API)
```bash
cd api
pip install -r requirements.txt -r requirements-dev.txt

# Set required env vars
export JWT_SECRET_KEY="dev-secret-for-testing"
export OPENAI_API_KEY="your-key"
export STORAGE_BACKEND="local"

# Run tests
python -m pytest tests/ -v

# Start dev server
uvicorn app.main:app --reload --port 8000
```

### Frontend (Web)
```bash
cd web
npm install

# Start dev server
npm run dev

# Build
npm run build

# Lint
npm run lint
```

### Full Stack (Docker)
```bash
cp .env.example .env
# Edit .env with your values
docker compose up --build
```

## Branch Strategy

- `main` — Production-ready code
- Feature branches: `feature/<description>`
- Bug fixes: `fix/<description>`

## Pull Request Process

1. Create a feature/fix branch from `main`
2. Make changes with tests
3. Ensure all tests pass:
   - `python -m pytest tests/ -v` (API)
   - `npm run build` (Web)
4. Submit PR with description of changes
5. Wait for review and CI checks

## Coding Conventions

### Python (Backend)
- Follow PEP 8
- Use type hints for function signatures
- Add docstrings to public functions
- Use `psycopg sql.SQL`/`sql.Identifier` for dynamic SQL (never f-strings)
- Raise custom exceptions from `app.exceptions` instead of raw `HTTPException`

### TypeScript (Frontend)
- Use TypeScript strict mode
- React functional components only
- Use `React.memo` for list-rendered components
- Korean UI text, English code/comments

## Testing

### Backend
```bash
# All tests
python -m pytest tests/ -v

# Single file
python -m pytest tests/test_auth.py -v

# With coverage
python -m pytest tests/ --cov=app --cov-report=term-missing
```

### Test Structure
- `test_auth.py` — Password hashing, JWT tokens, policy
- `test_agent.py` — Suggestion parsing
- `test_agent_tools.py` — Tool execution, mutation tracking
- `test_router.py` — Orchestrator routing logic
- `test_integration.py` — Full API endpoint testing via TestClient
- `test_sql_executor.py` — Table access validation
- `test_data_import.py` — CSV import, type inference
- `test_config.py` — Settings validation
- `test_rate_limiter.py` — Rate limiting logic
- `test_prompts.py` — System prompt building
