from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.secrets import SecretRef

# libs/config/config/settings.py lives at <repo_root>/libs/config/config/settings.py
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _select_env_file() -> str:
    app_env = os.environ.get("APP_ENV", "local")
    return str(_REPO_ROOT / "config" / "env" / f"{app_env}.env")


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

    def __init__(self, **kwargs: Any) -> None:
        # Resolve the env overlay file fresh on every instantiation (rather than
        # once at class-definition time) so APP_ENV changes take effect per-call.
        kwargs.setdefault("_env_file", _select_env_file())
        super().__init__(**kwargs)


def load_settings(service_name: str) -> AppSettings:
    """
    Build and validate AppSettings for `service_name`, exiting the process
    with a readable, field-named error report on any validation failure.
    """
    try:
        return AppSettings(service_name=service_name)
    except ValidationError as exc:
        print(f"Configuration error for service '{service_name}':", file=sys.stderr)
        for error in exc.errors():
            loc = ".".join(str(part) for part in error["loc"])
            print(f"  {loc}: {error['msg']}", file=sys.stderr)
        raise SystemExit(1) from exc
