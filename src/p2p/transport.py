"""Transport layer: HTTP + WebSocket server and client for P2P communication."""
# pylint: disable=import-outside-toplevel  # lazy import breaks circular dependency with messages/ui_bridge

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Awaitable

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import uvicorn
import websockets

if TYPE_CHECKING:
    from src.p2p.node import PeerNode

logger = logging.getLogger(__name__)


class TransportServer:
    """HTTP + WebSocket server for incoming P2P messages.

    Each node runs one TransportServer. It exposes:
      POST /p2p/message  — request/response envelope exchange
      WS   /p2p/ws       — persistent bidirectional connection for gossip + events
      GET  /p2p/health    — liveness check
    """

    def __init__(self, node: PeerNode) -> None:
        self.node = node
        self.app = FastAPI(title=f"P2P Node {node.node_id}")
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None
        self._inbound_ws: dict[str, WebSocket] = {}  # peer_node_id -> ws

        self.app.post("/p2p/message")(self._handle_message)
        self.app.websocket("/p2p/ws")(self._handle_ws)
        self.app.get("/p2p/health")(self._health)

    async def _handle_message(self, body: dict[str, Any]) -> dict[str, Any]:
        """HTTP endpoint for request/response and join messages."""
        from src.p2p.messages import Envelope

        envelope = Envelope.from_dict(body)
        response = await self.node.handle_envelope(envelope)
        if response:
            return response.to_dict()
        return {"status": "ok"}

    async def _handle_ws(self, websocket: WebSocket) -> None:
        """WebSocket endpoint for persistent neighbor connections."""
        from src.p2p.messages import Envelope

        await websocket.accept()
        peer_id = None
        try:
            while True:
                data = await websocket.receive_json()
                envelope = Envelope.from_dict(data)
                peer_id = envelope.sender_id
                self._inbound_ws[peer_id] = websocket
                response = await self.node.handle_envelope(envelope)
                if response:
                    await websocket.send_json(response.to_dict())
        except WebSocketDisconnect:
            if peer_id:
                self._inbound_ws.pop(peer_id, None)
                logger.info("Peer %s disconnected (inbound WS)", peer_id)
        except Exception:  # pylint: disable=broad-exception-caught  # WebSocket handler must not crash the server
            if peer_id:
                self._inbound_ws.pop(peer_id, None)
            logger.debug("WebSocket connection error", exc_info=True)

    def mount_ui_bridge(self, store: Any) -> None:
        """Mount the /v1/ UI bridge endpoints on this node's FastAPI app."""
        from src.p2p.ui_bridge import create_ui_bridge
        router = create_ui_bridge(self.node, store)
        self.app.include_router(router)

    async def _health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "node_id": self.node.node_id,
            "capabilities": sorted(c.value for c in self.node.capabilities),
            "peer_count": self.node.routing.peer_count,
        }

    async def send_to_inbound(self, peer_id: str, data: dict[str, Any]) -> bool:
        """Send data to a peer via their inbound WebSocket connection."""
        ws = self._inbound_ws.get(peer_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.send_json(data)
                return True
            except Exception:  # pylint: disable=broad-exception-caught  # WebSocket handler must not crash the server
                self._inbound_ws.pop(peer_id, None)
        return False

    async def broadcast_inbound(self, data: dict[str, Any]) -> int:
        """Broadcast to all inbound WebSocket peers."""
        count = 0
        dead = []
        for peer_id, ws in self._inbound_ws.items():
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(data)
                    count += 1
                else:
                    dead.append(peer_id)
            except Exception:  # pylint: disable=broad-exception-caught  # send failure must not crash broadcast
                dead.append(peer_id)
        for peer_id in dead:
            self._inbound_ws.pop(peer_id, None)
        return count

    @property
    def inbound_peer_ids(self) -> set[str]:
        """Return IDs of all inbound WebSocket peers."""
        return set(self._inbound_ws.keys())

    async def start(self, host: str, port: int) -> None:
        """Start the HTTP+WS server."""
        config = uvicorn.Config(
            self.app, host=host, port=port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
        # Give the server a moment to bind
        await asyncio.sleep(0.3)

    async def stop(self) -> None:
        """Stop the server."""
        if self._server_task:
            self._server.should_exit = True
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass


class TransportClient:
    """Manages outbound HTTP and WebSocket connections to peers."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._outbound_ws: dict[str, Any] = {}  # node_id -> websockets connection
        self._ws_tasks: dict[str, asyncio.Task] = {}

    async def http_post(self, url: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Send a message via HTTP POST, return response body."""
        try:
            r = await self._http.post(url, json=data)
            r.raise_for_status()
            return r.json()
        except Exception:  # pylint: disable=broad-exception-caught  # HTTP failure must not crash the caller
            logger.debug("HTTP POST to %s failed", url, exc_info=True)
            return None

    async def ws_connect(
        self,
        node_id: str,
        ws_url: str,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> bool:
        """Establish a persistent outbound WebSocket connection to a peer."""
        if node_id in self._outbound_ws:
            return True
        try:
            ws = await websockets.connect(ws_url)
            self._outbound_ws[node_id] = ws
            if on_message:
                self._ws_tasks[node_id] = asyncio.create_task(
                    self._ws_read_loop(node_id, ws, on_message)
                )
            logger.info("Connected outbound WS to %s at %s", node_id, ws_url)
            return True
        except Exception:  # pylint: disable=broad-exception-caught  # connection failure must not crash the caller
            logger.debug("Failed to connect WS to %s at %s", node_id, ws_url)
            return False

    async def _ws_read_loop(
        self,
        node_id: str,
        ws: Any,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Read messages from an outbound WebSocket connection."""
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    await on_message(data)
                except Exception:  # pylint: disable=broad-exception-caught  # message handler must not crash the WS loop
                    logger.debug("Error handling WS message from %s", node_id, exc_info=True)
        except websockets.ConnectionClosed:
            logger.info("Outbound WS to %s closed", node_id)
        except Exception:  # pylint: disable=broad-exception-caught  # message handler must not crash the WS loop
            logger.debug("Outbound WS read error for %s", node_id, exc_info=True)
        finally:
            self._outbound_ws.pop(node_id, None)
            self._ws_tasks.pop(node_id, None)

    async def ws_send(self, node_id: str, data: dict[str, Any]) -> bool:
        """Send data to a specific peer via outbound WebSocket."""
        ws = self._outbound_ws.get(node_id)
        if ws:
            try:
                await ws.send(json.dumps(data, default=str))
                return True
            except Exception:  # pylint: disable=broad-exception-caught  # send failure must not crash broadcast
                self._outbound_ws.pop(node_id, None)
        return False

    async def broadcast_ws(self, data: dict[str, Any]) -> int:
        """Send to all outbound WebSocket peers. Returns count sent."""
        count = 0
        dead = []
        payload = json.dumps(data, default=str)
        for node_id, ws in self._outbound_ws.items():
            try:
                await ws.send(payload)
                count += 1
            except Exception:  # pylint: disable=broad-exception-caught  # send failure must not crash broadcast
                dead.append(node_id)
        for node_id in dead:
            self._outbound_ws.pop(node_id, None)
        return count

    @property
    def connected_peer_ids(self) -> set[str]:
        """Return IDs of all outbound WebSocket peers."""
        return set(self._outbound_ws.keys())

    def is_connected(self, node_id: str) -> bool:
        """Check if a peer has an outbound WebSocket connection."""
        return node_id in self._outbound_ws

    async def close_peer(self, node_id: str) -> None:
        """Close the outbound connection to a specific peer."""
        ws = self._outbound_ws.pop(node_id, None)
        if ws:
            await ws.close()
        task = self._ws_tasks.pop(node_id, None)
        if task:
            task.cancel()

    async def close_all(self) -> None:
        """Close all outbound connections and the HTTP client."""
        for ws in list(self._outbound_ws.values()):
            try:
                await ws.close()
            except Exception:  # pylint: disable=broad-exception-caught  # close failure must not crash cleanup
                pass
        self._outbound_ws.clear()
        for task in self._ws_tasks.values():
            task.cancel()
        self._ws_tasks.clear()
        await self._http.aclose()
