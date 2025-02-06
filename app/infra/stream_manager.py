import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

import asyncio
import json_tricks
from redis import RedisError

from app.config.services import RedisSettings
from app.config.settings import settings
from app.infra.redis import RedisClient, redis_client
from app.utils.logging_service import app_logger
from app.utils.utils import utilities


__all__ = (
    "stream_client",
    "StreamClient",
)


class StreamClient:
    """Service for event-driven architecture implementation using Redis Streams.

    Handles event publishing, consumption, retries, and dead letter queue management.

    Args:
        redis_client: Redis client instance
        main_stream: Name of the main event stream
        dlq_stream: Name of the dead letter queue stream
        max_retries: Maximum number of retry attempts for failed events
        ttl_hours: Time-to-live for events in hours

    Attributes:
        handlers: Registered event handlers mapping {event_type: handler}
        logger: Logger instance for service operations
    """

    def __init__(
        self,
        redis_client: RedisClient,
        settings: RedisSettings,
    ):
        self.redis_client = redis_client
        self.settings = settings
        self.initialize_attributes()

    def initialize_attributes(self):
        self.main_stream = self.settings.main_stream
        self.dlq_stream = self.settings.dlq_stream
        self.max_retries = self.settings.max_retries
        self.ttl = timedelta(hours=self.settings.ttl_hours)
        self.handlers: Dict[str, Callable] = {}
        self.logger = app_logger
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None

    async def register_handler(
        self, event_type: str, handler: Callable[[dict], Any]
    ) -> None:
        """Register event handler for specific event type.

        Args:
            event_type: Event type identifier
            handler: Callback function to handle the event. Can be async or sync.
        """
        self.handlers[event_type] = handler
        self.logger.debug(f"Registered handler for event type: {event_type}")

    async def publish_event(self, event_type: str, data: dict) -> str:
        """Publish new event to the main stream.

        Args:
            event_type: Type identifier for the event
            data: Payload data for the event

        Returns:
            Generated event ID

        Raises:
            RedisError: If event publishing fails
        """
        event_id = str(uuid.uuid4())
        event_data = {
            "event_id": event_id,
            "type": event_type,
            "data": json_tricks.dumps(
                data, extra_obj_encoders=[utilities.custom_json_encoder]
            ),
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + self.ttl).isoformat(),
            "retries": "0",
        }

        try:
            return await self.redis_client.stream_publish(
                stream=self.main_stream,
                data=event_data,
                max_len=10_000,  # Keep last 10k events by default
            )
        except RedisError:
            self.logger.error(
                "Failed to publish event {event_id}", exc_info=True
            )
            raise

    async def start_consumer(self) -> None:
        """Start event consumption from main stream and DLQ monitoring."""
        self._running = True
        self._consumer_task = asyncio.create_task(self._run_consumers())
        self.logger.info("Event service consumer started")

    async def stop_consumer(self) -> None:
        """Stop event consumption and DLQ monitoring."""
        self._running = False
        if self._consumer_task:
            await self._consumer_task
        self.logger.info("Event service consumer stopped")

    async def _run_consumers(self) -> None:
        """Run main consumer and DLQ monitor in parallel."""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._consume_main_stream())
            tg.create_task(self._monitor_dlq())

    async def _consume_main_stream(self) -> None:
        """Main event consumption loop with error handling and retries."""
        last_id = "$"  # Start listening for new events

        while self._running:
            try:
                events = await self.redis_client.stream_read(
                    stream=self.main_stream,
                    last_id=last_id,
                    block_ms=5000,
                    count=10,
                )
                if events:
                    for event in events:
                        event = await utilities.decode_bytes(data=event)

                        await self._process_single_event(event)
                        last_id = event["id"]

            except RedisError:
                self.logger.error("Redis error in consumer", exc_info=True)
                await asyncio.sleep(5)
            except Exception:
                self.logger.error("Unexpected processing error", exc_info=True)
                await asyncio.sleep(1)

    async def _process_single_event(self, event: dict) -> None:
        """Process individual event with expiration check and error handling."""
        event_data = event["data"]

        self.logger.info(f"Processing event: {event}")

        try:
            if datetime.now() > datetime.fromisoformat(
                event_data["expires_at"]
            ):
                await self._handle_expired_event(event)
                return

            await self._execute_handler(event_data)
            await self._acknowledge_event(event["id"])

        except Exception as exc:
            await self._handle_processing_error(event, str(exc))

    async def _execute_handler(self, event_data: dict) -> None:
        """Execute registered handler for the event type."""
        handler = self.handlers.get(event_data["type"])
        if not handler:
            self.logger.error(
                f"No handler for event type: {event_data["type"]}"
            )
            raise ValueError(
                f"No handler for event type: {event_data["type"]}"
            )

        data = event_data["data"]

        if asyncio.iscoroutinefunction(handler):
            await handler(data)
        else:
            handler(data)

    async def _handle_expired_event(self, event: dict) -> None:
        """Move expired event to DLQ with TTL metadata."""
        await self.redis_client.stream_move(
            source_stream=self.main_stream,
            dest_stream=self.dlq_stream,
            event_id=event["id"],
            additional_data={
                "error": "Event TTL expired",
                "failed_at": datetime.now().isoformat(),
            },
        )
        self.logger.warning(f"Moved expired event to DLQ: {event['id']}")

    async def _handle_processing_error(self, event: dict, error: str) -> None:
        """Handle event processing errors and retry logic."""

        current_retries = int(event["data"]["retries"])
        event_id = event["data"]["event_id"]

        if current_retries <= self.max_retries:
            success = await self.redis_client.stream_retry_event(
                stream=self.main_stream, event_id=event["id"], ttl=self.ttl
            )
            if success:
                self.logger.info(
                    f"Retrying event {event_id} (attempt {current_retries + 1})"
                )
                return

        await self._move_to_dlq(event, error)
        self.logger.error(f"Permanent failure for event {event_id}: {error}")

    async def _move_to_dlq(self, event: dict, error: str) -> None:
        """Move failed event to DLQ with error metadata."""
        await self.redis_client.stream_move(
            source_stream=self.main_stream,
            dest_stream=self.dlq_stream,
            event_id=event["id"],
            additional_data={
                "error": error,
                "failed_at": datetime.now().isoformat(),
                "final_retry_count": event["data"].get("retries", 0),
            },
        )
        self.logger.info("Successful to move failed event to DLQ")

    async def _acknowledge_event(self, event_id: str) -> None:
        """Prepare acknowledge successful event processing."""
        try:
            await self.redis_client._client.xdel(self.main_stream, event_id)
            self.logger.info(
                f"Acknowledge successful event processing: {event_id}"
            )
        except RedisError as exc:
            self.logger.warning(f"Failed to ack event {event_id}: {str(exc)}")

    async def _monitor_dlq(self) -> None:
        """Monitor dead letter queue for logging and alerting."""
        last_id = "$"

        while self._running:
            try:
                events = await self.redis_client.stream_read(
                    stream=self.dlq_stream,
                    last_id=last_id,
                    block_ms=10000,
                    count=10,
                )

                for event in events:
                    event = utilities.decode_bytes(data=event)
                    event_data = event["data"]
                    self.logger.error(
                        f"DLQ Entry: {event_data['event_id']} | "
                        f"Error: {event_data.get('error', 'Unknown')} | "
                        f"Retries: {event_data.get('final_retry_count', 0)}"
                    )
                    last_id = event["id"]

            except RedisError:
                self.logger.error("DLQ monitoring error", exc_info=True)
                await asyncio.sleep(5)
            except Exception:
                self.logger.error("Unexpected DLQ error", exc_info=True)
                await asyncio.sleep(1)

    async def get_operational_stats(self) -> Dict[str, Any]:
        """Get current statistics for main stream and DLQ.

        Returns:
            Dictionary with stream lengths and recent activity

        Raises:
            RedisError: If statistics retrieval fails
        """
        try:
            return {
                "main_stream": await self.redis_client.stream_get_stats(
                    self.main_stream
                ),
                "dlq_stream": await self.redis_client.stream_get_stats(
                    self.dlq_stream
                ),
            }
        except RedisError:
            self.logger.error("Failed to get operational stats", exc_info=True)
            raise


stream_client = StreamClient(
    settings=settings.redis, redis_client=redis_client
)
