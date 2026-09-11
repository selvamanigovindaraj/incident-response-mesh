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
