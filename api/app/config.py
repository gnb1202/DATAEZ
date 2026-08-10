from pydantic import model_validator
from pydantic_settings import BaseSettings

# Placeholder secrets that must never reach a real deployment. Kept as an
# explicit blocklist so `.env.example` can ship a working local value while
# still failing loudly if someone copies a placeholder into production.
PLACEHOLDER_SECRETS = {
    "change-this-in-production",
    "your-secret-here",
    "secret",
}


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql://dataez:dataez@db:5432/dataez"
    storage_backend: str = "local"
    local_storage_path: str = "./data/uploads"
    aws_region: str = ""
    s3_bucket: str = ""
    s3_prefix: str = "uploads"
    max_upload_size_mb: int = 20
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-nano"
    openai_orchestrator_model: str = "gpt-5.4"
    # Judge for LLM-as-a-judge evaluation. Kept separate from the agent models
    # so scoring is not done by the same model that produced the answer.
    openai_judge_model: str = "gpt-4o"
    # RAG / embeddings
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dim: int = 1536
    rag_enabled: bool = True
    rag_top_k: int = 5
    rag_rrf_k: int = 60
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 120
    jwt_refresh_exp_days: int = 14
    auth_rate_limit_per_minute: int = 20
    query_rate_limit_per_minute: int = 60
    upload_rate_limit_per_minute: int = 10
    delete_rate_limit_per_minute: int = 20
    allowed_origins: str = "http://localhost:3000"
    redis_url: str = "redis://redis:6379/0"
    # DB pool
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10
    db_pool_timeout: int = 30
    # Agent limits
    agent_max_iterations: int = 25
    agent_max_token_budget: int = 100_000
    # SQL execution limits
    max_select_rows: int = 10_000
    query_timeout_ms: int = 30_000
    # Cleanup
    conversation_ttl_days: int = 90

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        secret = self.jwt_secret_key
        if not secret:
            raise ValueError(
                "JWT_SECRET_KEY must be set to a secure random value. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        if secret in PLACEHOLDER_SECRETS:
            raise ValueError(
                f"JWT_SECRET_KEY is set to the placeholder {secret!r}. "
                "Generate a real one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        # The development default shipped in .env.example is deliberately
        # self-describing so this check can reject it in production.
        if self.is_production:
            lowered = secret.lower()
            if len(secret) < 32 or "dev" in lowered or "insecure" in lowered:
                raise ValueError(
                    "JWT_SECRET_KEY looks like a development value but APP_ENV=production. "
                    "Set a random secret of at least 32 characters."
                )
        return self

    @model_validator(mode="after")
    def validate_storage_config(self) -> "Settings":
        if self.storage_backend not in ("s3", "local"):
            raise ValueError(
                f"STORAGE_BACKEND must be 's3' or 'local', got {self.storage_backend!r}"
            )
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError(
                "S3_BUCKET must be set when STORAGE_BACKEND=s3"
            )
        return self

    @model_validator(mode="after")
    def validate_openai_key(self) -> "Settings":
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY must be set")
        return self

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
    }


settings = Settings()
