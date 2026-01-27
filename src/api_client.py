"""HTTP client implementing MemoryAPI protocol.

Drop-in replacement for MemoryService when running out-of-process.
Agents and CLI use this to talk to the FastAPI server.
"""

from __future__ import annotations

from typing import Any

import httpx


class MemoryClient:
    """HTTP client that mirrors the MemoryService API.

    Satisfies the MemoryAPI protocol via structural typing.
    """

    def __init__(
        self, base_url: str = "http://localhost:8000", timeout: float = 120.0
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def observe(self, text: str, source: str) -> str:
        r = await self._client.post(
            "/v1/observe", json={"text": text, "source": source}
        )
        r.raise_for_status()
        return r.json()["observation_id"]

    async def claim(self, text: str, source: str) -> str:
        r = await self._client.post(
            "/v1/claim", json={"text": text, "source": source}
        )
        r.raise_for_status()
        return r.json()["claim_id"]

    async def remember(self, query: str) -> str:
        r = await self._client.post(
            "/v1/remember", json={"query": query}
        )
        r.raise_for_status()
        return r.json()["response"]

    async def infer(self, observation_text: str) -> str | None:
        r = await self._client.post(
            "/v1/infer", json={"observation_text": observation_text}
        )
        r.raise_for_status()
        return r.json()["claim_text"]

    async def get_recent_observations(
        self, limit: int = 10
    ) -> list[dict[str, Any]]:
        r = await self._client.get(
            "/v1/observations/recent", params={"limit": limit}
        )
        r.raise_for_status()
        return r.json()["observations"]

    async def get_recent_claims(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        r = await self._client.get(
            "/v1/claims/recent", params={"limit": limit}
        )
        r.raise_for_status()
        return r.json()["claims"]

    async def get_unresolved_contradictions(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        r = await self._client.get("/v1/contradictions/unresolved")
        r.raise_for_status()
        data = r.json()["contradictions"]
        return [(item["c1"], item["c2"]) for item in data]

    async def get_entities(self) -> list[dict[str, Any]]:
        r = await self._client.get("/v1/entities")
        r.raise_for_status()
        return r.json()["entities"]

    async def clear(self) -> None:
        r = await self._client.post("/v1/admin/clear")
        r.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
