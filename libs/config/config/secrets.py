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
