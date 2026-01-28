"""Agent registry and status management.

Tracks agent registration, heartbeats, and push rate configuration.
Uses Redis for persistent storage with TTL-based stale detection.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis key prefixes
KEY_STATUS = "agent:status"
KEY_REGISTRY = "agent:registry"
KEY_CONFIG = "agent:config"
KEY_ACTIVE = "agent:active"


@dataclass
class AgentStatus:
    """Full agent status for heartbeat reporting."""

    # Identity
    agent_id: str
    agent_type: str
    tags: list[str] = field(default_factory=list)

    # Timing
    timestamp: str = ""
    started_at: str = ""
    uptime_seconds: float = 0.0

    # Operational
    status: str = "running"  # running, idle, error, stopping
    last_action: str = ""
    last_action_at: str | None = None

    # Metrics
    items_processed: int = 0
    queue_depth: int = 0
    processing_time_avg_ms: float = 0.0
    error_count: int = 0

    # Resources
    memory_mb: float = 0.0

    # Push rate (from config)
    push_interval_seconds: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentStatus:
        return cls(**data)


@dataclass
class AgentRegistration:
    """Agent registration info (persistent)."""

    agent_id: str
    agent_type: str
    tags: list[str]
    hostname: str
    pid: int
    registered_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRegistration:
        return cls(**data)


class AgentRegistry:
    """Redis-backed agent registry and status tracker."""

    DEFAULT_PUSH_INTERVAL = 30.0
    STALE_MULTIPLIER = 3  # 3x push interval = stale
    DEAD_MULTIPLIER = 5  # 5x push interval = dead

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._status_listeners: list[Any] = []

    async def register(
        self,
        agent_type: str,
        tags: list[str] | None = None,
        hostname: str = "unknown",
        pid: int = 0,
    ) -> tuple[str, float]:
        """Register a new agent. Returns (agent_id, push_interval)."""
        agent_id = f"{agent_type}-{uuid.uuid4().hex[:8]}"
        registration = AgentRegistration(
            agent_id=agent_id,
            agent_type=agent_type,
            tags=tags or [],
            hostname=hostname,
            pid=pid,
            registered_at=datetime.utcnow().isoformat() + "Z",
        )

        # Store registration
        await self._redis.hset(
            KEY_REGISTRY, agent_id, json.dumps(registration.to_dict())
        )

        # Add to active set
        await self._redis.sadd(KEY_ACTIVE, agent_id)

        # Get push interval config
        push_interval = await self.get_push_interval(agent_id, agent_type, tags or [])

        logger.info(f"Registered agent {agent_id} (type={agent_type}, interval={push_interval}s)")
        return agent_id, push_interval

    async def deregister(self, agent_id: str) -> bool:
        """Deregister an agent."""
        # Remove from active set
        await self._redis.srem(KEY_ACTIVE, agent_id)

        # Remove status
        await self._redis.hdel(KEY_STATUS, agent_id)

        # Keep registration for history (optional: delete it)
        # await self._redis.hdel(KEY_REGISTRY, agent_id)

        logger.info(f"Deregistered agent {agent_id}")
        return True

    async def update_status(self, status: AgentStatus) -> float:
        """Update agent status. Returns current push interval."""
        # Get registration for tags
        reg_data = await self._redis.hget(KEY_REGISTRY, status.agent_id)
        tags = []
        if reg_data:
            reg = AgentRegistration.from_dict(json.loads(reg_data))
            tags = reg.tags

        # Get current push interval
        push_interval = await self.get_push_interval(
            status.agent_id, status.agent_type, tags
        )
        status.push_interval_seconds = push_interval

        # Store status with TTL
        ttl = int(push_interval * self.DEAD_MULTIPLIER)
        await self._redis.hset(KEY_STATUS, status.agent_id, json.dumps(status.to_dict()))

        # Ensure in active set
        await self._redis.sadd(KEY_ACTIVE, status.agent_id)

        # Notify listeners
        await self._notify_status_update(status)

        return push_interval

    async def get_status(self, agent_id: str) -> AgentStatus | None:
        """Get current status for an agent."""
        data = await self._redis.hget(KEY_STATUS, agent_id)
        if not data:
            return None
        return AgentStatus.from_dict(json.loads(data))

    async def list_agents(
        self,
        agent_type: str | None = None,
        tag: str | None = None,
        include_dead: bool = False,
    ) -> list[AgentStatus]:
        """List all agents, optionally filtered by type or tag.

        Dead agents are excluded by default and cleaned up from Redis.
        """
        agents = []
        dead_ids = []
        all_status = await self._redis.hgetall(KEY_STATUS)

        for agent_id, data in all_status.items():
            status = AgentStatus.from_dict(json.loads(data))

            # Check if stale/dead
            status = await self._check_liveness(status)

            # Collect dead agents for cleanup
            if status.status == "dead":
                dead_ids.append(agent_id)
                if not include_dead:
                    continue

            # Filter by type
            if agent_type and status.agent_type != agent_type:
                continue

            # Filter by tag
            if tag and tag not in status.tags:
                continue

            agents.append(status)

        # Clean up dead agents from Redis
        if dead_ids:
            await self._cleanup_dead(dead_ids)

        return agents

    async def _cleanup_dead(self, agent_ids: list[str]) -> None:
        """Remove dead agents from Redis."""
        for agent_id in agent_ids:
            await self._redis.hdel(KEY_STATUS, agent_id)
            await self._redis.hdel(KEY_REGISTRY, agent_id)
            await self._redis.srem(KEY_ACTIVE, agent_id)
            logger.info(f"Cleaned up dead agent {agent_id}")

    async def _check_liveness(self, status: AgentStatus) -> AgentStatus:
        """Check if agent is stale or dead based on last heartbeat."""
        if not status.timestamp:
            return status

        try:
            last_seen = datetime.fromisoformat(status.timestamp.rstrip("Z"))
            elapsed = (datetime.utcnow() - last_seen).total_seconds()
            interval = status.push_interval_seconds

            if elapsed > interval * self.DEAD_MULTIPLIER:
                status.status = "dead"
            elif elapsed > interval * self.STALE_MULTIPLIER:
                status.status = "stale"
        except (ValueError, TypeError):
            pass

        return status

    # -- Push rate configuration --

    async def get_push_interval(
        self,
        agent_id: str,
        agent_type: str,
        tags: list[str],
    ) -> float:
        """Get push interval for an agent (resolution order: agent > tag > type > default)."""

        # 1. Per-agent config
        agent_config = await self._redis.get(f"{KEY_CONFIG}:{agent_id}:push_interval")
        if agent_config:
            return float(agent_config)

        # 2. Per-tag config (lowest interval wins)
        tag_intervals = []
        for tag in tags:
            tag_config = await self._redis.get(f"{KEY_CONFIG}:tag:{tag}:push_interval")
            if tag_config:
                tag_intervals.append(float(tag_config))
        if tag_intervals:
            return min(tag_intervals)

        # 3. Per-type config
        type_config = await self._redis.get(f"{KEY_CONFIG}:type:{agent_type}:push_interval")
        if type_config:
            return float(type_config)

        # 4. Global default
        default_config = await self._redis.get(f"{KEY_CONFIG}:default:push_interval")
        if default_config:
            return float(default_config)

        return self.DEFAULT_PUSH_INTERVAL

    async def set_push_interval_for_agent(self, agent_id: str, interval: float) -> None:
        """Set push interval for a specific agent."""
        await self._redis.set(f"{KEY_CONFIG}:{agent_id}:push_interval", str(interval))

    async def set_push_interval_for_type(self, agent_type: str, interval: float) -> None:
        """Set push interval for an agent type."""
        await self._redis.set(f"{KEY_CONFIG}:type:{agent_type}:push_interval", str(interval))

    async def set_push_interval_for_tag(self, tag: str, interval: float) -> None:
        """Set push interval for a tag."""
        await self._redis.set(f"{KEY_CONFIG}:tag:{tag}:push_interval", str(interval))

    async def set_default_push_interval(self, interval: float) -> None:
        """Set global default push interval."""
        await self._redis.set(f"{KEY_CONFIG}:default:push_interval", str(interval))

    # -- Listeners for WebSocket broadcasting --

    def add_status_listener(self, callback) -> None:
        """Add a callback to be notified on status updates."""
        self._status_listeners.append(callback)

    def remove_status_listener(self, callback) -> None:
        """Remove a status listener."""
        if callback in self._status_listeners:
            self._status_listeners.remove(callback)

    async def _notify_status_update(self, status: AgentStatus) -> None:
        """Notify all listeners of a status update."""
        for listener in self._status_listeners:
            try:
                await listener(status)
            except Exception:
                logger.exception("Error in status listener")

    async def close(self) -> None:
        """Close Redis connection."""
        await self._redis.close()


class InMemoryAgentRegistry:
    """In-memory fallback for when Redis is not available (dev/test)."""

    DEFAULT_PUSH_INTERVAL = 30.0
    STALE_MULTIPLIER = 3
    DEAD_MULTIPLIER = 5

    def __init__(self) -> None:
        self._registrations: dict[str, AgentRegistration] = {}
        self._statuses: dict[str, AgentStatus] = {}
        self._config: dict[str, float] = {}
        self._status_listeners: list[Any] = []

    async def register(
        self,
        agent_type: str,
        tags: list[str] | None = None,
        hostname: str = "unknown",
        pid: int = 0,
    ) -> tuple[str, float]:
        agent_id = f"{agent_type}-{uuid.uuid4().hex[:8]}"
        self._registrations[agent_id] = AgentRegistration(
            agent_id=agent_id,
            agent_type=agent_type,
            tags=tags or [],
            hostname=hostname,
            pid=pid,
            registered_at=datetime.utcnow().isoformat() + "Z",
        )
        push_interval = await self.get_push_interval(agent_id, agent_type, tags or [])
        return agent_id, push_interval

    async def deregister(self, agent_id: str) -> bool:
        self._statuses.pop(agent_id, None)
        return True

    async def update_status(self, status: AgentStatus) -> float:
        tags = []
        if status.agent_id in self._registrations:
            tags = self._registrations[status.agent_id].tags
        push_interval = await self.get_push_interval(
            status.agent_id, status.agent_type, tags
        )
        status.push_interval_seconds = push_interval
        self._statuses[status.agent_id] = status
        await self._notify_status_update(status)
        return push_interval

    async def get_status(self, agent_id: str) -> AgentStatus | None:
        return self._statuses.get(agent_id)

    async def list_agents(
        self,
        agent_type: str | None = None,
        tag: str | None = None,
    ) -> list[AgentStatus]:
        agents = []
        for status in self._statuses.values():
            if agent_type and status.agent_type != agent_type:
                continue
            if tag and tag not in status.tags:
                continue
            agents.append(status)
        return agents

    async def get_push_interval(
        self,
        agent_id: str,
        agent_type: str,
        tags: list[str],
    ) -> float:
        if f"agent:{agent_id}" in self._config:
            return self._config[f"agent:{agent_id}"]
        for tag in tags:
            if f"tag:{tag}" in self._config:
                return self._config[f"tag:{tag}"]
        if f"type:{agent_type}" in self._config:
            return self._config[f"type:{agent_type}"]
        return self._config.get("default", self.DEFAULT_PUSH_INTERVAL)

    async def set_push_interval_for_agent(self, agent_id: str, interval: float) -> None:
        self._config[f"agent:{agent_id}"] = interval

    async def set_push_interval_for_type(self, agent_type: str, interval: float) -> None:
        self._config[f"type:{agent_type}"] = interval

    async def set_push_interval_for_tag(self, tag: str, interval: float) -> None:
        self._config[f"tag:{tag}"] = interval

    async def set_default_push_interval(self, interval: float) -> None:
        self._config["default"] = interval

    def add_status_listener(self, callback) -> None:
        self._status_listeners.append(callback)

    def remove_status_listener(self, callback) -> None:
        if callback in self._status_listeners:
            self._status_listeners.remove(callback)

    async def _notify_status_update(self, status: AgentStatus) -> None:
        for listener in self._status_listeners:
            try:
                await listener(status)
            except Exception:
                logger.exception("Error in status listener")

    async def close(self) -> None:
        pass
