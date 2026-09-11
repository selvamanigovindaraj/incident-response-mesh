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
