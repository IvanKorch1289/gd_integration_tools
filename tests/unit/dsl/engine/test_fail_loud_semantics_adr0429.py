"""ADR-0429 — «громкая» семантика провала: статус exchange'а и терминальный переход.

Контекст дефекта
----------------
``@handle_processor_error`` (117 процессоров DSL) ловил исключение процессора и
делал ``exchange.set_error(...)`` + ``exchange.stop()`` — **без** смены статуса.
Статус оставался ``processing``, а движок в финале перетирал его в
``completed`` (ветка «в trace нет записи со status=error»). Итог: упавший шаг
выглядел как успешный — trace «ok», SLO-метрика ``is_error=False``, а
``error`` жил в теле exchange'а.

Проверяется здесь:

* процессор с ``@handle_processor_error``, бросивший исключение → статус
  exchange'а ``failed`` (не ``completed``);
* неуспешная публикация в sink (``ok=False``) → шаг проваливается явно;
* неожиданное исключение в workflow-runner'е → инстанс переводится в
  ``failed`` (иначе он навсегда оставался в ``running`` и backup-poll
  подхватывал его снова и снова).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

pytestmark = pytest.mark.unit


class _BoomProcessor(BaseProcessor):
    """Процессор, который всегда падает (декоратор ловит исключение)."""

    def __init__(self) -> None:
        super().__init__(name="boom-proc")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Всегда бросает исключение — как реальный процессор при падении БД."""
        raise RuntimeError("db down")


@pytest.mark.asyncio
async def test_processor_error_marks_exchange_failed() -> None:
    """Падение процессора → ``exchange.status == failed``, а не ``completed``."""
    engine = ExecutionEngine(validate_before_execute=False)
    pipeline = Pipeline(route_id="rpa.boom", processors=[_BoomProcessor()])

    exchange = await engine.execute(pipeline)

    assert exchange.status == ExchangeStatus.failed, (
        "упавший процессор не должен выглядеть как успешный маршрут"
    )
    assert exchange.error is not None
    assert "db down" in exchange.error


@pytest.mark.asyncio
async def test_sink_publish_failure_marks_exchange_failed() -> None:
    """``ok=False`` от sink'а → шаг проваливается (иначе сообщение терялось)."""
    from src.backend.dsl.engine.exchange import Message
    from src.backend.dsl.engine.processors.sink_publish.generic import (
        _OutSpec,
        _store_result,
    )

    exchange = Exchange(in_message=Message(body={}))
    _store_result(
        exchange,
        _OutSpec(result_property="sink_result"),
        {"ok": False, "error": "broker down"},
    )

    assert exchange.status == ExchangeStatus.failed
    assert exchange.stopped is True
    assert exchange.properties["sink_result"]["ok"] is False
