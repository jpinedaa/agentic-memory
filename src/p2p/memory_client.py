"""P2PMemoryClient: MemoryAPI implementation that routes calls through the P2P network."""
# pylint: disable=protected-access  # memory client is an internal collaborator of PeerNode

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from src.p2p.messages import Envelope
from src.p2p.routing import METHOD_CAPABILITIES

if TYPE_CHECKING:
    from src.p2p.node import PeerNode
    from src.p2p.types import PeerState


class P2PMemoryClient:
    """MemoryAPI implementation that routes calls to capable peers.

    If the local node has the required capabilities, executes locally.
    Otherwise, finds a peer with the right capabilities via the routing table.

    Satisfies the MemoryAPI protocol via structural typing.
    """

    def __init__(self, node: PeerNode) -> None:
        self._node = node

    async def observe(self, text: str, source: str) -> str:
        """Record an observation via P2P routing."""
        return await self._call("observe", {"text": text, "source": source})

    async def claim(self, text: str, source: str) -> str:
        """Assert a claim via P2P routing."""
        return await self._call("claim", {"text": text, "source": source})

    async def flag_contradiction(
        self, stmt_id_1: str, stmt_id_2: str, reason: str = ""
    ) -> None:
        """Flag a contradiction between two statements via P2P routing."""
        await self._call(
            "flag_contradiction",
            {"stmt_id_1": stmt_id_1, "stmt_id_2": stmt_id_2, "reason": reason},
        )

    async def remember(self, query: str) -> str:
        """Query the knowledge graph via P2P routing."""
        return await self._call("remember", {"query": query})

    async def infer(self, observation_text: str) -> str | None:
        """Generate an inference from an observation via P2P routing."""
        return await self._call("infer", {"observation_text": observation_text})

    async def get_recent_observations(
        self, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return recent observations via P2P routing."""
        return await self._call("get_recent_observations", {"limit": limit})

    async def get_recent_statements(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent statements via P2P routing."""
        return await self._call("get_recent_statements", {"limit": limit})

    async def get_unresolved_contradictions(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Return unresolved contradictions via P2P routing."""
        return await self._call("get_unresolved_contradictions", {})

    async def get_concepts(self) -> list[dict[str, Any]]:
        """Return all concepts via P2P routing."""
        return await self._call("get_concepts", {})

    async def get_schema(self) -> dict[str, Any]:
        """Return the current schema via P2P routing."""
        return await self._call("get_schema", {})

    async def update_schema(
        self, changes: dict[str, Any], source: str
    ) -> dict[str, Any]:
        """Apply incremental schema changes via P2P routing."""
        return await self._call(
            "update_schema", {"changes": changes, "source": source}
        )

    async def clear(self) -> None:
        """Clear all data via P2P routing."""
        await self._call("clear", {})

    async def _call(self, method: str, args: dict[str, Any]) -> Any:
        """Route a MemoryAPI call: local if capable, otherwise find a peer."""
        required = METHOD_CAPABILITIES.get(method, set())

        # Can we handle it locally?
        if required.issubset(self._node.capabilities):
            return await self._execute_local(method, args)

        # Find a peer with the required capabilities
        peer = self._node.routing.route_method(method, exclude=self._node.node_id)
        if peer is None:
            raise RuntimeError(
                f"No peer available with capabilities {required} "
                f"for method '{method}'"
            )

        return await self._execute_remote(peer, method, args)

    async def _execute_local(self, method: str, args: dict[str, Any]) -> Any:
        """Execute a MemoryAPI method using local services."""
        memory = self._node.get_service("memory")
        if memory is None:
            raise RuntimeError("No local MemoryService registered")
        fn = getattr(memory, method)
        result = await fn(**args)

        # After local observe/claim/flag_contradiction, broadcast event to network
        if method in ("observe", "claim", "flag_contradiction"):
            await self._node._broadcast_event(method, {
                "id": result,
                "source": args.get("source", ""),
                "text": args.get("text", ""),
            })

        return result

    async def _execute_remote(
        self, peer: PeerState, method: str, args: dict[str, Any]
    ) -> Any:
        """Execute a MemoryAPI method on a remote peer via HTTP."""
        envelope = Envelope(
            msg_type="request",
            sender_id=self._node.node_id,
            recipient_id=peer.info.node_id,
            payload={"method": method, "args": args},
        )
        response = await self._node.transport_client.http_post(
            f"{peer.info.http_url}/p2p/message",
            envelope.to_dict(),
        )
        if response is None:
            raise RuntimeError(
                f"No response from peer {peer.info.node_id} for '{method}'"
            )

        if response.get("msg_type") == "response":
            if response["payload"].get("error"):
                raise RuntimeError(response["payload"]["error"])
            return response["payload"].get("result")

        raise RuntimeError(f"Unexpected response type: {response.get('msg_type')}")
