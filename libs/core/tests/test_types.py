from core.types import get_status


def test_get_status():
    assert get_status() == 200
