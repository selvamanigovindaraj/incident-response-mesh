# Typed Configuration System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `libs/config`, a single pydantic-settings-based typed configuration system, so every service declares its config schema and adapters are selected by config value (e.g. `QUEUE__BACKEND=redis|memory`), not by code branching.

**Architecture:** A new workspace package `libs/config` defines `AppSettings` (root) with nested per-subsystem `BaseModel`s (`queue`, `locks`, `blob_store`, `postgres`, `llm`, `observability`), a `SecretRef` type for secret-by-reference fields, an `APP_ENV`-selected `.env` overlay, and a `load_settings()` fail-fast helper. `libs/adapters`'s `AdapterRegistry` is retyped from `Mapping[str, Any]` to `AppSettings` and gains backend switching for `queue` and `locks` (real Redis vs. `ports-testing`'s in-memory fakes, now promoted to a runtime dependency). `hello-world`, `scenario-runner`, and `scripts/security-audit.py` are migrated to call `load_settings()` at startup.

**Tech Stack:** Python 3.12, `pydantic` 2.x, `pydantic-settings`, `uv` workspaces, `pytest` / `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-09-11-typed-config-design.md`

## Global Constraints

- Python `>=3.12` everywhere (matches every existing `pyproject.toml` in this repo).
- Use `pydantic>=2.0.0` (already pinned at 2.13.5 in `uv.lock`) and add `pydantic-settings>=2.0.0` as a new dependency.
- Follow existing repo conventions: `from __future__ import annotations` at the top of new modules that use it elsewhere in the file's package (match the style of the file being edited), `ruff` + `mypy --strict` clean, tests under a package's `tests/` directory using `pytest`.
- Async tests use the explicit `@pytest.mark.asyncio` marker (this repo does not set `asyncio_mode = "auto"` outside `ports-testing`; `pytest-asyncio`'s default strict mode is used everywhere else).
- Never put a resolved secret value in a `Settings` field, a log line, or a `repr()`. Only `SecretRef` reference *keys* (not values) may appear in plaintext.
- No dynamic/hot config reload. No feature-flag mechanism (out of scope, tracked separately).
- Only `queue` and `locks` get backend switching (`*.backend: "redis" | "memory"`) in this PR — `blob_store`, `postgres` (audit sink), and `secret_store` keep single-backend behavior.

---

### Task 1: Scaffold `libs/config` package with a minimal `AppSettings`

**Files:**
- Create: `libs/config/pyproject.toml`
- Create: `libs/config/config/__init__.py`
- Create: `libs/config/config/settings.py`
- Create: `libs/config/tests/test_settings.py`

**Interfaces:**
- Produces: `config.settings.AppSettings` — a `pydantic_settings.BaseSettings` subclass with fields `app_env: Literal["local", "ci", "cluster"] = "local"` and `service_name: str` (required, no default).

- [x] **Step 1: Create the package manifest**

```toml
# libs/config/pyproject.toml
[project]
name = "config"
version = "0.1.0"
description = "Typed configuration schema for Incident Response Mesh services"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "ports",
]

[build-system]
requires = ["uv_build>=0.11.32,<0.12.0"]
build-backend = "uv_build"

[tool.uv.sources]
ports = { workspace = true }

[dependency-groups]
dev = [
    "mypy>=2.3.1",
    "pytest>=9.1.1",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.16.5",
]
```

Also create a one-line `libs/config/README.md`:

```markdown
# config

Typed configuration schema (pydantic-settings) shared by every Incident Response Mesh service.
```

- [x] **Step 2: Write the failing test for a minimal `AppSettings`**

```python
# libs/config/tests/test_settings.py
from config.settings import AppSettings


def test_app_settings_requires_service_name() -> None:
    settings = AppSettings(service_name="test-service")
    assert settings.service_name == "test-service"
    assert settings.app_env == "local"


def test_app_settings_missing_service_name_raises() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AppSettings()  # type: ignore[call-arg]
```

- [x] **Step 3: Run the test to verify it fails**

Run: `cd libs/config && uv sync --all-extras && uv run pytest -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.settings'` (or similar) since `settings.py` doesn't exist yet.

- [x] **Step 4: Write the minimal `AppSettings`**

```python
# libs/config/config/__init__.py
```

```python
# libs/config/config/settings.py
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="forbid",
    )

    app_env: Literal["local", "ci", "cluster"] = "local"
    service_name: str
```

- [x] **Step 5: Run the test to verify it passes**

Run: `cd libs/config && uv run pytest -v`
Expected: PASS (2 tests)

- [x] **Step 6: Commit**

```bash
git add libs/config
git commit -m "feat(config): scaffold libs/config package with minimal AppSettings"
```

---

### Task 2: Add `SecretRef` type with masked repr

**Files:**
- Create: `libs/config/config/secrets.py`
- Create: `libs/config/tests/test_secrets.py`

**Interfaces:**
- Consumes: nothing new (uses only stdlib + `pydantic_core`).
- Produces: `config.secrets.SecretRef` — usable directly as a pydantic field type. Constructed from a plain non-empty string (the reference *key*, e.g. an env var name or vault path — never the secret value itself). `repr(ref)` and `str(ref)` return `SecretRef('<key>', value=***)`. `await ref.resolve(store)` calls `store.get(ref.key)` where `store` is any object satisfying `ports.interfaces.SecretStore` (`async def get(self, key: str) -> str`).

- [x] **Step 1: Write the failing tests**

```python
# libs/config/tests/test_secrets.py
from __future__ import annotations

import pytest

from config.secrets import SecretRef


class FakeSecretStore:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, key: str) -> str:
        return self._values[key]


def test_secret_ref_repr_masks_value() -> None:
    ref = SecretRef("db/prod/dsn")
    assert repr(ref) == "SecretRef('db/prod/dsn', value=***)"
    assert str(ref) == "SecretRef('db/prod/dsn', value=***)"


def test_secret_ref_key_is_visible_but_not_a_secret_value() -> None:
    ref = SecretRef("db/prod/dsn")
    assert ref.key == "db/prod/dsn"


def test_secret_ref_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        SecretRef("")


@pytest.mark.asyncio
async def test_secret_ref_resolve_calls_store_get_with_key() -> None:
    ref = SecretRef("db/prod/dsn")
    store = FakeSecretStore({"db/prod/dsn": "postgresql://real-secret-value"})
    assert await ref.resolve(store) == "postgresql://real-secret-value"


def test_secret_ref_validates_from_plain_string_via_pydantic() -> None:
    from pydantic import BaseModel

    class Holder(BaseModel):
        dsn: SecretRef

    holder = Holder(dsn="db/prod/dsn")  # type: ignore[arg-type]
    assert isinstance(holder.dsn, SecretRef)
    assert holder.dsn.key == "db/prod/dsn"
    assert "real-secret-value" not in repr(holder)
    assert "SecretRef" in repr(holder)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd libs/config && uv run pytest tests/test_secrets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.secrets'`

- [x] **Step 3: Implement `SecretRef`**

```python
# libs/config/config/secrets.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_core import core_schema

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from ports.interfaces import SecretStore


class SecretRef:
    """
    A reference to a secret by key, never the secret's plaintext value.

    Resolution is lazy and explicit via `resolve()` — constructing or
    reprinting a SecretRef never touches a SecretStore or exposes a value.
    """

    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("SecretRef key must be a non-empty string")
        self._key = key

    @property
    def key(self) -> str:
        return self._key

    def __repr__(self) -> str:
        return f"SecretRef({self._key!r}, value=***)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretRef) and other._key == self._key

    def __hash__(self) -> int:
        return hash(("SecretRef", self._key))

    async def resolve(self, store: SecretStore) -> str:
        """Fetch the plaintext secret value from `store` using this ref's key."""
        return await store.get(self._key)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate, core_schema.str_schema()
        )

    @classmethod
    def _validate(cls, value: str) -> SecretRef:
        return cls(value)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd libs/config && uv run pytest tests/test_secrets.py -v`
Expected: PASS (5 tests)

- [x] **Step 5: Commit**

```bash
git add libs/config
git commit -m "feat(config): add SecretRef type with masked repr and lazy resolve"
```

---

### Task 3: Add per-subsystem settings models with cross-field validation

**Files:**
- Modify: `libs/config/config/settings.py`
- Modify: `libs/config/tests/test_settings.py`

**Interfaces:**
- Consumes: `config.secrets.SecretRef` (Task 2).
- Produces: `config.settings.QueueSettings`, `LocksSettings`, `BlobStoreSettings`, `PostgresSettings`, `LLMSettings`, `ObservabilitySettings` — all plain `pydantic.BaseModel`s with sensible defaults so `AppSettings(service_name=...)` succeeds with zero other env vars set. `AppSettings` gains fields `queue: QueueSettings`, `locks: LocksSettings`, `blob_store: BlobStoreSettings`, `postgres: PostgresSettings`, `llm: LLMSettings`, `observability: ObservabilitySettings`, each defaulting to `Field(default_factory=<Model>)`.

- [x] **Step 1: Write the failing tests**

```python
# libs/config/tests/test_settings.py — add these to the existing file
def test_app_settings_defaults_use_memory_backends(monkeypatch) -> None:
    for var in ("QUEUE__BACKEND", "LOCKS__BACKEND"):
        monkeypatch.delenv(var, raising=False)
    settings = AppSettings(service_name="test-service")
    assert settings.queue.backend == "memory"
    assert settings.locks.backend == "memory"
    assert settings.postgres.dsn is None


def test_queue_backend_redis_requires_redis_url(monkeypatch) -> None:
    import pytest
    from pydantic import ValidationError

    monkeypatch.setenv("QUEUE__BACKEND", "redis")
    monkeypatch.delenv("QUEUE__REDIS_URL", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        AppSettings(service_name="test-service")
    assert "queue.redis_url" in str(exc_info.value)


def test_queue_backend_redis_with_url_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("QUEUE__BACKEND", "redis")
    monkeypatch.setenv("QUEUE__REDIS_URL", "redis://localhost:6379/0")
    settings = AppSettings(service_name="test-service")
    assert settings.queue.backend == "redis"
    assert settings.queue.redis_url == "redis://localhost:6379/0"


def test_postgres_dsn_parses_as_secret_ref(monkeypatch) -> None:
    from config.secrets import SecretRef

    monkeypatch.setenv("POSTGRES__DSN", "POSTGRES_DSN")
    settings = AppSettings(service_name="test-service")
    assert isinstance(settings.postgres.dsn, SecretRef)
    assert settings.postgres.dsn.key == "POSTGRES_DSN"


def test_repr_never_leaks_resolved_secret_value(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES__DSN", "POSTGRES_DSN")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:hunter2@host/db")
    settings = AppSettings(service_name="test-service")
    assert "hunter2" not in repr(settings)
    assert "SecretRef" in repr(settings)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd libs/config && uv run pytest tests/test_settings.py -v`
Expected: FAIL — `AttributeError: 'AppSettings' object has no attribute 'queue'` (and similar)

- [x] **Step 3: Implement the subsystem models and wire them into `AppSettings`**

```python
# libs/config/config/settings.py
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
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd libs/config && uv run pytest -v`
Expected: PASS (all tests in the package)

- [x] **Step 5: Commit**

```bash
git add libs/config
git commit -m "feat(config): add per-subsystem settings models with cross-field validation"
```

---

### Task 4: Add `APP_ENV`-selected `.env` overlay files

**Files:**
- Create: `config/env/local.env`
- Create: `config/env/ci.env`
- Create: `config/env/cluster.env`
- Modify: `libs/config/config/settings.py`
- Modify: `libs/config/tests/test_settings.py`

**Interfaces:**
- Produces: `config.settings._select_env_file() -> str`, used as `SettingsConfigDict(env_file=_select_env_file())`. Reads process env var `APP_ENV` (default `"local"`) and resolves to `<repo_root>/config/env/<app_env>.env`.

- [x] **Step 1: Create the overlay files**

```bash
# config/env/local.env
QUEUE__BACKEND=memory
LOCKS__BACKEND=memory
```

```bash
# config/env/ci.env
QUEUE__BACKEND=redis
QUEUE__REDIS_URL=redis://localhost:6379/0
LOCKS__BACKEND=redis
LOCKS__REDIS_URL=redis://localhost:6379/0
POSTGRES__DSN=POSTGRES_DSN
```

```bash
# config/env/cluster.env
QUEUE__BACKEND=redis
QUEUE__REDIS_URL=redis://redis.irm.svc.cluster.local:6379/0
LOCKS__BACKEND=redis
LOCKS__REDIS_URL=redis://redis.irm.svc.cluster.local:6379/0
POSTGRES__DSN=POSTGRES_DSN
```

`POSTGRES__DSN` in `ci.env`/`cluster.env` is a `SecretRef` *key* (the name of an env var the deployment sets separately), not a DSN itself — consistent with `EnvSecretStore.get(key)` reading `os.environ[key]`.

- [x] **Step 2: Write the failing test**

```python
# libs/config/tests/test_settings.py — add
def test_select_env_file_defaults_to_local(monkeypatch) -> None:
    from config.settings import _select_env_file

    monkeypatch.delenv("APP_ENV", raising=False)
    assert _select_env_file().endswith("config/env/local.env")


def test_select_env_file_respects_app_env(monkeypatch) -> None:
    from config.settings import _select_env_file

    monkeypatch.setenv("APP_ENV", "ci")
    assert _select_env_file().endswith("config/env/ci.env")


def test_ci_env_overlay_is_applied_when_app_env_is_ci(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.delenv("QUEUE__BACKEND", raising=False)
    monkeypatch.delenv("QUEUE__REDIS_URL", raising=False)
    settings = AppSettings(service_name="test-service")
    assert settings.queue.backend == "redis"
    assert settings.queue.redis_url == "redis://localhost:6379/0"


def test_real_env_var_overrides_env_file(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("QUEUE__BACKEND", "memory")
    settings = AppSettings(service_name="test-service")
    assert settings.queue.backend == "memory"
```

- [x] **Step 3: Run tests to verify they fail**

Run: `cd libs/config && uv run pytest tests/test_settings.py -v`
Expected: FAIL — `ImportError: cannot import name '_select_env_file'`

- [x] **Step 4: Implement `_select_env_file` and wire it into `model_config`**

```python
# libs/config/config/settings.py — add near the top, after imports
import os
from pathlib import Path

# libs/config/config/settings.py lives at <repo_root>/libs/config/config/settings.py
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _select_env_file() -> str:
    app_env = os.environ.get("APP_ENV", "local")
    return str(_REPO_ROOT / "config" / "env" / f"{app_env}.env")
```

Update `AppSettings.model_config`:

```python
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=_select_env_file(),
        extra="forbid",
    )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd libs/config && uv run pytest -v`
Expected: PASS (all tests)

- [x] **Step 6: Commit**

```bash
git add config libs/config
git commit -m "feat(config): add APP_ENV-selected .env overlay files"
```

---

### Task 5: Add `load_settings()` fail-fast startup helper

**Files:**
- Modify: `libs/config/config/settings.py`
- Modify: `libs/config/tests/test_settings.py`

**Interfaces:**
- Consumes: `AppSettings` (Task 3).
- Produces: `config.settings.load_settings(service_name: str) -> AppSettings`. On success, returns a validated `AppSettings`. On `pydantic.ValidationError`, prints one line per invalid/missing field to stderr and raises `SystemExit(1)`.

- [x] **Step 1: Write the failing tests**

```python
# libs/config/tests/test_settings.py — add
def test_load_settings_returns_valid_settings(monkeypatch) -> None:
    from config.settings import load_settings

    settings = load_settings("my-service")
    assert settings.service_name == "my-service"


def test_load_settings_exits_nonzero_with_field_named(monkeypatch, capsys) -> None:
    import pytest

    from config.settings import load_settings

    monkeypatch.setenv("QUEUE__BACKEND", "redis")
    monkeypatch.delenv("QUEUE__REDIS_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_settings("my-service")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "queue" in captured.err
    assert "redis_url" in captured.err
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd libs/config && uv run pytest tests/test_settings.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_settings'`

- [x] **Step 3: Implement `load_settings`**

```python
# libs/config/config/settings.py — add at the bottom
import sys

from pydantic import ValidationError


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
```

(Move the `import sys` and `from pydantic import ValidationError` lines up to the top of the file alongside the other imports rather than inline — keep the file's import block at the top.)

- [x] **Step 4: Run tests to verify they pass**

Run: `cd libs/config && uv run pytest -v`
Expected: PASS (all tests)

- [x] **Step 5: Commit**

```bash
git add libs/config
git commit -m "feat(config): add load_settings() fail-fast startup helper"
```

---

### Task 6: Add `config-docs` schema-to-Markdown generator

**Files:**
- Create: `libs/config/config/docs.py`
- Create: `libs/config/tests/test_docs.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `AppSettings.model_json_schema()` (standard pydantic method, no new interface).
- Produces: `config.docs.render_markdown() -> str`, and a `python -m config.docs` CLI entrypoint that prints the rendered Markdown to stdout.

- [x] **Step 1: Write the failing test**

```python
# libs/config/tests/test_docs.py
from config.docs import render_markdown


def test_render_markdown_includes_app_settings_section() -> None:
    output = render_markdown()
    assert "# Configuration Reference" in output
    assert "## AppSettings" in output


def test_render_markdown_includes_nested_subsystem_sections() -> None:
    output = render_markdown()
    assert "## QueueSettings" in output
    assert "backend" in output
    assert "redis_url" in output


def test_render_markdown_includes_field_descriptions_when_present() -> None:
    output = render_markdown()
    assert "service_name" in output
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd libs/config && uv run pytest tests/test_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.docs'`

- [x] **Step 3: Implement the renderer**

```python
# libs/config/config/docs.py
from __future__ import annotations

from typing import Any

from config.settings import AppSettings


def _type_str(field_schema: dict[str, Any]) -> str:
    if "$ref" in field_schema:
        return field_schema["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in field_schema:
        return " | ".join(_type_str(s) for s in field_schema["anyOf"])
    if field_schema.get("type") == "null":
        return "null"
    return str(field_schema.get("type", "any"))


def _render_model(name: str, model_schema: dict[str, Any], lines: list[str]) -> None:
    lines.append(f"## {name}")
    lines.append("")
    required = set(model_schema.get("required", []))
    properties = model_schema.get("properties", {})
    lines.append("| Field | Type | Required | Default | Description |")
    lines.append("|---|---|---|---|---|")
    for field_name, field_schema in properties.items():
        type_str = _type_str(field_schema)
        is_required = "yes" if field_name in required else "no"
        default = field_schema.get("default", "")
        description = field_schema.get("description", "")
        lines.append(f"| {field_name} | {type_str} | {is_required} | {default} | {description} |")
    lines.append("")


def render_markdown() -> str:
    schema = AppSettings.model_json_schema()
    defs = schema.get("$defs", {})
    lines: list[str] = [
        "# Configuration Reference",
        "",
        "Auto-generated by `make config-docs`. Do not edit by hand.",
        "",
    ]
    _render_model("AppSettings", schema, lines)
    for def_name, def_schema in defs.items():
        _render_model(def_name, def_schema, lines)
    return "\n".join(lines) + "\n"


def main() -> None:
    print(render_markdown(), end="")


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd libs/config && uv run pytest -v`
Expected: PASS (all tests)

- [x] **Step 5: Add the `make config-docs` target**

```makefile
# Makefile — add
.PHONY: config-docs
config-docs:
	cd libs/config && uv run python -m config.docs > ../../docs/config.md
```

- [x] **Step 6: Generate `docs/config.md` and verify it manually**

Run: `make config-docs && cat docs/config.md`
Expected: A Markdown file with an `AppSettings` section and one section per subsystem model (`QueueSettings`, `LocksSettings`, `BlobStoreSettings`, `PostgresSettings`, `LLMSettings`, `ObservabilitySettings`).

- [x] **Step 7: Commit**

```bash
git add libs/config Makefile docs/config.md
git commit -m "feat(config): add config-docs schema-to-Markdown generator"
```

---

### Task 7: Retype `AdapterRegistry` to `AppSettings` with queue/lock backend switching

**Files:**
- Modify: `libs/adapters/pyproject.toml`
- Modify: `libs/adapters/src/adapters/registry.py`
- Modify: `libs/adapters/tests/test_registry.py`
- Modify: `libs/adapters/tests/conftest.py`

**Interfaces:**
- Consumes: `config.settings.AppSettings`, `QueueSettings`, `LocksSettings`, `PostgresSettings`, `BlobStoreSettings` (Task 3); `config.secrets.SecretRef.resolve()` (Task 2); `ports_testing.fakes.InMemoryQueue`, `ports_testing.fakes.InMemoryLockService` (existing).
- Produces: `AdapterRegistry(settings: AppSettings)` — same public method names (`start`, `stop`, `get_queue`, `get_lock_service`, `get_blob_store`, `get_audit_sink`, `get_secret_store`) and return types as before; only the constructor's parameter type and the queue/lock backend selection logic change.

- [x] **Step 1: Promote `ports-testing` to a runtime dependency and add `config`**

```toml
# libs/adapters/pyproject.toml
[project]
name = "adapters"
version = "0.1.0"
description = "Adapter implementations for ports interfaces"
readme = "README.md"
authors = [
    { name = "selvamanigovindaraj", email = "selvamanigovindaraj@outlook.com" }
]
requires-python = ">=3.12"
dependencies = [
    "ports",
    "ports-testing",
    "config",
]

[project.optional-dependencies]
redis = [
    "redis>=8.1.0",
]
postgres = [
    "psycopg[pool]>=3.3.5",
]

[build-system]
requires = ["uv_build>=0.11.32,<0.12.0"]
build-backend = "uv_build"

[tool.uv.sources]
ports = { workspace = true }
ports-testing = { workspace = true }
config = { workspace = true }

[dependency-groups]
dev = [
    "mypy>=2.3.1",
    "pytest>=9.1.1",
    "pytest-cov>=4.1.0",
    "ruff>=0.16.5",
]
```

(`ports-testing` moves from the `dev` group to `[project.dependencies]`; the `dev` group no longer lists it.)

- [x] **Step 2: Update `test_registry.py` to build `AppSettings` and expect backend switching (failing first)**

```python
# libs/adapters/tests/test_registry.py
import os

import pytest
from config.settings import AppSettings
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore

from adapters.registry import AdapterRegistry

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://irm_user:irm_password@localhost:5432/irm_db"
)


def _settings(**overrides: object) -> AppSettings:
    base: dict[str, object] = {
        "service_name": "test",
        "queue": {"backend": "redis", "redis_url": REDIS_URL},
        "locks": {"backend": "redis", "redis_url": REDIS_URL},
        "blob_store": {"base_dir": "/tmp/test_blobs"},
    }
    base.update(overrides)
    return AppSettings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_registry_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_POSTGRES_DSN", POSTGRES_DSN)
    settings = _settings(postgres={"dsn": "TEST_POSTGRES_DSN"})

    async with AdapterRegistry(settings) as registry:
        queue = registry.get_queue("test_queue")
        assert isinstance(queue, Queue)

        lock = registry.get_lock_service("test_lock")
        assert isinstance(lock, LockService)

        blob = registry.get_blob_store("test_blob")
        assert isinstance(blob, BlobStore)

        audit = registry.get_audit_sink("test_audit")
        assert isinstance(audit, AuditSink)

        secret = registry.get_secret_store("test_secret")
        assert isinstance(secret, SecretStore)

        assert registry.get_queue("test_queue") is queue
        assert registry.get_lock_service("test_lock") is lock
        assert registry.get_blob_store("test_blob") is blob
        assert registry.get_audit_sink("test_audit") is audit
        assert registry.get_secret_store("test_secret") is secret

        assert registry.get_queue("other_queue") is not queue
        assert registry.get_lock_service("other_lock") is not lock
        assert registry.get_blob_store("other_blob") is not blob
        assert registry.get_audit_sink("other_audit") is not audit
        assert registry.get_secret_store("other_secret") is not secret

    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_queue("test_queue")
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_lock_service("test_lock")
    with pytest.raises(RuntimeError, match="Postgres pool not initialized"):
        registry.get_audit_sink("test_audit")


@pytest.mark.asyncio
async def test_registry_uninitialized_access_raises() -> None:
    registry = AdapterRegistry(_settings())
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_queue("default")
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_lock_service("default")
    with pytest.raises(RuntimeError, match="Postgres pool not initialized"):
        registry.get_audit_sink("default")

    blob = registry.get_blob_store("default")
    assert isinstance(blob, BlobStore)
    secret = registry.get_secret_store("default")
    assert isinstance(secret, SecretStore)


@pytest.mark.asyncio
async def test_registry_memory_backend_needs_no_redis_client() -> None:
    settings = _settings(
        queue={"backend": "memory"}, locks={"backend": "memory"}
    )
    async with AdapterRegistry(settings) as registry:
        queue = registry.get_queue("mem_queue")
        assert isinstance(queue, Queue)
        lock = registry.get_lock_service("mem_lock")
        assert isinstance(lock, LockService)
```

- [x] **Step 3: Update `conftest.py`'s `POSTGRES_DSN`-dependent fixtures if needed**

`conftest.py` already reads `POSTGRES_DSN` from the environment and constructs `PgAuditSink` directly against a raw pool — it is untouched by the registry's constructor signature change, so no edit is required here. Confirm by reading the file: `libs/adapters/tests/conftest.py` does not import `AdapterRegistry`.

- [x] **Step 4: Run tests to verify they fail**

Run: `cd libs/adapters && uv sync --all-extras && uv run pytest tests/test_registry.py -v`
Expected: FAIL — `TypeError: AdapterRegistry.__init__() takes a Mapping, got AppSettings` (or similar type mismatch once `AdapterRegistry` still expects a `Mapping`)

- [x] **Step 5: Retype and update `AdapterRegistry`**

```python
# libs/adapters/src/adapters/registry.py
from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Self

from config.settings import AppSettings
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore

from adapters.env_secret_store import EnvSecretStore
from adapters.fs_blob_store import FsBlobStore

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool
    from redis.asyncio import Redis


class AdapterRegistry:
    """Central registry to manage adapter instances and their connection pools."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._redis_client: Redis | None = None
        self._pg_pool: AsyncConnectionPool | None = None

        self._queues: dict[str, Queue] = {}
        self._locks: dict[str, LockService] = {}
        self._blob_stores: dict[str, BlobStore] = {}
        self._audit_sinks: dict[str, AuditSink] = {}
        self._secret_stores: dict[str, SecretStore] = {}

    async def start(self) -> None:
        """Initialize connection pools based on settings."""
        needs_redis = (
            self._settings.queue.backend == "redis"
            or self._settings.locks.backend == "redis"
        )
        if needs_redis:
            from redis.asyncio import Redis

            redis_url = self._settings.queue.redis_url or self._settings.locks.redis_url
            if not redis_url:
                raise RuntimeError(
                    "A redis_url is required when queue.backend or locks.backend is 'redis'"
                )
            self._redis_client = Redis.from_url(redis_url)

        if self._settings.postgres.dsn is not None:
            from psycopg_pool import AsyncConnectionPool

            dsn = await self._settings.postgres.dsn.resolve(self.get_secret_store())
            self._pg_pool = AsyncConnectionPool(dsn, open=False)
            await self._pg_pool.open()

    async def stop(self) -> None:
        """Close connection pools and clear cached instances."""
        try:
            if self._pg_pool:
                try:
                    await self._pg_pool.close()
                finally:
                    self._pg_pool = None
        finally:
            try:
                if self._redis_client:
                    await self._redis_client.aclose()
            finally:
                self._redis_client = None
                self._queues.clear()
                self._locks.clear()
                self._audit_sinks.clear()
                self._blob_stores.clear()
                self._secret_stores.clear()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()

    def get_queue(self, key: str = "default") -> Queue:
        """Get or instantiate a Queue per settings.queue.backend."""
        if key not in self._queues:
            if self._settings.queue.backend == "memory":
                from ports_testing.fakes import InMemoryQueue

                self._queues[key] = InMemoryQueue()
            else:
                if not self._redis_client:
                    raise RuntimeError("Redis client not initialized")
                from adapters.redis_queue import RedisStreamQueue

                self._queues[key] = RedisStreamQueue(self._redis_client)
        return self._queues[key]

    def get_lock_service(self, key: str = "default") -> LockService:
        """Get or instantiate a LockService per settings.locks.backend."""
        if key not in self._locks:
            if self._settings.locks.backend == "memory":
                from ports_testing.fakes import InMemoryLockService

                self._locks[key] = InMemoryLockService()
            else:
                if not self._redis_client:
                    raise RuntimeError("Redis client not initialized")
                from adapters.redis_lock import RedisLockService

                self._locks[key] = RedisLockService(self._redis_client)
        return self._locks[key]

    def get_blob_store(self, key: str = "default") -> BlobStore:
        """Get or instantiate an FsBlobStore."""
        if key not in self._blob_stores:
            self._blob_stores[key] = FsBlobStore(base_dir=self._settings.blob_store.base_dir)
        return self._blob_stores[key]

    def get_audit_sink(self, key: str = "default") -> AuditSink:
        """Get or instantiate a PgAuditSink."""
        if key not in self._audit_sinks:
            if not self._pg_pool:
                raise RuntimeError("Postgres pool not initialized")
            from adapters.postgres import PgAuditSink

            self._audit_sinks[key] = PgAuditSink(self._pg_pool)
        return self._audit_sinks[key]

    def get_secret_store(self, key: str = "default") -> SecretStore:
        """Get or instantiate an EnvSecretStore."""
        if key not in self._secret_stores:
            self._secret_stores[key] = EnvSecretStore()
        return self._secret_stores[key]
```

- [x] **Step 6: Run tests to verify they pass**

Run: `cd libs/adapters && uv run pytest tests/test_registry.py -v`
Expected: PASS (all tests, requires local `redis` and `postgres` via `docker-compose up -d redis postgres` from repo root)

- [x] **Step 7: Commit**

```bash
git add libs/adapters
git commit -m "feat(adapters): retype AdapterRegistry to AppSettings with queue/lock backend switching"
```

---

### Task 8: Prove zero-code-change backend switching with an integration test

**Files:**
- Create: `libs/adapters/tests/test_backend_switching.py`

**Interfaces:**
- Consumes: `AdapterRegistry` (Task 7), `config.settings.AppSettings`, `ports.types.Message`.

- [x] **Step 1: Write the test**

```python
# libs/adapters/tests/test_backend_switching.py
import os

import pytest
from config.settings import AppSettings
from ports.types import Message

from adapters.registry import AdapterRegistry

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_queue_publish_consume_ack_across_backends(backend: str) -> None:
    settings = AppSettings(
        service_name="test",
        queue={
            "backend": backend,
            "redis_url": REDIS_URL if backend == "redis" else None,
        },
        locks={"backend": "memory"},
    )
    async with AdapterRegistry(settings) as registry:
        queue = registry.get_queue("switch_test")
        msg = Message(payload={"hello": "world"}, idempotency_key=f"switch-{backend}")
        await queue.publish("switch-topic", msg)

        received = await anext(queue.consume("switch-topic", "switch-group"))
        assert received.payload == {"hello": "world"}
        await queue.ack(received)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_lock_acquire_release_across_backends(backend: str) -> None:
    settings = AppSettings(
        service_name="test",
        queue={"backend": "memory"},
        locks={
            "backend": backend,
            "redis_url": REDIS_URL if backend == "redis" else None,
        },
    )
    async with AdapterRegistry(settings) as registry:
        lock_service = registry.get_lock_service("switch_test")
        lease = await lock_service.acquire(f"resource-{backend}", ttl=5.0)
        assert lease.fence >= 1
        await lock_service.release(lease)
```

- [x] **Step 2: Run the test**

Run: `cd libs/adapters && uv run pytest tests/test_backend_switching.py -v`
Expected: PASS (4 tests: 2 backends x 2 scenarios), proving `QUEUE__BACKEND`/`LOCKS__BACKEND` switch behavior with no call-site code changes.

- [x] **Step 3: Commit**

```bash
git add libs/adapters/tests/test_backend_switching.py
git commit -m "test(adapters): prove queue/lock backend switching requires zero code changes"
```

---

### Task 9: Migrate `hello-world` to `load_settings()` with fail-fast startup

**Files:**
- Modify: `services/hello-world/pyproject.toml`
- Modify: `services/hello-world/hello_world/main.py`
- Modify: `services/hello-world/tests/test_main.py`

**Interfaces:**
- Consumes: `config.settings.load_settings` (Task 5).

- [x] **Step 1: Add the `config` dependency**

```toml
# services/hello-world/pyproject.toml
[project]
name = "hello-world"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "config",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv.sources]
config = { workspace = true }

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.1.0",
    "mypy>=1.9.0",
    "ruff>=0.3.0"
]
```

- [x] **Step 2: Write the failing test for fail-fast behavior**

```python
# services/hello-world/tests/test_main.py
import sys

import pytest

from hello_world.main import main


def test_main(capsys):
    assert main() == 0
    captured = capsys.readouterr()
    assert "Hello, world!" in captured.out


def test_main_exits_nonzero_with_field_named_on_missing_config(monkeypatch, capsys):
    monkeypatch.setenv("QUEUE__BACKEND", "redis")
    monkeypatch.delenv("QUEUE__REDIS_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "queue" in captured.err
    assert "redis_url" in captured.err
```

- [x] **Step 3: Run tests to verify the new one fails**

Run: `cd services/hello-world && uv sync && uv run pytest -v`
Expected: `test_main_exits_nonzero_with_field_named_on_missing_config` FAILs — `main()` currently ignores env vars and returns `0`.

- [x] **Step 4: Wire `load_settings` into `main()`**

```python
# services/hello-world/hello_world/main.py
from config.settings import load_settings


def main() -> int:
    load_settings("hello-world")
    print("Hello, world!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Run tests to verify both pass**

Run: `cd services/hello-world && uv run pytest -v`
Expected: PASS (both tests)

- [x] **Step 6: Commit**

```bash
git add services/hello-world
git commit -m "feat(hello-world): fail fast on invalid config via load_settings()"
```

---

### Task 10: Wire `scenario-runner` and `scripts/security-audit.py` to `load_settings()`

**Files:**
- Modify: `services/scenario-runner/pyproject.toml`
- Modify: `services/scenario-runner/scripts/run-scenario.py`
- Modify: `pyproject.toml` (repo root)
- Modify: `scripts/security-audit.py`

**Interfaces:**
- Consumes: `config.settings.load_settings` (Task 5).

- [x] **Step 1: Add `config` dependency to `scenario-runner`**

```toml
# services/scenario-runner/pyproject.toml
[project]
name = "scenario-runner"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "config",
    "pydantic>=2.0.0",
    "pyyaml>=6.0",
    "requests>=2.31.0"
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["scenarios"]

[tool.uv.sources]
config = { workspace = true }

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.1.0",
    "mypy>=1.9.0",
    "ruff>=0.3.0",
    "types-pyyaml",
    "types-requests"
]
```

- [x] **Step 2: Call `load_settings` at the top of `run-scenario.py`'s `main()`**

```python
# services/scenario-runner/scripts/run-scenario.py
# Add near the top imports:
from config.settings import load_settings


def main():
    load_settings("scenario-runner")

    if len(sys.argv) < 2:
        print("Usage: python scripts/run-scenario.py <scenario_id>")
        sys.exit(1)
    # ... rest of function unchanged
```

- [x] **Step 3: Run existing `scenario-runner` tests to confirm no regression**

Run: `cd services/scenario-runner && uv sync && uv run pytest -v`
Expected: PASS — all existing tests in `tests/test_run_scenario.py` still pass, since default settings (memory backends, no postgres) validate successfully with no new required env vars.

- [x] **Step 4: Add `config` dependency to the repo root `pyproject.toml`**

```toml
# pyproject.toml (repo root)
[project]
name = "incident-response-mesh"
version = "0.1.0"
description = "Incident Response Mesh Monorepo"
requires-python = ">=3.12"
dependencies = [
    "config",
]

[tool.uv.sources]
config = { workspace = true }

[dependency-groups]
dev = [
    "pip-audit>=2.7.0",
    "pyyaml>=6.0",
]

[tool.uv.workspace]
members = [
    "libs/*",
    "services/*",
    "agents/*",
    "mcp/*"
]
```

- [x] **Step 5: Call `load_settings` at the top of `security-audit.py`'s `main()`**

```python
# scripts/security-audit.py
# Add near the top imports:
from config.settings import load_settings


def main() -> int:
    """CLI entrypoint."""
    load_settings("security-audit")

    parser = argparse.ArgumentParser(
        description="Security Audit Wrapper (pip-audit + trivy)"
    )
    # ... rest of function unchanged
```

- [x] **Step 6: Run root and security-audit tests to confirm no regression**

Run: `uv sync && uv run pytest tests/test_security_audit.py -v`
Expected: PASS — `tests/test_security_audit.py` never calls `main()` directly (it tests individual functions via `importlib`), so this is unaffected; run it to confirm.

- [x] **Step 7: Commit**

```bash
git add services/scenario-runner scripts/security-audit.py pyproject.toml uv.lock
git commit -m "feat(config): wire scenario-runner and security-audit.py to load_settings()"
```

---

### Task 11: Wire CI to test `libs/config` and exercise the `ci.env` overlay

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:** None (CI configuration only).

- [x] **Step 1: Add a `libs_config` path filter and extend dependent filters**

```yaml
# .github/workflows/ci.yml — inside the `filters:` block under `detect-changes`
          filters: |
            libs_adapters:
              - 'libs/adapters/**'
              - 'libs/config/**'
              - 'pyproject.toml'
              - 'uv.lock'
            libs_config:
              - 'libs/config/**'
              - 'pyproject.toml'
              - 'uv.lock'
            libs_core:
              - 'libs/core/**'
              - 'pyproject.toml'
              - 'uv.lock'
            services_hello_world:
              - 'services/hello-world/**'
              - 'libs/config/**'
              - 'pyproject.toml'
              - 'uv.lock'
            services_scenario_runner:
              - 'services/scenario-runner/**'
              - 'libs/config/**'
              - 'pyproject.toml'
              - 'uv.lock'
            security:
              - 'uv.lock'
              - 'infra/**'
              - 'security-suppressions.yaml'
```

- [x] **Step 2: Set `APP_ENV=ci` for the test job so the `ci.env` overlay is exercised**

```yaml
# .github/workflows/ci.yml — inside the `test` job's steps
      - name: Test
        working-directory: ${{ env.PKG_PATH }}
        env:
          APP_ENV: ci
        run: uv run pytest --cov=. --cov-fail-under=80
```

- [x] **Step 3: Verify the workflow YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: No output (no exception raised) — confirms valid YAML syntax.

- [x] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: test libs/config and exercise the ci.env overlay via APP_ENV"
```

---

### Task 12: Run the full workspace test suite and fix any fallout

**Files:** None planned — this task only touches files if a regression surfaces.

**Interfaces:** None.

- [x] **Step 1: Sync every workspace member**

Run: `uv sync --all-extras`
Expected: Resolves cleanly with `config`, `ports-testing` (now a runtime dep of `adapters`), and `pydantic-settings` all present in `uv.lock`.

- [x] **Step 2: Run each affected package's test suite**

Run, from repo root, with `docker-compose up -d redis postgres` already running:
```bash
(cd libs/config && uv run pytest -v)
(cd libs/adapters && uv run pytest -v)
(cd services/hello-world && uv run pytest -v)
(cd services/scenario-runner && uv run pytest -v)
uv run pytest tests/test_security_audit.py -v
```
Expected: All PASS.

- [x] **Step 3: Run `make config-docs` once more and confirm `docs/config.md` is current**

Run: `make config-docs && git diff --stat docs/config.md`
Expected: No diff (or only the expected additions from earlier tasks — regenerate and re-commit if the schema changed since Task 6).

- [x] **Step 4: Lint and typecheck every touched package**

Run:
```bash
(cd libs/config && uv run ruff check . && uv run ruff format --check . && uv run mypy . --strict)
(cd libs/adapters && uv run ruff check . && uv run ruff format --check . && uv run mypy . --strict)
(cd services/hello-world && uv run ruff check . && uv run ruff format --check . && uv run mypy . --strict)
(cd services/scenario-runner && uv run ruff check . && uv run ruff format --check .)
```
Expected: Clean (fix any findings inline before proceeding).

- [x] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: address lint/type findings from typed config migration"
```

(Skip this step entirely if Step 4 found nothing to fix.)
