"""Redis-backed agent state management.

Replaces in-memory sets (_processed_obs, _checked_pairs) with
Redis SETs that persist across restarts and are shared across
multiple agent instances.

Includes distributed locking for multi-instance coordination.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class AgentState:
    """Redis-backed state for agent bookkeeping."""

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def is_processed(self, key: str, member: str) -> bool:
        """Check if a member exists in a Redis SET."""
        return await self._redis.sismember(key, member)

    async def mark_processed(self, key: str, member: str) -> None:
        """Add a member to a Redis SET."""
        await self._redis.sadd(key, member)

    async def try_acquire(
        self, key: str, instance_id: str, ttl: int = 300
    ) -> bool:
        """Try to acquire a distributed lock.

        Uses SET NX EX for atomic check-and-set with expiry.
        Returns True if this instance acquired the lock.
        """
        result = await self._redis.set(
            f"lock:{key}", instance_id, nx=True, ex=ttl
        )
        return result is not None

    async def close(self) -> None:
        await self._redis.close()


class InMemoryAgentState:
    """In-memory fallback for when Redis is not available (dev/test)."""

    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = {}
        self._locks: dict[str, str] = {}

    async def is_processed(self, key: str, member: str) -> bool:
        return member in self._sets.get(key, set())

    async def mark_processed(self, key: str, member: str) -> None:
        self._sets.setdefault(key, set()).add(member)

    async def try_acquire(
        self, key: str, instance_id: str, ttl: int = 300
    ) -> bool:
        lock_key = f"lock:{key}"
        if lock_key not in self._locks:
            self._locks[lock_key] = instance_id
            return True
        return self._locks[lock_key] == instance_id

    async def close(self) -> None:
        pass
