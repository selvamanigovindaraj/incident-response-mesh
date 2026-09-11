# Typed Configuration System Design

## Overview

Introduces a single typed configuration system, `libs/config`, so every
service declares its config schema up front and adapters are selected by
config value, not by code branching. It builds directly on the 1.5
`AdapterRegistry` (`libs/adapters`) and the port protocols in `libs/ports`,
and replaces the registry's untyped `Mapping[str, Any]` config with a
validated `AppSettings` model.

## Package Structure

* **Location:** `libs/config` (new workspace member).
* **Dependencies:** `pydantic-settings`, and `ports` (only for the
  `SecretStore` protocol type used by `SecretRef.resolve`). `libs/config`
  performs no I/O itself — it is pure schema and validation.
* **Dependency direction:** `ports` -> `config` -> `adapters` -> `services/*`.
* **Layout:**
  ```
  libs/config/
    config/
      __init__.py
      settings.py   # AppSettings + subsystem models + load_settings()
      secrets.py    # SecretRef
      docs.py       # schema -> Markdown dumper for `make config-docs`
    tests/
    pyproject.toml
  ```

## Settings Schema

`AppSettings(BaseSettings)` is the single root every service instantiates
via `load_settings(service_name: str) -> AppSettings`:

```python
class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=_select_env_file(),  # from APP_ENV
        extra="forbid",
    )

    app_env: Literal["local", "ci", "cluster"] = "local"
    service_name: str

    queue: QueueSettings
    locks: LocksSettings
    blob_store: BlobStoreSettings
    postgres: PostgresSettings
    llm: LLMSettings
    observability: ObservabilitySettings
```

Each subsystem is an independent `BaseModel`, e.g.:

```python
class QueueSettings(BaseModel):
    backend: Literal["redis", "memory"] = "memory"
    redis_url: str | None = None
    max_deliveries: int = 3

    @model_validator(mode="after")
    def _require_redis_url_when_redis(self) -> "QueueSettings":
        if self.backend == "redis" and not self.redis_url:
            raise ValueError("queue.redis_url is required when queue.backend == 'redis'")
        return self

class LocksSettings(BaseModel):
    backend: Literal["redis", "memory"] = "memory"
    redis_url: str | None = None

class BlobStoreSettings(BaseModel):
    base_dir: str = "/tmp/blobs"

class PostgresSettings(BaseModel):
    dsn: SecretRef | None = None

class LLMSettings(BaseModel):
    provider: str | None = None

class ObservabilitySettings(BaseModel):
    otlp_endpoint: str | None = None
```

`llm` and `observability` are schema scaffolding only — no adapter consumes
them yet (out of scope), but their shape exists now so future work can add
fields without a breaking schema change.

Env vars use the nested delimiter, e.g. `QUEUE__BACKEND=redis`,
`QUEUE__REDIS_URL=redis://localhost:6379/0`. Cross-field requirements (e.g.
`redis_url` required when `backend == "redis"`) are enforced via
`model_validator(mode="after")` on the relevant subsystem model, so a single
`ValidationError` on boot can report multiple invalid/missing fields at once.

## Secret Handling — `SecretRef`

```python
class SecretRef:
    def __init__(self, key: str) -> None:
        self._key = key

    def __repr__(self) -> str:
        return f"SecretRef({self._key!r}, value=***)"

    __str__ = __repr__

    async def resolve(self, store: SecretStore) -> str:
        return await store.get(self._key)
```

* A config field typed `SecretRef` accepts a **plain string key** from
  env/`.env` (e.g. `POSTGRES__DSN=irm/postgres/dsn`); pydantic validates the
  string is non-empty and wraps it as `SecretRef(key=...)`. No plaintext
  secret value ever enters a `Settings` instance.
* Resolution is lazy: `AdapterRegistry.start()` calls
  `await settings.postgres.dsn.resolve(secret_store)` immediately before
  opening the connection that needs it, using whatever `SecretStore` the
  registry already holds (`EnvSecretStore` today).
* Because pydantic's default model repr recurses into nested fields,
  `repr(app_settings)` and any logger that reprs the settings object never
  exposes a resolved value — only the masked `SecretRef(...)` marker. This
  is what the redaction test asserts.

## Adapter Selection via the Registry

