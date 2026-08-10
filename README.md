# DATAEZ

소규모 사업자를 위한 AI 기반 데이터 관리 & 시각화 플랫폼.
자연어로 데이터를 추가/수정/삭제하고, 차트를 생성하고, 대시보드에 고정할 수 있습니다.

## Stack
- **Web**: Next.js 16 + React 19 + TypeScript + Tailwind CSS 4 + shadcn/ui
- **API**: FastAPI (Python) + OpenAI Function Calling
  - Orchestrator: gpt-5.4 (intent 분류 + 동적 도구 선택)
  - Worker: gpt-5.4-nano (실제 도구 실행)
- **DB**: PostgreSQL (동적 사용자 테이블) + pgvector (문서 임베딩)
- **Cache / Rate limit**: Redis (in-memory fallback 지원)
- **Storage**: AWS S3 / Local (원본 파일 보관)
- **Orchestration**: Docker Compose

## Quick Start

필요한 건 OpenAI API 키 하나입니다. 기본값은 로컬 파일 저장소라 AWS 계정 없이 동작합니다.

```bash
cp .env.example .env      # OPENAI_API_KEY 만 채우면 됩니다
docker compose up --build
```

- Web: http://localhost:3000
- API health: http://localhost:8000/health

> `.env.example`의 `JWT_SECRET_KEY`는 개발 전용 값입니다. `APP_ENV=production`으로 두면
> 설정 검증이 이 값을 거부하므로 실수로 배포될 수 없습니다.

## Core Features
- **프로젝트 관리**: 사업장별 프로젝트 생성/관리
- **장부 관리**: CSV/XLSX 업로드로 장부(테이블) 생성, 데이터 미리보기, CSV 내보내기
- **AI 채팅**: 자연어로 데이터 조회, 추가, 수정, 삭제 (14개 도구)
- **Orchestrator**: gpt-5.4 기반 intent 분류 + 동적 도구 선택
- **문서 RAG**: PDF/MD/TXT 업로드 → pgvector 임베딩 → 하이브리드 검색(RRF)으로 답변에 활용
- **차트 생성**: AI가 데이터 분석 후 line/bar/pie 차트 자동 생성
- **대시보드**: 생성된 차트를 대시보드에 고정, 드래그/리사이즈
- **운영**: JWT 인증 + refresh token 로테이션, Redis 레이트 리밋, 감사 로그, 구조화 JSON 로깅, `/metrics`

## API Endpoints

### Health / Ops
- `GET /health` — 라이브니스
- `GET /ready` — 레디니스 (DB 연결 확인)
- `GET /metrics` — Prometheus 스타일 메트릭

