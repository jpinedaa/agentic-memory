"""PeerNode: core runtime for a single node in the P2P network."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Awaitable

from src.p2p.types import Capability, PeerInfo, PeerState, generate_node_id
from src.p2p.messages import Envelope
from src.p2p.routing import RoutingTable, METHOD_CAPABILITIES
from src.p2p.transport import TransportServer, TransportClient
from src.p2p.gossip import GossipProtocol

logger = logging.getLogger(__name__)

MAX_NEIGHBORS = 8
GOSSIP_INTERVAL = 5.0
HEALTH_CHECK_INTERVAL = 10.0
SUSPECT_TIMEOUT = 15.0
DEAD_TIMEOUT = 30.0
HEARTBEAT_INTERVAL = 5.0
SEEN_MSG_MAX = 10_000


class PeerNode:
    """A single node in the P2P network.

    Runs an HTTP+WS server, maintains neighbor connections,
    gossips state, and routes MemoryAPI calls to capable peers.
    """

    def __init__(
        self,
        capabilities: set[Capability],
        listen_host: str = "0.0.0.0",
        listen_port: int = 9000,
        bootstrap_peers: list[str] | None = None,
        node_id: str | None = None,
        advertise_host: str | None = None,
    ) -> None:
        self.node_id = node_id or generate_node_id()
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.capabilities = frozenset(capabilities)
        self.bootstrap_peers = bootstrap_peers or []

        # Advertise host is what other nodes use to reach us.
        # Defaults to listen_host, but in Docker/k8s you need
        # to set this to the container hostname or service name.
        self._advertise_host = advertise_host or listen_host

        self.info = PeerInfo(
            node_id=self.node_id,
            capabilities=self.capabilities,
            http_url=f"http://{self._advertise_host}:{listen_port}",
            ws_url=f"ws://{self._advertise_host}:{listen_port}/p2p/ws",
            started_at=time.time(),
        )

        self.routing = RoutingTable()
        self.gossip = GossipProtocol(self, interval=GOSSIP_INTERVAL)
        self.transport_server = TransportServer(self)
        self.transport_client = TransportClient()

        self._heartbeat_seq = 0
        self._running = False
        self._seen_msgs: OrderedDict[str, None] = OrderedDict()
        self._tasks: list[asyncio.Task] = []

        # Local services (injected based on capabilities)
        self._local_services: dict[str, Any] = {}

        # Event listeners (agents, UI, etc.)
        self._event_listeners: list[Callable[[str, dict[str, Any]], Awaitable[None]]] = []

    def register_service(self, name: str, service: Any) -> None:
        """Register a local service (e.g. 'memory', 'store', 'llm')."""
        self._local_services[name] = service

    def get_service(self, name: str) -> Any | None:
        return self._local_services.get(name)

    def add_event_listener(
        self, listener: Callable[[str, dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Register a callback for network events (observation, claim, etc.)."""
        self._event_listeners.append(listener)

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Full startup sequence."""
        self._running = True

        # Start HTTP+WS server
        await self.transport_server.start(self.listen_host, self.listen_port)
        logger.info(
            f"Node {self.node_id} listening on {self.listen_host}:{self.listen_port} "
            f"capabilities={sorted(c.value for c in self.capabilities)}"
        )

        # Bootstrap: join known peers
        for peer_url in self.bootstrap_peers:
            try:
                peers = await self._join_peer(peer_url)
                for ps in peers:
                    self.routing.update_peer(ps)
                logger.info(
                    f"Bootstrapped via {peer_url}, learned {len(peers)} peer(s)"
                )
            except Exception:
                logger.warning(f"Failed to bootstrap with {peer_url}")

        # Connect WebSocket to discovered neighbors
        await self._connect_to_neighbors()

        # Start background loops
        self._tasks = [
            asyncio.create_task(self.gossip.run_loop()),
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._heartbeat_loop()),
        ]

        logger.info(
            f"Node {self.node_id} started, knows {self.routing.peer_count} peer(s)"
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False

        # Notify neighbors
        leave = Envelope(msg_type="leave", sender_id=self.node_id)
        data = leave.to_dict()
        await self.transport_client.broadcast_ws(data)
        await self.transport_server.broadcast_inbound(data)

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.transport_client.close_all()
        await self.transport_server.stop()
        logger.info(f"Node {self.node_id} stopped")

    # ── Bootstrap ───────────────────────────────────────────────────

    async def _join_peer(self, peer_url: str) -> list[PeerState]:
        """Send a join message to a seed peer and get back known peers."""
        envelope = Envelope(
            msg_type="join",
            sender_id=self.node_id,
            payload={"peer_info": self.info.to_dict()},
        )
        response = await self.transport_client.http_post(
            f"{peer_url}/p2p/message", envelope.to_dict()
        )
        if response and response.get("msg_type") == "welcome":
            return [
                PeerState.from_dict(ps)
                for ps in response["payload"].get("peers", [])
            ]
        return []

    # ── Neighbor Management ─────────────────────────────────────────

    async def _connect_to_neighbors(self) -> None:
        """Connect outbound WebSocket to peers, up to MAX_NEIGHBORS."""
        connected = self.transport_client.connected_peer_ids
        needed = MAX_NEIGHBORS - len(connected)
        if needed <= 0:
            return

        # Prefer peers with complementary capabilities
        peers = self.routing.get_alive_peers(exclude=self.node_id)
        peers.sort(key=lambda p: -len(p.info.capabilities - self.capabilities))

        for ps in peers[:needed]:
            if ps.info.node_id not in connected:
                await self.transport_client.ws_connect(
                    ps.info.node_id,
                    ps.info.ws_url,
                    on_message=self._on_ws_message,
                )

    async def _on_ws_message(self, data: dict[str, Any]) -> None:
        """Handle a message received on an outbound WebSocket."""
        envelope = Envelope.from_dict(data)
        response = await self.handle_envelope(envelope)
        if response:
            await self.transport_client.ws_send(
                envelope.sender_id, response.to_dict()
            )

    # ── Background Loops ────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Increment heartbeat sequence periodically."""
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            self._heartbeat_seq += 1

    async def _health_check_loop(self) -> None:
        """Check peer liveness and replace dead neighbors."""
        while self._running:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            now = time.time()
            to_remove = []

            for ps in self.routing.get_all_peers():
                elapsed = now - ps.last_seen
                if elapsed > DEAD_TIMEOUT:
                    ps.status = "dead"
                    to_remove.append(ps.info.node_id)
                elif elapsed > SUSPECT_TIMEOUT:
                    if ps.status != "suspect":
                        ps.status = "suspect"
                        # Try a ping via HTTP
                        result = await self.transport_client.http_post(
                            f"{ps.info.http_url}/p2p/health", {}
                        )
                        if result:
                            ps.status = "alive"
                            ps.last_seen = now

            for node_id in to_remove:
                self.routing.remove_peer(node_id)
                await self.transport_client.close_peer(node_id)
                logger.info(f"Removed dead peer {node_id}")

            # Replace lost neighbors
            await self._connect_to_neighbors()

    # ── Message Dispatch ────────────────────────────────────────────

    async def handle_envelope(self, envelope: Envelope) -> Envelope | None:
        """Central dispatch for all incoming messages."""
        # Dedup
        if envelope.msg_id in self._seen_msgs:
            return None
        self._seen_msgs[envelope.msg_id] = None
        if len(self._seen_msgs) > SEEN_MSG_MAX:
            # Evict oldest half
            for _ in range(SEEN_MSG_MAX // 2):
                self._seen_msgs.popitem(last=False)

        handler = {
            "join": self._handle_join,
            "gossip": self._handle_gossip,
            "ping": self._handle_ping,
            "request": self._handle_request,
            "event": self._handle_event,
            "leave": self._handle_leave,
        }.get(envelope.msg_type)

        if handler:
            return await handler(envelope)

        logger.warning(f"Unknown message type: {envelope.msg_type}")
        return None

    async def _handle_join(self, envelope: Envelope) -> Envelope:
        """New peer wants to join — add them and return known peers."""
        peer_info = PeerInfo.from_dict(envelope.payload["peer_info"])
        new_state = PeerState(
            info=peer_info,
            status="alive",
            last_seen=time.time(),
            heartbeat_seq=0,
        )
        self.routing.update_peer(new_state)

        # Return our info + all known peers
        own_state = PeerState(
            info=self.info,
            status="alive",
            last_seen=time.time(),
            heartbeat_seq=self._heartbeat_seq,
        )
        all_peers = [own_state] + self.routing.get_all_peers()
        # Don't send the joining peer back to itself
        all_peers = [
            ps for ps in all_peers if ps.info.node_id != envelope.sender_id
        ]

        return Envelope(
            msg_type="welcome",
            sender_id=self.node_id,
            reply_to=envelope.msg_id,
            payload={"peers": [ps.to_dict() for ps in all_peers]},
        )

    async def _handle_gossip(self, envelope: Envelope) -> None:
        self.gossip.handle_gossip(envelope)
        return None

    async def _handle_ping(self, envelope: Envelope) -> Envelope:
        return Envelope(
            msg_type="pong",
            sender_id=self.node_id,
            reply_to=envelope.msg_id,
        )

    async def _handle_request(self, envelope: Envelope) -> Envelope:
        """Handle an incoming MemoryAPI RPC request."""
        method = envelope.payload.get("method", "")
        args = envelope.payload.get("args", {})

        required = METHOD_CAPABILITIES.get(method, set())
        if not required.issubset(self.capabilities):
            return Envelope(
                msg_type="response",
                sender_id=self.node_id,
                reply_to=envelope.msg_id,
                payload={
                    "result": None,
                    "error": f"Node {self.node_id} lacks capabilities for '{method}'",
                },
            )

        try:
            memory = self.get_service("memory")
            if memory is None:
                raise RuntimeError("No MemoryService registered on this node")
            fn = getattr(memory, method)
            result = await fn(**args)

            # After observe/claim, broadcast event to network
            if method in ("observe", "claim"):
                await self._broadcast_event(method, {
                    "id": result,
                    "source": args.get("source", ""),
                    "text": args.get("text", ""),
                })

            return Envelope(
                msg_type="response",
                sender_id=self.node_id,
                reply_to=envelope.msg_id,
                payload={"result": result, "error": None},
            )
        except Exception as e:
            logger.exception(f"Error handling request '{method}'")
            return Envelope(
                msg_type="response",
                sender_id=self.node_id,
                reply_to=envelope.msg_id,
                payload={"result": None, "error": str(e)},
            )

    async def _handle_event(self, envelope: Envelope) -> None:
        """Handle incoming event: notify local listeners, re-broadcast if TTL allows."""
        event_type = envelope.payload.get("event_type", "")
        data = envelope.payload.get("data", {})

        # Notify local listeners
        for listener in self._event_listeners:
            try:
                await listener(event_type, data)
            except Exception:
                logger.debug("Error in event listener", exc_info=True)

        # Re-broadcast if TTL allows
        if envelope.ttl > 1:
            fwd = Envelope(
                msg_type="event",
                msg_id=envelope.msg_id,  # same ID for dedup
                sender_id=envelope.sender_id,  # original sender
                ttl=envelope.ttl - 1,
                payload=envelope.payload,
            )
            data = fwd.to_dict()
            await self.transport_client.broadcast_ws(data)
            await self.transport_server.broadcast_inbound(data)

        return None

    async def _handle_leave(self, envelope: Envelope) -> None:
        """Peer is shutting down gracefully."""
        self.routing.remove_peer(envelope.sender_id)
        await self.transport_client.close_peer(envelope.sender_id)
        logger.info(f"Peer {envelope.sender_id} left the network")
        return None

    # ── Event Broadcasting ──────────────────────────────────────────

    async def _broadcast_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a memory event to the network."""
        envelope = Envelope(
            msg_type="event",
            sender_id=self.node_id,
            ttl=3,
            payload={"event_type": event_type, "data": data},
        )
        msg = envelope.to_dict()
        # Mark as seen so we don't re-process our own broadcast
        self._seen_msgs[envelope.msg_id] = None
        await self.transport_client.broadcast_ws(msg)
        await self.transport_server.broadcast_inbound(msg)

    # ── Metadata ────────────────────────────────────────────────────

    def _build_metadata(self) -> dict[str, Any]:
        """Build metadata dict for gossip (agent metrics, etc.)."""
        return {
            "peer_count": self.routing.peer_count,
            "neighbor_count": (
                len(self.transport_client.connected_peer_ids)
                + len(self.transport_server.inbound_peer_ids)
            ),
        }
