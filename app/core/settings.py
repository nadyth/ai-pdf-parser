from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "pdf-parser"
    app_env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./storage/pdfparser.db"
    redis_url: str = "redis://localhost:6379/0"

    gcs_bucket: str = "pdf-parser"
    gcs_project: str = "local"
    gcs_path_prefix: str = "pdf-parser"

    pdf_render_dpi: int = 300
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    max_pages: int = 1000
    page_concurrency: int = 4
    keep_page_images: bool = True

    # Rule extraction is chunked when the consolidated text spans more pages
    # than this. Each chunk is sent to the rule model independently and the
    # outputs are merged (lists concatenate; dicts shallow-merge).
    rule_chunk_pages: int = 40

    # Per-LLM-call retry/backoff (transient 429/5xx etc.)
    llm_max_attempts: int = 5
    llm_backoff_base_seconds: float = 2.0

    # arq job timeout for parse_document.
    parse_job_timeout_seconds: int = 6 * 60 * 60  # 6 hours

    webhook_timeout_seconds: float = 10.0
    webhook_max_retries: int = 5
    webhook_backoff_base_seconds: float = 2.0  # 2, 4, 8, 16, 32 …

    model_routes_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
