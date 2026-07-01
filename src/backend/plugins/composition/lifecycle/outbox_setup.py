"""S64 W3 / S111 W2+ — outbox dispatcher registration extracted from startup.py.

Содержит ``register_outbox_dispatcher()`` — feature-flag-gated cutover между
legacy APScheduler worker и новым multi-instance safe OutboxDispatcher.

Ре-экспортируется из lifespan.py как ``_register_outbox_dispatcher`` для
backward compatibility (тест ``test_outbox_dispatcher_cutover.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("application.startup")

__all__ = ("register_outbox_dispatcher",)


async def register_outbox_dispatcher(app: FastAPI) -> None:
    """S64 W3 — outbox dispatcher cutover: legacy worker ↔ new dispatcher.

    Под feature flag-ом ``outbox_settings.enabled`` (default OFF):

    * **False** (default) → ``start_outbox_worker()`` (legacy APScheduler,
      не multi-instance safe, см. ``outbox_worker.py``).
    * **True** → ``start_outbox_dispatcher()`` (S64 W1+W3: multi-instance
      safe через ``claim_pending`` с advisory lock + FOR UPDATE SKIP LOCKED).

    Adapter-ы (claim_pending → OutboxEvent, OutboxEvent → mark_sent)
    инкапсулированы внутри этой функции. ``_outbox_msg_id`` кодируется
    в ``correlation_id`` (формат ``outbox_msg_id:<N>``) для ack-mapping.

    **NB**: исключения НЕ raise'ятся наружу — outbox не блокирует
    startup (best-effort), аналогично legacy поведению.
    """
    try:
        from src.backend.core.config.services.outbox import outbox_settings

        if outbox_settings.enabled:
            # S64 W3: новый OutboxDispatcher path (multi-instance safe).
            # Worker ID: HOSTNAME env (K8s pod name) → socket.gethostname()
            import os as _os
            import socket as _socket
            from collections.abc import Sequence as _Sequence
            from uuid import uuid4

            from src.backend.core.messaging.outbox import FakeOutbox, OutboxEvent
            from src.backend.infrastructure.messaging.outbox.lifecycle import (
                start_outbox_dispatcher,
            )
            from src.backend.infrastructure.repositories import outbox as outbox_repo
            from src.backend.infrastructure.workflow.outbox_worker import _publish

            _worker_id = _os.environ.get("HOSTNAME") or _socket.gethostname()

            def _topic_to_transport(topic: str) -> str:
                """``kafka:orders.created`` → ``kafka`` для OutboxEvent.transport."""
                if ":" in topic:
                    proto = topic.split(":", 1)[0].lower()
                    if proto in ("kafka", "rabbit", "redis", "nats", "http"):
                        return proto
                return "kafka"  # default (legacy worker)

            async def _pending_source(limit: int) -> _Sequence[OutboxEvent]:
                """Adapter: claim_pending (W1) → OutboxEvent list.

                Использует S64 W1 claim_pending (advisory lock +
                FOR UPDATE SKIP LOCKED) → multi-instance safe.
                Кодирует ``outbox_msg_id:<N>`` в ``correlation_id``
                для последующего ack (OutboxEvent не имеет ``id``/``headers``).
                """
                msgs = await outbox_repo.claim_pending(
                    limit=limit, worker_id=_worker_id
                )
                result: list[OutboxEvent] = []
                for m in msgs:
                    # Prefer original correlation_id from headers;
                    # else use the outbox_msg_id marker (для ack).
                    original_cid = (m.headers or {}).get("correlation_id")
                    cid = original_cid or f"outbox_msg_id:{m.id}"
                    result.append(
                        OutboxEvent(
                            event_id=uuid4().hex,
                            transport=_topic_to_transport(m.topic),
                            action=m.topic,
                            payload=m.payload,
                            correlation_id=cid,
                        )
                    )
                return result

            async def _ack(event: OutboxEvent) -> None:
                """Adapter: OutboxEvent → mark_sent (по ``correlation_id``).

                Приоритет: если ``correlation_id`` начинается с
                ``outbox_msg_id:`` — это marker, ack по msg.id.
                Иначе (original CID) — нет msg.id, skip ack (safety).
                """
                cid = event.correlation_id or ""
                if cid.startswith("outbox_msg_id:"):
                    raw_id = cid.removeprefix("outbox_msg_id:")
                    try:
                        await outbox_repo.mark_sent(int(raw_id))
                    except (ValueError, TypeError):
                        return

            async def _deliverer(event: OutboxEvent) -> None:
                """Adapter: reuse legacy ``_publish`` (K8/F2 Wave 2)."""
                await _publish(
                    event.action,
                    event.payload,
                    {"correlation_id": event.correlation_id or ""},
                )

            await start_outbox_dispatcher(
                app=app,
                backend=FakeOutbox(),
                pending_source=_pending_source,
                ack=_ack,
                deliverer=_deliverer,
            )
            _logger.info(
                "S64 W3: OutboxDispatcher started (worker_id=%s, "
                "outbox_settings.enabled=True)",
                _worker_id,
            )
        else:
            # Legacy APScheduler worker (default, backwards-compat).
            from src.backend.infrastructure.workflow.outbox_worker import (
                start_outbox_worker,
            )

            start_outbox_worker(interval_seconds=5, batch_size=100)
            _logger.info(
                "Legacy outbox worker registered "
                "(outbox_settings.enabled=False, S64 W3 cutover not active)."
            )
    except Exception as exc:
        # Outbox-worker не критичен для базовой работоспособности
        # (например, dev_light без RabbitMQ) — startup продолжается.
        _logger.warning("Outbox worker registration skipped: %s", exc)
