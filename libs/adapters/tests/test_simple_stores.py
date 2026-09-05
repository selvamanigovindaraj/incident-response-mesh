# ruff: noqa: F401
import os
from pathlib import Path
from typing import Any

import pytest
from adapters.env_secret_store import EnvSecretStore
from adapters.fs_blob_store import FsBlobStore
from ports_testing.contracts.stores import (
    BlobStoreConfig,
    SecretStoreConfig,
    test_blob_store_content_addressing,
    test_blob_store_delete_is_idempotent,
    test_blob_store_get_nonexistent_raises,
    test_blob_store_list_prefix_and_lexicographical_ordering,
    test_blob_store_overwrite,
    test_blob_store_put_and_get,
    test_secret_store_get_existing,
    test_secret_store_get_nonexistent_raises,
)


@pytest.fixture
def secret_store() -> EnvSecretStore:
    return EnvSecretStore()


@pytest.fixture(autouse=True)
def setup_env_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Seed the known secret in environment so the contract test can find it
    config = SecretStoreConfig()
    monkeypatch.setenv(config.known_key, config.known_value)


@pytest.fixture
def secret_store_config() -> SecretStoreConfig:
    return SecretStoreConfig()


@pytest.fixture
def blob_store(tmp_path: Path) -> FsBlobStore:
    return FsBlobStore(base_dir=tmp_path)