### Auth
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/audit-logs` — 감사 로그 조회

### Projects
- `POST /api/projects` — 프로젝트 생성
- `GET /api/projects` — 프로젝트 목록
- `GET /api/projects/{id}` — 프로젝트 상세
- `PUT /api/projects/{id}` — 프로젝트 수정
- `DELETE /api/projects/{id}` — 프로젝트 삭제

### Tables (장부)
- `POST /api/projects/{pid}/tables` — 빈 테이블 생성
- `GET /api/projects/{pid}/tables` — 테이블 목록
- `GET /api/projects/{pid}/tables/{tid}` — 테이블 상세
- `PUT /api/projects/{pid}/tables/{tid}` — 테이블 수정
- `DELETE /api/projects/{pid}/tables/{tid}` — 테이블 삭제
- `POST /api/projects/{pid}/tables/import` — CSV/XLSX 임포트
- `POST /api/projects/{pid}/tables/{tid}/append` — 데이터 추가
- `GET /api/projects/{pid}/tables/{tid}/data` — 데이터 조회
- `GET /api/projects/{pid}/tables/{tid}/export` — CSV 내보내기

### Documents (RAG)
- `POST /api/projects/{pid}/documents` — 문서 업로드 (PDF/MD/TXT)
- `GET /api/projects/{pid}/documents` — 문서 목록
- `DELETE /api/projects/{pid}/documents/{fid}` — 문서 삭제

### Files
- `POST /api/files/upload` — 파일 업로드
- `GET /api/files` — 파일 목록

### Conversations (AI 채팅)
- `POST /api/conversations` — 대화 생성
- `GET /api/conversations` — 대화 목록
- `DELETE /api/conversations/{id}` — 대화 삭제
- `GET /api/conversations/{id}/messages` — 메시지 목록
- `POST /api/conversations/{id}/messages` — 메시지 전송 (동기)
- `POST /api/conversations/{id}/messages/stream` — 메시지 전송 (SSE 스트리밍)

### Dashboard
- `GET /api/dashboard/widgets` — 위젯 목록
- `POST /api/dashboard/widgets` — 위젯 생성
- `PUT /api/dashboard/widgets/layout` — 레이아웃 업데이트
- `DELETE /api/dashboard/widgets/{id}` — 위젯 삭제

## Environment Variables

시작용 템플릿은 [.env.example](.env.example), 상세 설명은 [docs/CONFIGURATION.md](docs/CONFIGURATION.md) 참고.
기본값의 최종 출처는 [api/app/config.py](api/app/config.py)입니다.

**필수 (`.env.example`에 미리 채워져 있지 않은 것)**
- `OPENAI_API_KEY` — 미설정 시 기동 실패

**환경**
- `APP_ENV` (기본값: `development`) — `production`이면 설정 검증이 강화되어 개발용 JWT 시크릿(길이 32 미만 또는 `dev`/`insecure` 포함)을 거부합니다
- `JWT_SECRET_KEY` — 미설정/플레이스홀더면 기동 실패 (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- `POSTGRES_PASSWORD`

**Storage**
- `STORAGE_BACKEND`: `local`(기본값) or `s3` — 그 외 값은 기동 시 거부
- `LOCAL_STORAGE_PATH` (기본값: `./data/uploads`, compose에서는 `/data/uploads` 볼륨)
- `S3_BUCKET` — `STORAGE_BACKEND=s3`일 때 필수
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`(optional)
- `S3_PREFIX`, `MAX_UPLOAD_SIZE_MB` (기본값: `20`)

**OpenAI / RAG**
- `OPENAI_MODEL` — Worker 모델 (기본값: `gpt-5.4-nano`)
- `OPENAI_ORCHESTRATOR_MODEL` — Orchestrator 모델 (기본값: `gpt-5.4`, intent 분류 + 도구 선택)
- `OPENAI_EMBEDDING_MODEL` (기본값: `text-embedding-3-small`), `OPENAI_EMBEDDING_DIM` (기본값: `1536`)
- `RAG_ENABLED` (기본값: `true`), `RAG_TOP_K` (기본값: `5`), `RAG_RRF_K` (기본값: `60`)

**Auth / Rate limit / CORS**
- `JWT_ALGORITHM`, `JWT_EXP_MINUTES`, `JWT_REFRESH_EXP_DAYS`
- `AUTH_RATE_LIMIT_PER_MINUTE`, `QUERY_RATE_LIMIT_PER_MINUTE`, `UPLOAD_RATE_LIMIT_PER_MINUTE`, `DELETE_RATE_LIMIT_PER_MINUTE`
- `REDIS_URL` — 미가용 시 in-memory 레이트 리밋으로 폴백
- `ALLOWED_ORIGINS` — 쉼표 구분

**Limits**
- `AGENT_MAX_ITERATIONS` (기본값: `25`), `AGENT_MAX_TOKEN_BUDGET` (기본값: `100000`)
- `MAX_SELECT_ROWS` (기본값: `10000`), `QUERY_TIMEOUT_MS` (기본값: `30000`)
- `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_POOL_TIMEOUT`, `CONVERSATION_TTL_DAYS`

