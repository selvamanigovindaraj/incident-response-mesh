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
