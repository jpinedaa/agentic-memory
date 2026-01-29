"""Core P2P types: node identity, capabilities, and peer state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Capability(str, Enum):
    """Services a node can provide to the network."""

    STORE = "store"
    LLM = "llm"
    INFERENCE = "inference"
    VALIDATION = "validation"
    CLI = "cli"


@dataclass(frozen=True)
class PeerInfo:
    """Immutable identity and address of a node, gossiped through the network."""

    node_id: str
    capabilities: frozenset[Capability]
    http_url: str
    ws_url: str
    started_at: float = 0.0
    version: str = "0.3.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialize peer info to a dict."""
        return {
            "node_id": self.node_id,
            "capabilities": sorted(c.value for c in self.capabilities),
            "http_url": self.http_url,
            "ws_url": self.ws_url,
            "started_at": self.started_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PeerInfo:
        """Deserialize peer info from a dict."""
        return cls(
            node_id=d["node_id"],
            capabilities=frozenset(Capability(c) for c in d["capabilities"]),
            http_url=d["http_url"],
            ws_url=d["ws_url"],
            started_at=d.get("started_at", 0.0),
            version=d.get("version", "0.3.0"),
        )


@dataclass
class PeerState:
    """Mutable state about a peer, tracked locally and propagated via gossip."""

    info: PeerInfo
    status: str = "alive"  # alive | suspect | dead
    last_seen: float = 0.0
    heartbeat_seq: int = 0  # monotonic counter, only the owning node increments
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize peer state to a dict."""
        return {
            "info": self.info.to_dict(),
            "status": self.status,
            "last_seen": self.last_seen,
            "heartbeat_seq": self.heartbeat_seq,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PeerState:
        """Deserialize peer state from a dict."""
        return cls(
            info=PeerInfo.from_dict(d["info"]),
            status=d.get("status", "alive"),
            last_seen=d.get("last_seen", 0.0),
            heartbeat_seq=d.get("heartbeat_seq", 0),
            metadata=d.get("metadata", {}),
        )


def generate_node_id() -> str:
    """Generate a unique node identifier."""
    return f"node-{uuid.uuid4().hex[:8]}"