## Testing

```bash
cd api && pip install -r requirements.txt -r requirements-dev.txt && python -m pytest tests/ -v
```

- **188 tests** (pytest), 11개 테스트 모듈
- 대상: `agent_tools`(47), `integration`(30), `data_import`(23), `prompts`(19), `router`(19), `auth`(16), `agent`(11), `document_processor`(9), `config`(5), `sql_executor`(5), `rate_limiter`(4)
- 외부 의존성(DB, OpenAI, Redis, S3) mock 처리 — 실제 인프라 없이 실행 가능
- `scripts/e2e_rag_test.py`는 실제 API/OpenAI 키가 필요한 별도 E2E 스크립트 (CI 미포함)

CI는 [.github/workflows](.github/workflows)에서 API 테스트와 web 빌드, 두 Docker 이미지 빌드를 검증합니다.

## Project Structure
```text
.
|- api/
|  |- app/
|  |  |- main.py               # FastAPI endpoints (auth/projects/tables/documents/chat/dashboard)
|  |  |- schemas.py            # Pydantic request/response models
|  |  |- agent.py              # AI agent loop (OpenAI Function Calling)
|  |  |- agent_tools.py        # 14 tools + TOOL_META + structured errors
|  |  |- router.py             # Orchestrator: intent 분류 + 동적 도구 선택
|  |  |- prompts.py            # 조건부 시스템 프롬프트 (intent/table state)
|  |  |- eval_judge.py         # LLM-as-a-Judge 평가 모듈
|  |  |- rag.py                # pgvector 하이브리드 검색 (vector + FTS, RRF)
|  |  |- document_processor.py # PDF/MD/TXT 텍스트 추출 + 청킹
|  |  |- sql_executor.py       # Safe SQL execution layer
|  |  |- data_import.py        # CSV/XLSX → PostgreSQL pipeline
|  |  |- data_ops.py           # Recharts 차트 데이터 빌더
|  |  |- db.py                 # Database operations (psycopg3 pool)
|  |  |- auth.py               # JWT auth + refresh token rotation
|  |  |- rate_limiter.py       # Redis sliding window + in-memory fallback
|  |  |- storage.py            # S3 / local storage backend
|  |  |- openai_clients.py     # OpenAI client factory (sync/async)
|  |  |- llm.py                # Lightweight LLM utilities
|  |  |- config.py             # Settings (env vars, validation)
|  |  |- exceptions.py         # Custom exception hierarchy
|  |  |- metrics.py            # In-memory Prometheus-style metrics
|  |  `- logging_config.py     # Structured JSON logging
|  |- tests/                   # 188 tests (pytest, 외부 의존성 mock)
|  |- requirements.txt
|  |- requirements-dev.txt
|  `- Dockerfile
|- web/
|  |- app/
|  |  |- dashboard/page.tsx    # Main dashboard page
|  |  |- components/           # Chat panel, message bubble, reasoning steps, upload modal
|  |  |- contexts/             # dashboard-context (project ID, apiFetch)
|  |  |- hooks/                # use-auth, use-streaming
|  |  `- lib/                  # api.ts, api-schemas.ts
|  |- components/
|  |  |- dashboard/            # Sidebar, header, sections, recharts-chart
|  |  `- ui/                   # shadcn/ui components
|  |- package.json
|  `- Dockerfile
|- db/
|  |- init.sql                 # System tables schema
|  |- migrations/              # 001_pgvector_rag.sql
|  |- backup.sh
|  `- restore.sh
|- scripts/
|  `- e2e_rag_test.py          # RAG E2E 스크립트 (실제 API 키 필요, CI 미포함)
|- docs/
|  |- ARCHITECTURE.md
|  |- CONFIGURATION.md
|  `- DEPLOYMENT.md
|- .github/workflows/          # test.yml, docker.yml
`- docker-compose.yml
```