`AdapterRegistry.__init__` changes signature from `Mapping[str, Any]` to
`AppSettings`. Per scope, only `queue` and `locks` get backend switching in
this PR:

```python
def get_queue(self, key: str = "default") -> Queue:
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
```

Same pattern for `get_lock_service` against `settings.locks.backend`.
`blob_store`, `postgres` (audit sink), and `secret_store` keep their current
single-backend behavior — no `*_BACKEND` switch for those in this PR.

`start()` only opens a Redis client if `queue.backend == "redis"` or
`locks.backend == "redis"`, and only opens a Postgres pool if
`postgres.dsn is not None` (resolving the `SecretRef` at that point).

**Runtime dependency change:** `libs/ports-testing`'s `InMemoryQueue` and
`InMemoryLockService` move from a dev-only dependency of `libs/adapters` to
a normal runtime dependency, since `QUEUE__BACKEND=memory` /
`LOCKS__BACKEND=memory` must work in production code paths, not just tests.
`ports-testing`'s `pyproject.toml` dependency group in `adapters` moves from
`[dependency-groups].dev` to `[project].dependencies`.

## Env Overlay Files

* Files live at `config/env/local.env`, `config/env/ci.env`,
  `config/env/cluster.env` (new top-level `config/` directory, distinct from
  the `libs/config` package).
* `APP_ENV` (a real process environment variable, default `"local"`) is read
  by `_select_env_file()` in `settings.py` to pick which file
  `SettingsConfigDict(env_file=...)` points at.
* Precedence follows pydantic-settings' default source order: **real
  environment variables > selected `.env` file > model defaults**. No custom
  merge logic — this is the built-in behavior once `env_file` is set
  correctly.

## Startup Validation

* `load_settings(service_name: str) -> AppSettings` in `libs/config` wraps
  `AppSettings(service_name=service_name)` construction.
* On `pydantic.ValidationError`, it prints one line per invalid/missing
  field (`field.path: message`) to stderr and raises `SystemExit(1)`.
* `services/hello-world/hello_world/main.py` becomes the reference
  implementation: `main()` calls `load_settings("hello-world")` before doing
  anything else, so a missing required var makes the service exit non-zero
  with the field named — directly satisfying the acceptance criterion.

## `make config-docs`

* `config/docs.py` walks `AppSettings.model_json_schema()` and renders one
  Markdown section per subsystem: field name, type, default, required?, and
  description (from `Field(description=...)` where present).
* Output is written to `docs/config.md`, committed like any other doc (no
  dynamic generation at runtime).
* `Makefile` target:
  ```
  .PHONY: config-docs
  config-docs:
  	cd libs/config && uv run python -m config.docs > ../../docs/config.md
  ```

## Migration (Definition of Done)

* **`libs/adapters`:** `AdapterRegistry` retyped to take `AppSettings`;
  `test_registry.py` and `conftest.py` updated to build `AppSettings`
  instances instead of raw dicts / direct `os.environ` reads.
* **`services/hello-world`:** calls `load_settings("hello-world")` at
  startup (new behavior — today it does nothing).
* **`services/scenario-runner`, `scripts/security-audit.py`:** add a
  `libs/config` dependency and construct `AppSettings` at their entrypoints
  for consistency, even though neither branches on any field yet (they have
  no existing env-var reads to migrate).
* **CI (`ci.yml`):** any workflow steps starting `hello-world` or adapter
  integration tests set `APP_ENV=ci` so the `ci.env` overlay is exercised.

## Testing

* **`libs/config` unit tests:** missing required field exits non-zero with
  the field path named; `SecretRef.__repr__`/`__str__` never contain a
  resolved value; `.env` overlay selection changes with `APP_ENV`; cross-field
  validators reject `backend="redis"` with no `redis_url`.
* **`libs/adapters` integration test:** boot `AdapterRegistry` twice — once
  with `QUEUE__BACKEND=memory`, once with `QUEUE__BACKEND=redis` (against the
  docker-compose Redis) — publish and consume a message both ways, asserting
  identical behavior against the `Queue` protocol. Same for `locks`.

## Out of Scope (reaffirmed)

* Dynamic/hot config reload.
* Feature flags (separate, later effort).
* Backend switching for `blob_store`, `postgres` (audit sink), or
  `secret_store` — only `queue` and `locks` get a `*_BACKEND`-style switch
  in this PR.
