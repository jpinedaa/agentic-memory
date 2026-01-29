"""Local in-process agent state, replacing Redis-backed AgentState."""

from __future__ import annotations


class LocalAgentState:
    """Local in-process state for agent bookkeeping.

    Each node tracks its own processed sets locally. No cross-node
    state sharing is needed because the store is append-only and
    duplicate processing is harmless.

    Same interface as the old AgentState / InMemoryAgentState.
    """

    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = {}
        self._locks: dict[str, str] = {}

    async def is_processed(self, key: str, member: str) -> bool:
        """Check if a member has been processed for the given key."""
        return member in self._sets.get(key, set())

    async def mark_processed(self, key: str, member: str) -> None:
        """Mark a member as processed for the given key."""
        self._sets.setdefault(key, set()).add(member)

    async def try_acquire(
        self, key: str, instance_id: str,
        ttl: int = 300,  # pylint: disable=unused-argument  # kept for Redis interface compat
    ) -> bool:
        """Try to acquire a lock for the given key and instance."""
        lock_key = f"lock:{key}"
        if lock_key not in self._locks:
            self._locks[lock_key] = instance_id
            return True
        return self._locks[lock_key] == instance_id

    async def close(self) -> None:
        """Clean up resources."""
