from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://dataez:dataez@db:5432/dataez"
    storage_backend: str = "s3"
    aws_region: str = ""
    s3_bucket: str = ""
    s3_prefix: str = "uploads"
    max_upload_size_mb: int = 20
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-nano"
    openai_orchestrator_model: str = "gpt-5.4"
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

    @field_validator("jwt_secret_key")
    @classmethod
    def jwt_secret_must_be_set(cls, v: str) -> str:
        if not v or v == "change-this-in-production":
            raise ValueError(
                "JWT_SECRET_KEY must be set to a secure random value. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return v

    @model_validator(mode="after")
    def validate_storage_config(self) -> "Settings":
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
