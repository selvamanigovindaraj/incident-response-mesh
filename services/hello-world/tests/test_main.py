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
