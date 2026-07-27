"""HITL Pub/Sub consumer (S178 HITL-1 closeout — ARC-010).

Background consumer для cross-instance HITL signal notification.
Подписывается на wildcard Redis channel ``hitl:resolved:*`` и
обрабатывает входящие pub/sub messages путём вызова
``on_message`` callback (caller-provided).

Дизайн (Ponytail + R-V15-11 leak prevention):

* **Lazy-import**: ``get_redis_client`` импортируется внутри
  :meth:`start` (per-instance use, не на module load).
* **Best-effort**: если Redis недоступен или ``psubscribe`` падает,
  :meth:`start` возвращает ``False`` и логирует warning. Никаких
  raises — caller продолжает работать на in-memory only.
* **TaskRegistry-agnostic**: создаёт локальный ``asyncio.Task``,
  хранит reference, гарантирует cleanup в :meth:`stop`.
* **Wildcard subscribe** через ``psubscribe`` — не нужно знать
  ``tenant_id`` заранее. Caller решает фильтрацию через callback.
* **JSON parsing** с graceful fallback: битые сообщения → log + skip.
* **Stop semantics**: ``stop()`` отменяет task, ждёт завершения
  (timeout 5s), закрывает pubsub handle.

Example::

    consumer = HitlPubSubConsumer()

    async def on_resolved(message: dict) -> None:
        if my_store.get(message["signal_id"]):
            my_store.mark_resolved(message["signal_id"], ...)

    started = await consumer.start(on_message=on_resolved)
    if started:
        try:
            # ... do work ...
        finally:
            await consumer.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from src.backend.services.workflows.hitl_pubsub import HITL_CHANNEL_PREFIX

__all__ = ("HitlPubSubConsumer",)

_logger = logging.getLogger("services.workflows.hitl_pubsub_consumer")

# S178: timeout для graceful stop.
_STOP_TIMEOUT_S: float = 5.0


class HitlPubSubConsumer:
    """Background consumer для HITL ``hitl:resolved:*`` pub/sub channel.

    Attributes:
        started: ``True`` если psubscribe task запущен успешно.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._pubsub: Any | None = None
        self._on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._stopped = asyncio.Event()

    @property
    def started(self) -> bool:
        """Check if consumer task is alive.

        Returns:
            ``True`` если psubscribe task running, ``False`` otherwise.
        """
        return self._task is not None and not self._task.done()

    async def start(
        self,
        *,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        """Start psubscribe + background task.

        Args:
            on_message: Async callback, вызывается на каждый
                распарсенный JSON message. Caller отвечает за
                фильтрацию по ``signal_id``/``tenant_id``.

        Returns:
            ``True`` если subscribe task запущен, ``False`` если
            Redis недоступен или subscription упал (best-effort,
            caller продолжает работу с in-memory).
        """
        if self.started:
            _logger.debug("HitlPubSubConsumer.start called while already running")
            return True

        try:
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client,
            )

            wrapper = get_redis_client()
            raw = await wrapper.get_client("cache")
            pubsub = raw.pubsub()
            channel_pattern = f"{HITL_CHANNEL_PREFIX}:*"
            await pubsub.psubscribe(channel_pattern)
            self._pubsub = pubsub
            self._on_message = on_message
            self._stopped.clear()
            self._task = asyncio.create_task(
                self._listen_loop(),
                name="hitl-pubsub-consumer",
            )
            _logger.debug(
                "HitlPubSubConsumer started, pattern=%s", channel_pattern
            )
            return True
        except Exception as exc:
            # Ponytail: Redis недоступен → caller продолжает работать.
            _logger.warning(
                "hitl.pubsub.consumer_start_failed: %s "
                "(caller continues on in-memory only)",
                exc,
            )
            self._pubsub = None
            self._on_message = None
            return False

    async def _listen_loop(self) -> None:
        """Async iterator по pubsub.listen() до ``stop()``.

        Каждое ``message`` event → JSON parse → ``on_message()``.
        Type != ``message`` (subscribe confirmation) → ignore.
        """
        if self._pubsub is None:
            return
        try:
            async for msg in self._pubsub.listen():
                if self._stopped.is_set():
                    break
                if msg.get("type") != "pmessage":
                    continue
                data = msg.get("data")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8", errors="replace")
                if not isinstance(data, str):
                    continue
                try:
                    payload = json.loads(data)
                except (TypeError, json.JSONDecodeError) as exc:
                    _logger.warning(
                        "hitl.pubsub.bad_message data=%r: %s", data, exc
                    )
                    continue
                if not isinstance(payload, dict):
                    continue
                callback = self._on_message
                if callback is None:
                    break
                try:
                    await callback(payload)
                except Exception as exc:
                    # Ponytail: caller-side error → log + continue (не убиваем loop).
                    _logger.warning(
                        "hitl.pubsub.consumer_callback_failed "
                        "signal_id=%s: %s",
                        payload.get("signal_id", "<unknown>"),
                        exc,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.exception("hitl.pubsub.consumer_loop_crashed: %s", exc)
        finally:
            self._stopped.set()

    async def stop(self) -> None:
        """Cancel task + close pubsub (graceful, with timeout).

        Idempotent: можно вызвать несколько раз.
        """
        task = self._task
        pubsub = self._pubsub
        self._task = None
        self._pubsub = None
        self._on_message = None

        if task is not None and not task.done():
            self._stopped.set()
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                _logger.warning(
                    "hitl.pubsub.consumer_stop_timeout task=%s", task.get_name()
                )
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _logger.warning(
                    "hitl.pubsub.consumer_stop_error: %s", exc
                )

        if pubsub is not None:
            try:
                await pubsub.close()
            except Exception as exc:
                _logger.warning("hitl.pubsub.close_failed: %s", exc)
