# DATAEZ Deployment Guide

## Prerequisites

- Docker & Docker Compose v2+
- AWS credentials (for S3 storage) or local storage mode
- OpenAI API key

## Quick Start (Development)

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your values

# 2. Start all services
docker compose up --build -d

# 3. Verify
curl http://localhost:8000/health
curl http://localhost:3000
```

## Production Deployment

### 1. Environment Variables

Create `.env` with production values (see `docs/CONFIGURATION.md` for all options):

```bash
# Required
POSTGRES_PASSWORD=<strong-random-password>
JWT_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">
OPENAI_API_KEY=sk-...

# Storage
STORAGE_BACKEND=s3
S3_BUCKET=your-bucket-name
AWS_REGION=ap-northeast-2

# Security
ALLOWED_ORIGINS=https://your-domain.com
```

### 2. Build & Push Images

```bash
# Build
docker compose build

# Tag and push (example: ECR)
docker tag dataez-api:latest <account>.dkr.ecr.<region>.amazonaws.com/dataez-api:latest
docker tag dataez-web:latest <account>.dkr.ecr.<region>.amazonaws.com/dataez-web:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/dataez-api:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/dataez-web:latest
```

### 3. Database

- Use managed PostgreSQL (RDS, Cloud SQL) for production
- Update `DATABASE_URL` in `.env`
- Initial schema: `db/init.sql` runs automatically on first start
- Migrations run on API startup (`run_startup_migrations()`)

### 4. Reverse Proxy (Nginx example)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;  # Required for SSE streaming
    }
}
```

### 5. Health Checks

| Endpoint | Purpose | Expected |
|----------|---------|----------|
| `GET /health` | Liveness probe | `{"status": "ok"}` |
| `GET /ready` | Readiness probe (DB + Redis) | `{"status": "ok", "checks": {...}}` |
| `GET /metrics` | Prometheus metrics | Text format |

## Backup & Restore

```bash
# Backup
./db/backup.sh ./backups

# Restore
./db/restore.sh ./backups/dataez_backup_20260404_120000.sql.gz
```

## Scaling Considerations

- **API**: Stateless — scale horizontally behind a load balancer
- **Redis**: Single instance sufficient for rate limiting; use Redis Cluster for HA
- **PostgreSQL**: Vertical scaling preferred; read replicas for analytics
- **OpenAI**: Token budget (100k/request) and rate limits are the primary bottleneck
