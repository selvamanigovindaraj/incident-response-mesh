from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.secrets import SecretRef


class QueueSettings(BaseModel):
    backend: Literal["redis", "memory"] = "memory"
    redis_url: str | None = None
    max_deliveries: int = 3

    @model_validator(mode="after")
    def _require_redis_url_when_redis(self) -> QueueSettings:
        if self.backend == "redis" and not self.redis_url:
            raise ValueError(
                "queue.redis_url is required when queue.backend == 'redis'"
            )
        return self


class LocksSettings(BaseModel):
    backend: Literal["redis", "memory"] = "memory"
    redis_url: str | None = None

    @model_validator(mode="after")
    def _require_redis_url_when_redis(self) -> LocksSettings:
        if self.backend == "redis" and not self.redis_url:
            raise ValueError(
                "locks.redis_url is required when locks.backend == 'redis'"
            )
        return self


class BlobStoreSettings(BaseModel):
    base_dir: str = "/tmp/blobs"


class PostgresSettings(BaseModel):
    dsn: SecretRef | None = None


class LLMSettings(BaseModel):
    provider: str | None = None


class ObservabilitySettings(BaseModel):
    otlp_endpoint: str | None = None


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="forbid",
    )

    app_env: Literal["local", "ci", "cluster"] = "local"
    service_name: str

    queue: QueueSettings = Field(default_factory=QueueSettings)
    locks: LocksSettings = Field(default_factory=LocksSettings)
    blob_store: BlobStoreSettings = Field(default_factory=BlobStoreSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
