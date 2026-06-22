"""FanoutDLQWriter — публикует envelope в несколько writers одновременно.

Применение:

* публикация и в Kafka, и в Postgres inbox (для replay при недоступности
  Kafka);
* публикация во все доступные backend'ы при шейdown'е (graceful drain).

Если хотя бы один writer успешно записал — fanout считается success.
Если все failed — re-raise последнюю exception.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("FanoutDLQWriter",)

logger = get_logger(__name__)


class FanoutDLQWriter:
    """Fan-out на несколько writers.

    Args:
        writers: список реализаций :class:`DLQWriter`.
        require_all: если ``True`` — exception при любой failure;
            если ``False`` (default) — успешно если хотя бы один записал.
    """

    def __init__(self, *, writers: list[Any], require_all: bool = False) -> None:
        if not writers:
            raise ValueError("FanoutDLQWriter requires at least one writer")
        self._writers = writers
        self._require_all = require_all

    async def write(self, envelope: DLQEnvelope) -> None:
        async with asyncio.TaskGroup() as tg:
            results = [
                tg.create_task(self._safe_write(w, envelope)) for w in self._writers
            ]

        outcomes = [r.result() for r in results]
        successes = [o for o in outcomes if o[0]]
        failures = [o for o in outcomes if not o[0]]

        if self._require_all and failures:
            _, last_exc = failures[-1]
            raise last_exc  # type: ignore[misc]
        if not successes:
            _, last_exc = failures[-1]
            logger.error(
                "dlq.fanout.all_failed",
                extra={"dlq_id": envelope.dlq_id, "failures": len(failures)},
            )
            raise last_exc  # type: ignore[misc]

    @staticmethod
    async def _safe_write(
        writer: Any, envelope: DLQEnvelope
    ) -> tuple[bool, BaseException | None]:
        try:
            await writer.write(envelope)
            return True, None
        except BaseException as exc:
            logger.warning(
                "dlq.fanout.writer_failed",
                extra={
                    "writer_class": type(writer).__name__,
                    "dlq_id": envelope.dlq_id,
                    "error": str(exc),
                },
            )
            return False, exc
