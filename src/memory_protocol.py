# pylint: disable=missing-function-docstring  # protocol stubs use `...` bodies; names are self-documenting
"""MemoryAPI protocol — shared contract for MemoryService and MemoryClient.

Both in-process (MemoryService) and HTTP (MemoryClient) implementations
satisfy this protocol via structural typing.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryAPI(Protocol):
    """Interface that both MemoryService and MemoryClient implement."""

    # Core operations
    async def observe(self, text: str, source: str) -> str: ...
    async def claim(self, text: str, source: str) -> str: ...
    async def remember(self, query: str) -> str: ...

    # Store queries (facade over direct store access)
    async def get_recent_observations(self, limit: int = 10) -> list[dict[str, Any]]: ...
    async def get_recent_statements(self, limit: int = 20) -> list[dict[str, Any]]: ...
    async def get_unresolved_contradictions(self) -> list[tuple[dict[str, Any], dict[str, Any]]]: ...
    async def get_concepts(self) -> list[dict[str, Any]]: ...

    # LLM inference (facade over direct LLM access)
    async def infer(self, observation_text: str) -> str | None: ...

    # Admin
    async def clear(self) -> None: ...
