# DATAEZ Architecture

## Overview

DATAEZ is an AI-powered data management and visualization platform for small businesses. Users upload CSV/XLSX files, manage structured data tables, and interact with an AI agent that can query, mutate, and visualize their data through natural language.

## System Architecture

```
[Browser] <-> [Next.js Frontend] <-> [FastAPI Backend] <-> [PostgreSQL]
                                          |                      |
                                          +-> [Redis]            +-> User Data Tables
                                          +-> [OpenAI API]       +-> System Tables
                                          +-> [S3/Local Storage]
```

## Layer Structure

### Frontend (Next.js 16 + React 19)
- **`web/app/`** — App Router pages and hooks
  - `dashboard/page.tsx` — Main dashboard with section routing
  - `hooks/use-auth.ts` — JWT authentication (access token in memory only)
  - `hooks/use-streaming.ts` — SSE streaming for real-time agent steps
  - `contexts/dashboard-context.tsx` — Shared state (project ID, apiFetch)
- **`web/components/dashboard/`** — Dashboard UI components
  - `sections/` — Lazy-loaded section components (dashboard, ai-chat, tables, settings)
  - `sidebar.tsx`, `header.tsx` — Navigation shell
- **`web/components/ui/`** — shadcn/ui primitives

### Backend (FastAPI + psycopg3)
- **`api/app/main.py`** — All HTTP endpoints (auth, projects, tables, conversations, dashboard)
- **`api/app/auth.py`** — JWT auth with PBKDF2 password hashing, refresh token rotation
- **`api/app/db.py`** — Database access layer (connection pool, CRUD operations)
- **`api/app/agent.py`** — AI Agent loop with OpenAI Function Calling
- **`api/app/agent_tools.py`** — Tool definitions and executor (query, insert, update, delete, chart, etc.)
- **`api/app/router.py`** — Orchestrator: GPT-based dynamic tool selection
- **`api/app/sql_executor.py`** — Safe SQL execution with table access validation
- **`api/app/data_import.py`** — CSV/XLSX import with type inference
- **`api/app/prompts.py`** — System prompt builder with context management
- **`api/app/config.py`** — Pydantic Settings with validation
- **`api/app/exceptions.py`** — Custom exception hierarchy
- **`api/app/metrics.py`** — In-memory Prometheus-style metrics
- **`api/app/logging_config.py`** — Structured JSON logging with request tracking

### Database (PostgreSQL 16)
- **System tables**: `users`, `projects`, `table_meta`, `conversations`, `messages`, `files`, `dashboard_widgets`, `refresh_tokens`, `query_history`
- **User data tables**: Dynamically created as `ut_{user_id_prefix}_{table_id}` with per-user isolation

## Data Flow

### AI Chat Flow
```
1. User sends message via SSE endpoint
2. Message saved to DB
3. Orchestrator (GPT-5.4) analyzes intent and selects tools
4. Agent loop (GPT-5.4-nano) executes tools iteratively:
   - list_tables, describe_table (read schema)
   - query_data, cross_query (SELECT)
   - insert_rows, update_rows, delete_rows (mutations)
   - generate_chart (visualization)
   - create_table, alter_table (DDL)
5. Each step streamed to client as SSE event
6. Final answer + charts + table data saved and sent
```

### Security Model
- Access tokens: In-memory only (never persisted to storage)
- Refresh tokens: SHA-256 hashed in DB, rotation on use
- Table isolation: `ut_{uid}_{tid}` naming + runtime validation
- SQL injection prevention: `psycopg sql.SQL`/`sql.Identifier` for all dynamic SQL
- Rate limiting: Redis sorted-set sliding window with in-memory fallback
- Security headers: X-Content-Type-Options, X-Frame-Options, CSP, etc.

### Agent Architecture
```
Orchestrator (GPT-5.4)          Worker (GPT-5.4-nano)
+-------------------+          +------------------+
| Analyze question  |          | Execute tools    |
| Select tools      | -------> | Function Calling |
| Classify intent   |          | Max 25 iterations|
+-------------------+          | 100k token budget|
                               +------------------+
```

## Key Design Decisions

1. **Sync psycopg3 + Connection Pool**: Simpler than async drivers; offloaded to threads via `asyncio.to_thread()`
2. **Two-Model Agent**: Orchestrator (expensive, smart) selects tools once; Worker (cheap, fast) executes iteratively
3. **Dynamic Table Naming**: `ut_{uid}_{tid}` provides per-user data isolation without row-level security complexity
4. **SSE Streaming**: Real-time agent step visibility without WebSocket complexity
5. **In-memory Access Tokens**: Prevents token theft from localStorage/sessionStorage
