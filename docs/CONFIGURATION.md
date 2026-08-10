# DATAEZ Configuration Reference

All settings are loaded from environment variables via Pydantic Settings (`api/app/config.py`).

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://dataez:dataez@db:5432/dataez` | PostgreSQL connection string |
| `DB_POOL_MIN_SIZE` | `2` | Minimum connection pool size |
| `DB_POOL_MAX_SIZE` | `10` | Maximum connection pool size |
| `DB_POOL_TIMEOUT` | `30` | Pool connection acquisition timeout (seconds) |

## Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_KEY` | *(required)* | Secret for signing JWTs. Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXP_MINUTES` | `120` | Access token expiry (minutes) |
| `JWT_REFRESH_EXP_DAYS` | `14` | Refresh token expiry (days) |

## OpenAI

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `OPENAI_MODEL` | `gpt-5.4-nano` | Worker model for agent tool execution |
| `OPENAI_ORCHESTRATOR_MODEL` | `gpt-5.4` | Orchestrator model for intent classification |

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `s3` | Storage backend: `s3` or `local` |
| `S3_BUCKET` | *(required if s3)* | S3 bucket name |
| `S3_PREFIX` | `uploads` | S3 key prefix for uploaded files |
| `AWS_REGION` | `` | AWS region |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum file upload size (MB) |

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_RATE_LIMIT_PER_MINUTE` | `20` | Auth endpoints (signup/login/refresh) per IP |
| `QUERY_RATE_LIMIT_PER_MINUTE` | `60` | AI query endpoints per user |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection for rate limiting |

## Agent Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MAX_ITERATIONS` | `25` | Maximum tool call iterations per agent run |
| `AGENT_MAX_TOKEN_BUDGET` | `100000` | Maximum token budget per agent run |

## SQL Execution

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_SELECT_ROWS` | `10000` | Maximum rows returned by SELECT queries |
| `QUERY_TIMEOUT_MS` | `30000` | SQL query timeout (milliseconds) |

## Miscellaneous

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowed origins (comma-separated) |
| `CONVERSATION_TTL_DAYS` | `90` | Auto-cleanup conversations older than this |

## Frontend

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL (build-time) |
