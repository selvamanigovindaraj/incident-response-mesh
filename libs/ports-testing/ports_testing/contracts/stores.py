"""
Pytest contract test suite for BlobStore, SecretStore, and AuditSink port implementations.

Downstream adapters should verify conformance by defining `blob_store`, `secret_store`,
and/or `audit_sink` fixtures (and optionally `secret_store_config`) and importing this suite:

    from ports_testing.contracts.stores import *
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

import pytest
from ports.interfaces import AuditSink, BlobStore, SecretStore


@dataclass(frozen=True)
class BlobStoreConfig:
    """
    Configuration parameters for tuning blob store contract tests.
    """

    expected_not_found_error: type[Exception] | tuple[type[Exception], ...] = (
        KeyError,
        FileNotFoundError,
        LookupError,
        RuntimeError,
    )


@pytest.fixture
def blob_store_config() -> BlobStoreConfig:
    """
    Default blob store configuration fixture. Adapters may override this fixture
    to specify adapter-specific error types for missing keys.
    """
    return BlobStoreConfig()


@dataclass(frozen=True)
class SecretStoreConfig:
    """
    Configuration parameters for tuning secret store contract tests.
    """

    known_key: str = "contract-test-secret"
    known_value: str = "super-secret-contract-token"
    missing_key: str = "nonexistent-secret-key-99999"
    expected_error: type[Exception] | tuple[type[Exception], ...] = (
        KeyError,
        LookupError,
        RuntimeError,
    )


@pytest.fixture
def secret_store_config() -> SecretStoreConfig:
    """
    Default secret store configuration fixture. Adapters may override this fixture
    to point to seeded credentials in external secret managers.
    """
    return SecretStoreConfig()


def _get_config(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


# ============================================================================
# BlobStore Contracts
# ============================================================================


@pytest.mark.asyncio
async def test_blob_store_put_and_get(blob_store: BlobStore) -> None:
    """
    Contract: Data stored with put() is durably retrieved by get() with exact
    binary equality.
    """
    key = "contract-blobs/standard-artifact.bin"
    payload = b"\x00\x01\x02\xffbinary-data-content\xfe"

    try:
        stored_key = await blob_store.put(key, payload)
        assert stored_key == key, f"Expected put to return key '{key}', got '{stored_key}'"

        retrieved = await blob_store.get(key)
        assert retrieved == payload, "Retrieved blob bytes did not match original data"
    finally:
        # Clean up
        await blob_store.delete(key)


@pytest.mark.asyncio
async def test_blob_store_get_nonexistent_raises(
    blob_store: BlobStore, blob_store_config: Any = None
) -> None:
    """
    Contract: Attempting to retrieve a nonexistent or deleted blob raises an expected error.
    """
    expected_error = _get_config(
        blob_store_config,
        "expected_not_found_error",
        (KeyError, FileNotFoundError, LookupError, RuntimeError),
    )
    missing_key = "contract-blobs/nonexistent-blob-99999.bin"
    with pytest.raises(expected_error):
        await blob_store.get(missing_key)


@pytest.mark.asyncio
async def test_blob_store_overwrite(blob_store: BlobStore) -> None:
    """
    Contract: Overwriting an existing blob key updates its contents with strong consistency.
    """
    key = "contract-blobs/overwrite-target.bin"
    initial_data = b"initial-version-data"
    updated_data = b"updated-version-data-v2"

    try:
        await blob_store.put(key, initial_data)
        assert await blob_store.get(key) == initial_data

        await blob_store.put(key, updated_data)
        assert await blob_store.get(key) == updated_data
    finally:
        # Clean up
        await blob_store.delete(key)


@pytest.mark.asyncio
async def test_blob_store_delete_is_idempotent(
    blob_store: BlobStore, blob_store_config: Any = None
) -> None:
    """
    Contract: Deleting a blob removes it permanently so subsequent get() calls raise.
    Calling delete() again or deleting a nonexistent key must succeed idempotently (no-op).
    """
    expected_error = _get_config(
        blob_store_config,
        "expected_not_found_error",
        (KeyError, FileNotFoundError, LookupError, RuntimeError),
    )
    key = "contract-blobs/delete-target.bin"
    data = b"ephemeral-data"

    try:
        await blob_store.put(key, data)
        assert await blob_store.get(key) == data

        # Delete existing blob
        await blob_store.delete(key)

        # Retrieval must fail
        with pytest.raises(expected_error):
            await blob_store.get(key)

        # Deleting an already-deleted key must not crash
        await blob_store.delete(key)

        # Deleting an never-existent key must not crash
        await blob_store.delete("contract-blobs/never-existed.bin")
    finally:
        await blob_store.delete(key)


@pytest.mark.asyncio
async def test_blob_store_content_addressing(blob_store: BlobStore) -> None:
    """
    Contract: When content_addressing=True, put() derives the key deterministically
    from the content hash and safely ignores duplicate writes.
    """
    data1 = b"deterministic-content-addressed-payload-alpha"
    data2 = b"deterministic-content-addressed-payload-beta"
    expected_digest1 = hashlib.sha256(data1).hexdigest()
    key1: str | None = None
    key2: str | None = None

    try:
        # Store with content addressing
        key1 = await blob_store.put("blobs/cas", data1, content_addressing=True)
        assert expected_digest1 in key1, (
            f"Content-addressed key '{key1}' should incorporate content digest '{expected_digest1}'"
        )

        # Re-putting identical content should return the same key
        key1_repeat = await blob_store.put("blobs/cas", data1, content_addressing=True)
        assert key1 == key1_repeat, (
            f"Duplicate content write returned different key: {key1} vs {key1_repeat}"
        )

        # Putting different content must return a different key
        key2 = await blob_store.put("blobs/cas", data2, content_addressing=True)
        assert key1 != key2, "Different contents produced identical content-addressed keys"

        # Both keys can be retrieved
        assert await blob_store.get(key1) == data1
        assert await blob_store.get(key2) == data2
    finally:
        # Clean up
        if key1:
            await blob_store.delete(key1)
        if key2:
            await blob_store.delete(key2)


@pytest.mark.asyncio
async def test_blob_store_list_prefix_and_lexicographical_ordering(
    blob_store: BlobStore,
) -> None:
    """
    Contract: list(prefix) streams keys matching the prefix in lexicographical order,
    filtering out non-matching keys.
    """
    prefix = "contract-list-test/"
    keys_to_create = [
        f"{prefix}c-file.txt",
        f"{prefix}a-file.txt",
        f"{prefix}b-file.txt",
        "contract-other-dir/z-file.txt",
    ]

    try:
        for k in keys_to_create:
            await blob_store.put(k, b"sample-bytes")

        matching_keys: list[str] = []
        async for item in blob_store.list(prefix):
            matching_keys.append(item)

        expected_keys = [
            f"{prefix}a-file.txt",
            f"{prefix}b-file.txt",
            f"{prefix}c-file.txt",
        ]

        assert matching_keys == expected_keys, (
            f"Expected lexicographical list {expected_keys}, got {matching_keys}"
        )
        assert all(k.startswith(prefix) for k in matching_keys), (
            f"Found key not matching prefix '{prefix}': {matching_keys}"
        )
    finally:
        for k in keys_to_create:
            await blob_store.delete(k)


# ============================================================================
# SecretStore Contracts
# ============================================================================


@pytest.mark.asyncio
async def test_secret_store_get_existing(
    secret_store: SecretStore, secret_store_config: Any = None
) -> None:
    """
    Contract: get() retrieves the plaintext secret string for a valid key.
    """
    known_key = str(
        _get_config(secret_store_config, "known_key", "contract-test-secret")
    )
    known_value = str(
        _get_config(secret_store_config, "known_value", "super-secret-contract-token")
    )

    # If the store supports writing secrets (e.g. in-memory fake), seed if missing
    if hasattr(secret_store, "set") and callable(secret_store.set):
        await secret_store.set(known_key, known_value)

    retrieved = await secret_store.get(known_key)
    assert isinstance(retrieved, str), f"Secret must be a string, got {type(retrieved)}"
    assert retrieved == known_value, (
        f"Secret value mismatch: expected '{known_value}', got '{retrieved}'"
    )


@pytest.mark.asyncio
async def test_secret_store_get_nonexistent_raises(
    secret_store: SecretStore, secret_store_config: Any = None
) -> None:
    """
    Contract: get() raises an expected error on nonexistent keys.
    """
    expected_error = _get_config(
        secret_store_config,
        "expected_error",
        (KeyError, LookupError, RuntimeError),
    )
    missing_key = str(
        _get_config(secret_store_config, "missing_key", "nonexistent-secret-key-99999")
    )
    with pytest.raises(expected_error):
        await secret_store.get(missing_key)


# ============================================================================
# AuditSink Contracts
# ============================================================================


@pytest.mark.asyncio
async def test_audit_sink_append_returns_monotonically_increasing_sequence(
    audit_sink: AuditSink,
) -> None:
    """
    Contract: Each event appended to AuditSink returns a strictly monotonically
    increasing sequence number.
    """
    seqs: list[int] = []
    for i in range(5):
        event = {"event_id": f"evt-{i}", "action": "user_action", "index": i}
        seq = await audit_sink.append(event)
        seqs.append(seq)

    assert len(seqs) == 5
    assert all(isinstance(s, int) for s in seqs), (
        "All sequence numbers must be integers"
    )
    assert all(seqs[i] < seqs[i + 1] for i in range(len(seqs) - 1)), (
        f"Sequence numbers are not strictly monotonically increasing: {seqs}"
    )


@pytest.mark.asyncio
async def test_audit_sink_concurrent_appends_have_unique_monotonic_sequences(
    audit_sink: AuditSink,
) -> None:
    """
    Contract: Concurrent appends to AuditSink all receive distinct, unique sequence numbers.
    """
    num_events = 20
    tasks = [
        audit_sink.append({"concurrent_id": i, "timestamp": "2026-09-03T12:00:00Z"})
        for i in range(num_events)
    ]
    sequences = await asyncio.gather(*tasks)

    assert len(sequences) == num_events
    assert all(isinstance(s, int) for s in sequences)
    unique_sequences = set(sequences)
    assert len(unique_sequences) == num_events, (
        f"Collision detected in concurrent sequence numbers: {sequences}"
    )


@pytest.mark.asyncio
async def test_audit_sink_payload_immutability_caller_mutation(
    audit_sink: AuditSink,
) -> None:
    """
    Contract: Mutating the caller's event dictionary after append() must not tamper with
    or alter the recorded audit event (ledger immutability).
    """
    original_event = {
        "event_id": "audit-tamper-check-001",
        "actor": "legitimate_service",
        "details": {"role": "operator", "authenticated": True},
    }

    seq = await audit_sink.append(original_event)
    assert isinstance(seq, int)

    # Caller mutates their dictionary in-place
    original_event["actor"] = "malicious_hacker"
    original_event["details"]["role"] = "superadmin"  # type: ignore[index]

    # If sink provides event inspection (like in-memory fake or verifiable ledger)
    if hasattr(audit_sink, "get_events") and callable(audit_sink.get_events):
        recorded_events = audit_sink.get_events()
        stored = next(
            (
                e
                for e in recorded_events
                if e.get("event_id") == "audit-tamper-check-001"
            ),
            None,
        )
        assert stored is not None, "Appended event was not recorded"
        assert stored["actor"] == "legitimate_service", (
            f"Audit sink allowed in-place caller mutation: {stored['actor']}"
        )
        assert stored["details"]["role"] == "operator", (
            f"Audit sink allowed nested caller mutation: {stored['details']}"
        )
    elif hasattr(audit_sink, "read_events") and callable(audit_sink.read_events):
        res = audit_sink.read_events()
        recorded_events = await res if asyncio.iscoroutine(res) else res
        stored = next(
            (
                e
                for e in recorded_events
                if e.get("event_id") == "audit-tamper-check-001"
            ),
            None,
        )
        assert stored is not None, "Appended event was not recorded"
        assert stored["actor"] == "legitimate_service", (
            f"Audit sink allowed in-place caller mutation: {stored['actor']}"
        )
        assert stored["details"]["role"] == "operator", (
            f"Audit sink allowed nested caller mutation: {stored['details']}"
        )
    else:
        pytest.skip("No event_reader or inspection method provided for immutability verification")


__all__ = [
    "BlobStoreConfig",
    "SecretStoreConfig",
    "blob_store_config",
    "secret_store_config",
    "test_audit_sink_append_returns_monotonically_increasing_sequence",
    "test_audit_sink_concurrent_appends_have_unique_monotonic_sequences",
    "test_audit_sink_payload_immutability_caller_mutation",
    "test_blob_store_content_addressing",
    "test_blob_store_delete_is_idempotent",
    "test_blob_store_get_nonexistent_raises",
    "test_blob_store_list_prefix_and_lexicographical_ordering",
    "test_blob_store_overwrite",
    "test_blob_store_put_and_get",
    "test_secret_store_get_existing",
    "test_secret_store_get_nonexistent_raises",
]
