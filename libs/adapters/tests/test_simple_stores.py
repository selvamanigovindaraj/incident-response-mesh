from pathlib import Path

import pytest
from adapters.env_secret_store import EnvSecretStore
from adapters.fs_blob_store import FsBlobStore
from ports_testing.contracts.stores import (
    SecretStoreConfig,
    test_blob_store_content_addressing,  # noqa: F401
    test_blob_store_delete_is_idempotent,  # noqa: F401
    test_blob_store_get_nonexistent_raises,  # noqa: F401
    test_blob_store_list_prefix_and_lexicographical_ordering,  # noqa: F401
    test_blob_store_overwrite,  # noqa: F401
    test_blob_store_put_and_get,  # noqa: F401
    test_secret_store_get_existing,  # noqa: F401
    test_secret_store_get_nonexistent_raises,  # noqa: F401
)


@pytest.fixture
def secret_store() -> EnvSecretStore:
    return EnvSecretStore()


@pytest.fixture(autouse=True)
def setup_env_secrets(
    monkeypatch: pytest.MonkeyPatch,
    secret_store_config: SecretStoreConfig,
) -> None:
    # Seed the known secret in environment so the contract test can find it
    monkeypatch.setenv(secret_store_config.known_key, secret_store_config.known_value)


@pytest.fixture
def secret_store_config() -> SecretStoreConfig:
    return SecretStoreConfig()


@pytest.fixture
def blob_store(tmp_path: Path) -> FsBlobStore:
    return FsBlobStore(base_dir=tmp_path)


@pytest.mark.asyncio
async def test_fs_blob_store_directory_key_raises_key_error(
    blob_store: FsBlobStore,
) -> None:
    # Querying empty key or directory must raise KeyError instead of IsADirectoryError
    with pytest.raises(KeyError):
        await blob_store.get("")

    with pytest.raises(KeyError):
        await blob_store.get(".")

    # Create a nested file so parent directory exists
    await blob_store.put("subdir/file.bin", b"test-data")
    with pytest.raises(KeyError):
        await blob_store.get("subdir")


@pytest.mark.asyncio
async def test_fs_blob_store_delete_directory_is_idempotent_noop(
    blob_store: FsBlobStore,
) -> None:
    # Deleting empty key or existing directory must be a no-op, not raise IsADirectoryError
    await blob_store.put("subdir/file.bin", b"test-data")
    await blob_store.delete("")
    await blob_store.delete(".")
    await blob_store.delete("subdir")
    # File inside directory should still exist
    assert await blob_store.get("subdir/file.bin") == b"test-data"


@pytest.mark.asyncio
async def test_fs_blob_store_leading_slash_keys(blob_store: FsBlobStore) -> None:
    # Keys with leading slashes should resolve inside base_dir
    key = "/leading/slash/blob.txt"
    await blob_store.put(key, b"slash-content")
    assert await blob_store.get(key) == b"slash-content"
    # Leading slash key resolves to relative path inside base_dir
    assert await blob_store.get("leading/slash/blob.txt") == b"slash-content"

    await blob_store.delete(key)
    with pytest.raises(KeyError):
        await blob_store.get(key)


@pytest.mark.asyncio
async def test_fs_blob_store_path_traversal_prevention(blob_store: FsBlobStore) -> None:
    with pytest.raises(ValueError, match="outside of base directory"):
        await blob_store.put("../escaped.txt", b"malicious")

    with pytest.raises(ValueError, match="outside of base directory"):
        await blob_store.get("../escaped.txt")


@pytest.mark.asyncio
async def test_fs_blob_store_list_directory_pruning(blob_store: FsBlobStore) -> None:
    await blob_store.put("alpha/1.txt", b"a1")
    await blob_store.put("alpha/2.txt", b"a2")
    await blob_store.put("beta/1.txt", b"b1")
    await blob_store.put("gamma/sub/1.txt", b"g1")

    # List with prefix starting in alpha/
    alpha_keys = [k async for k in blob_store.list("alpha/")]
    assert alpha_keys == ["alpha/1.txt", "alpha/2.txt"]

    # List with prefix matching sub-directory
    gamma_keys = [k async for k in blob_store.list("gamma/sub/")]
    assert gamma_keys == ["gamma/sub/1.txt"]

    # List with nonexistent prefix returns empty
    none_keys = [k async for k in blob_store.list("nonexistent/")]
    assert none_keys == []
