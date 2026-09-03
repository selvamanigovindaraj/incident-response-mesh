"""
Pytest contract test suite for LockService port implementations.

Downstream adapters should verify conformance by defining a `lock_service` fixture
(and optionally a `lock_config` fixture) and importing this suite:

    from ports_testing.contracts.lock import *
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from ports.interfaces import LockService
from ports.types import Lease

from ports_testing.fakes import LockError


@dataclass(frozen=True)
class LockConfig:
    """
    Configuration parameters for tuning lock service contract tests.
    """

    ttl: float = 0.2
    contenders_count: int = 20


@pytest.fixture
def lock_config() -> LockConfig:
    """
    Default lock configuration fixture. Adapters may override this fixture
    to adjust timing thresholds or concurrency parameters.
    """
    return LockConfig()


def _get_config(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


@pytest.mark.asyncio
async def test_lock_concurrency_twenty_contenders(
    lock_service: LockService, lock_config: Any = None
) -> None:
    """
    Contract: When multiple contenders concurrently attempt to acquire a lock
    on the same resource, exactly one contender succeeds and all others fail.
    """
    contenders = int(_get_config(lock_config, "contenders_count", 20))
    resource = "contract-contended-resource"

    results = await asyncio.gather(
        *[lock_service.acquire(resource, ttl=10) for _ in range(contenders)],
        return_exceptions=True,
    )

    leases = [r for r in results if isinstance(r, Lease)]
    exceptions = [r for r in results if isinstance(r, Exception)]

    assert len(leases) == 1, (
        f"Expected exactly 1 contender to acquire lock, but {len(leases)} succeeded."
    )
    assert len(exceptions) == contenders - 1, (
        f"Expected {contenders - 1} contenders to fail, but got {len(exceptions)} exceptions."
    )

    winner_lease = leases[0]
    assert winner_lease.token, "Acquired lease must contain a non-empty token"
    assert winner_lease.fence >= 1, "Acquired lease must have a positive fencing token"

    # Clean up
    await lock_service.release(winner_lease)


@pytest.mark.asyncio
async def test_lock_ttl_expiration_allows_takeover(
    lock_service: LockService, lock_config: Any = None
) -> None:
    """
    Contract: If a lease is not renewed before its TTL expires, the lock expires
    and a new contender can immediately acquire it with an increased fencing token.
    """
    ttl = float(_get_config(lock_config, "ttl", 0.2))
    resource = "contract-ttl-takeover-resource"

    lease1 = await lock_service.acquire(resource, ttl=cast(int, ttl))
    assert lease1.token
    assert lease1.fence >= 1

    # Wait for the initial lease TTL to elapse
    await asyncio.sleep(ttl + 0.15)

    # A second contender must now be able to take over the lock
    lease2 = await lock_service.acquire(resource, ttl=10)
    assert lease2.token
    assert lease2.fence > lease1.fence, (
        f"Takeover lease fence ({lease2.fence}) must be greater than original fence ({lease1.fence})"
    )

    # Clean up
    await lock_service.release(lease2)


@pytest.mark.asyncio
async def test_lock_renew_successfully_extends_ttl(
    lock_service: LockService, lock_config: Any = None
) -> None:
    """
    Contract: Calling renew() on an active lease successfully extends its validity
    window, preventing other contenders from acquiring the lock past the initial TTL.
    """
    ttl = float(_get_config(lock_config, "ttl", 0.25))
    resource = "contract-renew-resource"

    lease = await lock_service.acquire(resource, ttl=cast(int, ttl))

    # Sleep partway through TTL
    await asyncio.sleep(ttl * 0.4)

    # Renew the lease to extend expiration window
    await lock_service.renew(lease)

    # Sleep past the original expiration time
    await asyncio.sleep(ttl * 0.7)

    # The lock must STILL be held; another contender must fail to acquire
    with pytest.raises((LockError, TimeoutError, RuntimeError)):
        await lock_service.acquire(resource, ttl=cast(int, ttl))

    # Releasing the renewed lease frees the lock
    await lock_service.release(lease)

    # Now a new contender can acquire the lock
    new_lease = await lock_service.acquire(resource, ttl=cast(int, ttl))
    assert new_lease.fence > lease.fence
    await lock_service.release(new_lease)


@pytest.mark.asyncio
async def test_lock_fencing_tokens_are_strictly_monotonic(
    lock_service: LockService, lock_config: Any = None
) -> None:
    """
    Contract: Each successive lease granted for a resource must have a strictly
    monotonically increasing fencing token to prevent stale writer race conditions.
    """
    resource = "contract-monotonic-resource"
    fences: list[int] = []

    for _ in range(5):
        lease = await lock_service.acquire(resource, ttl=10)
        fences.append(lease.fence)
        await lock_service.release(lease)

    assert len(fences) == 5
    assert all(isinstance(f, int) for f in fences), (
        "All fencing tokens must be integers"
    )
    assert all(fences[i] < fences[i + 1] for i in range(len(fences) - 1)), (
        f"Fencing tokens are not strictly monotonically increasing: {fences}"
    )


@pytest.mark.asyncio
async def test_lock_stale_lease_release_noop(
    lock_service: LockService, lock_config: Any = None
) -> None:
    """
    Contract: Releasing a phantom, expired, or superseded lease must be safe,
    idempotent, and not crash (no-op). It must not invalidate an active lease
    held by a subsequent contender.
    """
    # 1. Phantom lease release must not crash
    phantom_lease = Lease(token="phantom-token-00000", fence=99999)
    await lock_service.release(phantom_lease)

    # 2. Releasing an expired lease must not release a newly acquired lease
    ttl = float(_get_config(lock_config, "ttl", 0.1))
    resource = "contract-stale-release-resource"

    expired_lease = await lock_service.acquire(resource, ttl=cast(int, ttl))
    await asyncio.sleep(ttl + 0.15)

    # New contender acquires after expiration
    active_lease = await lock_service.acquire(resource, ttl=10)

    # Releasing the expired lease must be a safe no-op
    await lock_service.release(expired_lease)

    # The active lease must STILL be valid and held
    with pytest.raises((LockError, TimeoutError, RuntimeError)):
        await lock_service.acquire(resource, ttl=10)

    # Clean up active lease
    await lock_service.release(active_lease)


__all__ = [
    "LockConfig",
    "lock_config",
    "test_lock_concurrency_twenty_contenders",
    "test_lock_fencing_tokens_are_strictly_monotonic",
    "test_lock_renew_successfully_extends_ttl",
    "test_lock_stale_lease_release_noop",
    "test_lock_ttl_expiration_allows_takeover",
]
