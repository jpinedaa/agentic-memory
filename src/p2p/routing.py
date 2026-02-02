"""Capability-based routing table for P2P network."""

from __future__ import annotations

import random
from src.p2p.types import Capability, PeerState


# Which capabilities are required for each MemoryAPI method.
METHOD_CAPABILITIES: dict[str, set[Capability]] = {
    "observe": {Capability.STORE, Capability.LLM},
    "claim": {Capability.STORE, Capability.LLM},
    "remember": {Capability.STORE, Capability.LLM},
    "infer": {Capability.LLM},
    "get_recent_observations": {Capability.STORE},
    "get_recent_statements": {Capability.STORE},
    "get_unresolved_contradictions": {Capability.STORE},
    "get_concepts": {Capability.STORE},
    "flag_contradiction": {Capability.STORE},
    "clear": {Capability.STORE},
}


class RoutingTable:
    """Maps capabilities to known peers for capability-based routing.

    Maintains a local view of all peers in the network, updated via gossip.
    Routes MemoryAPI method calls to peers that have the required capabilities.
    """

    def __init__(self) -> None:
        self._peers: dict[str, PeerState] = {}

    def update_peer(self, state: PeerState) -> bool:
        """Update peer state. Returns True if this was new information.

        A peer's state is considered new if we haven't seen it before,
        or if the incoming heartbeat_seq is higher than what we have.

        Even when heartbeat_seq hasn't changed, we still refresh last_seen
        to keep health checks accurate (receiving gossip about a peer
        proves it was recently alive).
        """
        existing = self._peers.get(state.info.node_id)
        if existing is None:
            self._peers[state.info.node_id] = state
            return True
        if state.heartbeat_seq > existing.heartbeat_seq:
            self._peers[state.info.node_id] = state
            return True
        # Refresh last_seen even if seq hasn't changed
        if state.last_seen > existing.last_seen:
            existing.last_seen = state.last_seen
            existing.status = "alive"
        return False

    def remove_peer(self, node_id: str) -> None:
        """Remove a peer from the routing table."""
        self._peers.pop(node_id, None)

    def find_peers_with_capability(
        self, capability: Capability, exclude: str = ""
    ) -> list[PeerState]:
        """Return alive peers that have the given capability."""
        return [
            ps
            for ps in self._peers.values()
            if ps.status == "alive"
            and capability in ps.info.capabilities
            and ps.info.node_id != exclude
        ]

    def route_method(self, method: str, exclude: str = "") -> PeerState | None:
        """Find a peer that can handle a MemoryAPI method.

        Returns one peer that has ALL required capabilities for the method.
        Uses random selection for simple load distribution.
        """
        required = METHOD_CAPABILITIES.get(method, set())
        candidates = [
            ps
            for ps in self._peers.values()
            if ps.status == "alive"
            and ps.info.node_id != exclude
            and required.issubset(ps.info.capabilities)
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    def get_alive_peers(self, exclude: str = "") -> list[PeerState]:
        """Return all alive peers, optionally excluding one."""
        return [
            ps
            for ps in self._peers.values()
            if ps.status == "alive" and ps.info.node_id != exclude
        ]

    def get_all_peers(self) -> list[PeerState]:
        """Return all known peers regardless of status."""
        return list(self._peers.values())

    @property
    def peer_count(self) -> int:
        """Return the number of known peers."""
        return len(self._peers)
