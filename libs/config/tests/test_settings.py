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
