"""Push-based gossip protocol for propagating peer state."""
# pylint: disable=protected-access  # gossip is an internal collaborator of PeerNode, not an external consumer

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING

from src.p2p.messages import Envelope
from src.p2p.types import PeerState

if TYPE_CHECKING:
    from src.p2p.node import PeerNode

logger = logging.getLogger(__name__)

GOSSIP_FANOUT = 3  # number of peers to gossip to each round


class GossipProtocol:
    """Push-based gossip for propagating peer state across the network.

    Every gossip_interval seconds, the node sends its full peer table
    to a random subset of neighbors. On receiving gossip, it updates
    its routing table — higher heartbeat_seq always wins.
    """

    def __init__(self, node: PeerNode, interval: float = 5.0) -> None:
        self.node = node
        self.interval = interval

    async def run_loop(self) -> None:
        """Main gossip loop — runs until node stops."""
        while self.node._running:
            await asyncio.sleep(self.interval)
            await self._gossip_round()

    async def _gossip_round(self) -> None:
        """Push peer table to a random subset of neighbors."""
        # Collect all neighbor IDs (both inbound and outbound WS)
        neighbor_ids = (
            self.node.transport_client.connected_peer_ids
            | self.node.transport_server.inbound_peer_ids
        )
        if not neighbor_ids:
            return

        targets = random.sample(
            sorted(neighbor_ids), min(GOSSIP_FANOUT, len(neighbor_ids))
        )

        # Build payload: own state + all known peers
        own_state = PeerState(
            info=self.node.info,
            status="alive",
            last_seen=time.time(),
            heartbeat_seq=self.node._heartbeat_seq,
            metadata=self.node._build_metadata(),
        )
        all_states = [own_state] + self.node.routing.get_all_peers()

        envelope = Envelope(
            msg_type="gossip",
            sender_id=self.node.node_id,
            payload={
                "peer_states": [ps.to_dict() for ps in all_states],
            },
        )
        data = envelope.to_dict()

        for target_id in targets:
            # Try outbound WS first, then inbound WS
            sent = await self.node.transport_client.ws_send(target_id, data)
            if not sent:
                await self.node.transport_server.send_to_inbound(target_id, data)

    def handle_gossip(self, envelope: Envelope) -> None:
        """Process incoming gossip, updating the routing table."""
        now = time.time()
        for ps_dict in envelope.payload.get("peer_states", []):
            ps = PeerState.from_dict(ps_dict)
            if ps.info.node_id == self.node.node_id:
                continue
            # Use local receive time for health checks (not sender's clock)
            ps.last_seen = now
            # Re-apply URL overrides so gossip doesn't reset remapped URLs
            self.node.apply_url_overrides(ps)
            updated = self.node.routing.update_peer(ps)
            if updated:
                logger.debug(
                    "Gossip: updated peer %s (seq=%d, caps=%s)",
                    ps.info.node_id, ps.heartbeat_seq, ps.info.capabilities,
                )
