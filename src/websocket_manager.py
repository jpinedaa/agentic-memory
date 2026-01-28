"""WebSocket connection manager for real-time updates.

Manages client connections, subscriptions, and message broadcasting.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ClientConnection:
    """Represents a connected WebSocket client."""

    websocket: WebSocket
    client_id: str
    connected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    subscribed_channels: set[str] = field(default_factory=set)
    agent_type_filter: set[str] = field(default_factory=set)
    agent_tag_filter: set[str] = field(default_factory=set)


class WebSocketManager:
    """Manages WebSocket connections and message broadcasting."""

    # Supported channels
    CHANNEL_AGENT_STATUS = "agent_status"
    CHANNEL_AGENT_LIFECYCLE = "agent_lifecycle"
    CHANNEL_MEMORY_EVENT = "memory_event"
    CHANNEL_GRAPH_UPDATE = "graph_update"
    CHANNEL_SYSTEM_STATS = "system_stats"

    ALL_CHANNELS = {
        CHANNEL_AGENT_STATUS,
        CHANNEL_AGENT_LIFECYCLE,
        CHANNEL_MEMORY_EVENT,
        CHANNEL_GRAPH_UPDATE,
        CHANNEL_SYSTEM_STATS,
    }

    def __init__(self) -> None:
        self._connections: dict[str, ClientConnection] = {}
        self._lock = asyncio.Lock()
        self._client_counter = 0

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection."""
        await websocket.accept()

        async with self._lock:
            self._client_counter += 1
            client_id = f"client-{self._client_counter}"
            self._connections[client_id] = ClientConnection(
                websocket=websocket,
                client_id=client_id,
                subscribed_channels=self.ALL_CHANNELS.copy(),  # Subscribe to all by default
            )

        logger.info(f"WebSocket client connected: {client_id}")
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Remove a disconnected client."""
        async with self._lock:
            if client_id in self._connections:
                del self._connections[client_id]
        logger.info(f"WebSocket client disconnected: {client_id}")

    async def handle_message(self, client_id: str, message: dict[str, Any]) -> None:
        """Handle an incoming message from a client."""
        async with self._lock:
            client = self._connections.get(client_id)
            if not client:
                return

        msg_type = message.get("type")

        if msg_type == "subscribe":
            channels = set(message.get("channels", []))
            client.subscribed_channels = channels & self.ALL_CHANNELS
            logger.debug(f"Client {client_id} subscribed to {client.subscribed_channels}")

        elif msg_type == "filter":
            client.agent_type_filter = set(message.get("agent_types", []))
            client.agent_tag_filter = set(message.get("agent_tags", []))
            logger.debug(
                f"Client {client_id} filter: types={client.agent_type_filter}, "
                f"tags={client.agent_tag_filter}"
            )

        elif msg_type == "request_snapshot":
            # Handled by caller (API) which has access to registry
            pass

        elif msg_type == "ping":
            await self.send_to_client(client_id, {"type": "pong"})

    async def send_to_client(self, client_id: str, message: dict[str, Any]) -> bool:
        """Send a message to a specific client."""
        async with self._lock:
            client = self._connections.get(client_id)
            if not client:
                return False

        try:
            await client.websocket.send_json(message)
            return True
        except Exception:
            logger.debug(f"Failed to send to client {client_id}")
            await self.disconnect(client_id)
            return False

    async def broadcast(
        self,
        channel: str,
        message: dict[str, Any],
        agent_type: str | None = None,
        agent_tags: list[str] | None = None,
    ) -> int:
        """Broadcast a message to all subscribed clients.

        Args:
            channel: The channel name (e.g., "agent_status")
            message: The message payload
            agent_type: Optional agent type for filtering
            agent_tags: Optional agent tags for filtering

        Returns:
            Number of clients that received the message
        """
        full_message = {"type": channel, "data": message}
        sent_count = 0
        failed_clients = []

        async with self._lock:
            clients = list(self._connections.values())

        for client in clients:
            # Check channel subscription
            if channel not in client.subscribed_channels:
                continue

            # Check agent type filter
            if client.agent_type_filter and agent_type:
                if agent_type not in client.agent_type_filter:
                    continue

            # Check agent tag filter
            if client.agent_tag_filter and agent_tags:
                if not client.agent_tag_filter & set(agent_tags):
                    continue

            try:
                await client.websocket.send_json(full_message)
                sent_count += 1
            except Exception:
                failed_clients.append(client.client_id)

        # Clean up failed connections
        for client_id in failed_clients:
            await self.disconnect(client_id)

        return sent_count

    async def broadcast_agent_status(self, status: dict[str, Any]) -> int:
        """Broadcast an agent status update."""
        return await self.broadcast(
            self.CHANNEL_AGENT_STATUS,
            status,
            agent_type=status.get("agent_type"),
            agent_tags=status.get("tags", []),
        )

    async def broadcast_agent_lifecycle(
        self,
        event: str,  # registered, deregistered, stale, dead
        agent_id: str,
        agent_type: str,
    ) -> int:
        """Broadcast an agent lifecycle event."""
        return await self.broadcast(
            self.CHANNEL_AGENT_LIFECYCLE,
            {"event": event, "agent_id": agent_id, "agent_type": agent_type},
            agent_type=agent_type,
        )

    async def broadcast_memory_event(
        self,
        event_type: str,  # observation, claim, inference, contradiction
        data: dict[str, Any],
    ) -> int:
        """Broadcast a memory event (observation, claim, etc.)."""
        return await self.broadcast(
            self.CHANNEL_MEMORY_EVENT,
            {"event": event_type, **data},
        )

    async def broadcast_graph_update(
        self,
        operation: str,  # create_node, create_relationship, delete_node
        data: dict[str, Any],
    ) -> int:
        """Broadcast a graph update."""
        return await self.broadcast(
            self.CHANNEL_GRAPH_UPDATE,
            {"operation": operation, **data},
        )

    async def broadcast_system_stats(self, stats: dict[str, Any]) -> int:
        """Broadcast system statistics."""
        return await self.broadcast(self.CHANNEL_SYSTEM_STATS, stats)

    @property
    def connection_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    def get_connection_ids(self) -> list[str]:
        """Get all active connection IDs."""
        return list(self._connections.keys())
