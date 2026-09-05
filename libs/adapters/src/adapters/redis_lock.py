import uuid
from typing import ClassVar

from ports.interfaces import LockService
from ports.types import Lease
from redis.asyncio import Redis


class LockError(Exception):
    pass

class RedisLockService(LockService):
    """
    Redis implementation of the LockService port.
    Uses SET NX PX for mutual exclusion and INCR for strictly monotonic fencing tokens.
    Release and renew use atomic Lua scripts to prevent stale token invalidation.
    """
    
    # Lua script to safely renew a lease if and only if we still hold it with the same token
    RENEW_SCRIPT: ClassVar[str] = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("PEXPIRE", KEYS[1], ARGV[2])
    else
        return 0
    end
    """
    
    # Lua script to safely release a lease if and only if we still hold it with the same token
    RELEASE_SCRIPT: ClassVar[str] = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client
        # Pre-load scripts if needed, but we can also use EVAL directly or register script
        self._renew_script = self._redis.register_script(self.RENEW_SCRIPT)
        self._release_script = self._redis.register_script(self.RELEASE_SCRIPT)

    def _lock_key(self, resource: str) -> str:
        return f"lock:{resource}"

    def _fence_key(self, resource: str) -> str:
        return f"fence:{resource}"

    def _encode_token(self, resource: str, ttl: float, uid: str) -> str:
        # Format: ttl:uid:resource
        return f"{ttl}:{uid}:{resource}"

    def _decode_token(self, token: str) -> tuple[str, float, str]:
        parts = token.split(":", 2)
        if len(parts) != 3:
            raise ValueError("Invalid token format")
        ttl_str, uid, resource = parts
        return resource, float(ttl_str), uid

    async def acquire(self, resource: str, ttl: float) -> Lease:
        uid = str(uuid.uuid4())
        token = self._encode_token(resource, ttl, uid)
        
        key = self._lock_key(resource)
        px = int(ttl * 1000)
        
        # Attempt to acquire the lock
        acquired = await self._redis.set(key, token, nx=True, px=px)
        if not acquired:
            raise LockError(f"Failed to acquire lock for resource: {resource}")
            
        # Get fencing token
        fence_key = self._fence_key(resource)
        fence = await self._redis.incr(fence_key)
        
        return Lease(token=token, fence=fence)

    async def renew(self, lease: Lease) -> None:
        try:
            resource, ttl, _ = self._decode_token(lease.token)
        except ValueError:
            # Phantom or malformed lease
            raise LockError("Invalid lease token")

        key = self._lock_key(resource)
        px = int(ttl * 1000)
        
        result = await self._renew_script(keys=[key], args=[lease.token, px])
        if result == 0:
            raise LockError("Failed to renew lock (expired, stolen, or invalid token)")

    async def release(self, lease: Lease) -> None:
        try:
            resource, _, _ = self._decode_token(lease.token)
        except ValueError:
            # Releasing a phantom lease is a safe no-op per contract
            return
            
        key = self._lock_key(resource)
        
        # We don't care if it fails, as release must be idempotent/no-op for stale leases
        await self._release_script(keys=[key], args=[lease.token])
