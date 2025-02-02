import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional

import asyncio
from redis import RedisError

from app.infra.redis import RedisClient, redis_client


__all__ = (
    "EventClient",
    "event_client",
)


class EventClient:
    def __init__(
        self,
        redis_client: RedisClient,
        main_stream: str = "events_stream",
        dlq_stream: str = "events_dlq",
        max_retries: int = 3,
        ttl_hours: int = 1,
    ):
        self.redis_client = redis_client
        self.main_stream = main_stream
        self.dlq_stream = dlq_stream
        self.max_retries = max_retries
        self.ttl = timedelta(hours=ttl_hours)
        self.handlers: Dict[str, Callable] = {}
        self._running = False
        self._dlq_running = False
        self.logger = logging.getLogger(self.__class__.__name__)
        self._main_task: Optional[asyncio.Task] = None
        self._dlq_task: Optional[asyncio.Task] = None

    def register_handler(
        self, event_type: str, handler: Callable[[dict], None]
    ) -> None:
        self.handlers[event_type] = handler

    async def publish_event(self, event_type: str, data: dict) -> str:
        event_id = str(uuid.uuid4())
        event = {
            "event_id": event_id,
            "type": event_type,
            "data": json.dumps(data),
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + self.ttl).isoformat(),
            "retries": "0",
        }

        try:
            async with self.redis_client.connection() as conn:
                await conn.xadd(self.main_stream, event, id="*")
            self.logger.debug(f"Event published: {event_id}")
            return event_id
        except RedisError as e:
            self.logger.error(f"Failed to publish event: {str(e)}")
            raise

    async def _move_to_dlq(self, event: dict, error: str) -> None:
        dlq_event = {
            **event,
            "error": error,
            "failed_at": datetime.now().isoformat(),
            "original_stream": self.main_stream,
        }

        try:
            async with self.redis_client.connection() as conn:
                await conn.xadd(self.dlq_stream, dlq_event, id="*")
                await conn.xdel(self.main_stream, event["event_id"])
            self.logger.warning(f"Moved to DLQ: {event['event_id']}")
        except RedisError as e:
            self.logger.error(f"Failed to move to DLQ: {str(e)}")

    async def _handle_event(self, event: dict) -> None:
        try:
            event_type = event["type"]
            handler = self.handlers.get(event_type)

            if not handler:
                raise ValueError(f"No handler for event type: {event_type}")

            data = json.loads(event["data"])
            if asyncio.iscoroutinefunction(handler):
                await handler(data)
            else:
                handler(data)

            async with self.redis_client.connection() as conn:
                await conn.xdel(self.main_stream, event["event_id"])

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            await self._move_to_dlq(event, f"Processing error: {str(e)}")
        except Exception as e:
            current_retries = int(event.get("retries", 0))
            if current_retries < self.max_retries:
                await self._retry_event(event, current_retries)
            else:
                await self._move_to_dlq(
                    event, f"Max retries exceeded: {str(e)}"
                )

    async def _retry_event(self, event: dict, retries: int) -> None:
        try:
            new_event = {
                **event,
                "retries": str(retries + 1),
                "expires_at": (datetime.now() + self.ttl).isoformat(),
            }
            async with self.redis_client.connection() as conn:
                await conn.xadd(self.main_stream, new_event, id="*")
                await conn.xdel(self.main_stream, event["event_id"])
        except RedisError as e:
            self.logger.error(f"Retry failed: {str(e)}")

    async def _event_listener(self) -> None:
        last_id = "$"
        while self._running:
            try:
                async with self.redis_client.connection() as conn:
                    events = await conn.xread(
                        streams={self.main_stream: last_id},
                        count=10,
                        block=5000,
                    )

                if not events:
                    continue

                for stream, stream_events in events:
                    for event_id, event in stream_events:
                        last_id = event_id
                        if datetime.now() > datetime.fromisoformat(
                            event["expires_at"]
                        ):
                            await self._move_to_dlq(event, "TTL expired")
                            continue
                        await self._handle_event(event)

            except RedisError as e:
                self.logger.error(f"Redis error: {str(e)}")
                await asyncio.sleep(5)
            except Exception as e:
                self.logger.error(f"Unexpected error: {str(e)}")
                await asyncio.sleep(1)

    async def _dlq_listener(self) -> None:
        last_id = "$"
        while self._dlq_running:
            try:
                async with self.redis_client.connection() as conn:
                    events = await conn.xread(
                        streams={self.dlq_stream: last_id},
                        count=10,
                        block=10000,
                    )

                if events:
                    for stream, stream_events in events:
                        for event_id, event in stream_events:
                            last_id = event_id
                            self.logger.error(
                                f"DLQ Entry: {event['event_id']} | "
                                f"Error: {event.get('error', 'Unknown')} | "
                                f"Failed at: {event.get('failed_at', '')}"
                            )
            except Exception as e:
                self.logger.error(f"DLQ listener error: {str(e)}")
                await asyncio.sleep(5)

    async def start(self) -> None:
        self._running = True
        self._dlq_running = True

        self._main_task = asyncio.create_task(self._event_listener())
        self._dlq_task = asyncio.create_task(self._dlq_listener())
        self.logger.info("Event manager started")

    async def stop(self) -> None:
        self._running = False
        self._dlq_running = False

        if self._main_task:
            await self._main_task
        if self._dlq_task:
            await self._dlq_task

        self.logger.info("Event manager stopped")

    async def get_dlq_stats(self) -> dict:
        try:
            async with self.redis_client.connection() as conn:
                return {
                    "count": await conn.xlen(self.dlq_stream),
                    "last_errors": [
                        {**event}
                        for event in await conn.xrevrange(
                            self.dlq_stream, count=5
                        )
                    ],
                }
        except RedisError as e:
            self.logger.error(f"Failed to get DLQ stats: {str(e)}")
            return {}


event_client = EventClient(redis_client=redis_client)
