"""Redis pub/sub event bus for observation and claim notifications.

Agents subscribe to events instead of blind polling. The API server
publishes events after each observe() or claim() call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

CHANNEL_OBSERVATION = "memory:events:observation"
CHANNEL_CLAIM = "memory:events:claim"


class EventBus:
    """Redis-backed event bus for memory system notifications."""

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def publish_observation(self, obs_data: dict[str, Any]) -> None:
        """Publish an observation event."""
        await self._redis.publish(
            CHANNEL_OBSERVATION, json.dumps(obs_data, default=str)
        )

    async def publish_claim(self, claim_data: dict[str, Any]) -> None:
        """Publish a claim event."""
        await self._redis.publish(
            CHANNEL_CLAIM, json.dumps(claim_data, default=str)
        )

    async def subscribe(
        self, *channels: str
    ) -> aioredis.client.PubSub:
        """Subscribe to one or more channels. Returns a PubSub object."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*channels)
        return pubsub

    async def listen(
        self, *channels: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed event data from the given channels."""
        pubsub = await self.subscribe(*channels)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    data["_channel"] = message["channel"]
                    yield data
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in event: {message['data']}")
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.close()

    async def close(self) -> None:
        await self._redis.close()
