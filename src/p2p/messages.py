"""Universal message envelope for all P2P communication."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Envelope:
    """Universal message wrapper for all node-to-node communication.

    Used over both HTTP POST and WebSocket. Message types:

        join      - new node announcing itself to a seed peer
        welcome   - response to join, includes known peers
        gossip    - peer state propagation between neighbors
        request   - MemoryAPI RPC call
        response  - RPC result
        event     - broadcast notification (observation/claim created)
        ping/pong - liveness check
        leave     - graceful shutdown notification
    """

    msg_type: str
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    sender_id: str = ""
    recipient_id: str = ""  # empty = broadcast
    timestamp: float = field(default_factory=time.time)
    ttl: int = 3  # hop limit for event flooding
    reply_to: str = ""  # msg_id this is responding to
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_type": self.msg_type,
            "msg_id": self.msg_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "reply_to": self.reply_to,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Envelope:
        return cls(
            msg_type=d["msg_type"],
            msg_id=d.get("msg_id", uuid.uuid4().hex[:16]),
            sender_id=d.get("sender_id", ""),
            recipient_id=d.get("recipient_id", ""),
            timestamp=d.get("timestamp", time.time()),
            ttl=d.get("ttl", 3),
            reply_to=d.get("reply_to", ""),
            payload=d.get("payload", {}),
        )
