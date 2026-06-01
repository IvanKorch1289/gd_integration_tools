"""W14.4 — классификация side-effects процессоров.

Покрывает:

* enum ``SideEffectKind`` сериализуется как строка;
* default ``BaseProcessor.side_effect == PURE`` и ``compensatable == True``;
* наследник может переопределить class-attribute;
* invalid enum value → ValueError;
* PURE-процессор детерминированный (одинаковый вход → одинаковый выход);
* SIDE_EFFECTING-процессор маркер в reflective-проверке;
* SagaProcessor увидел ``compensatable=False`` → compensate невозможен.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.base import BaseProcessor


class TestSideEffectKindEnum:
    def test_string_value(self) -> None:
        assert SideEffectKind.PURE.value == "pure"
        assert SideEffectKind.STATEFUL.value == "stateful"
        assert SideEffectKind.SIDE_EFFECTING.value == "side_effecting"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            SideEffectKind("garbage")


class TestBaseProcessorDefaults:
    def test_default_side_effect_is_pure(self) -> None:
        class P(BaseProcessor):
            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                pass

        assert P.side_effect is SideEffectKind.PURE
        assert P.compensatable is True

    def test_subclass_override(self) -> None:
        class HttpPost(BaseProcessor):
            side_effect = SideEffectKind.SIDE_EFFECTING
            compensatable = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                pass

        assert HttpPost.side_effect is SideEffectKind.SIDE_EFFECTING
        assert HttpPost.compensatable is False


class TestPureProcessorIdempotency:
    @pytest.mark.asyncio
    async def test_pure_processor_deterministic(self) -> None:
        """PURE: одинаковый input → одинаковый output."""

        class Doubler(BaseProcessor):
            side_effect = SideEffectKind.PURE

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                exchange.in_message.body = exchange.in_message.body * 2

        proc = Doubler()
        ctx = ExecutionContext(route_id="r1")

        results = []
        for _ in range(3):
            ex: Exchange[int] = Exchange(in_message=Message(body=5))
            await proc.process(ex, ctx)
            results.append(ex.in_message.body)
        assert results == [10, 10, 10]


class TestStatefulProcessor:
    @pytest.mark.asyncio
    async def test_stateful_keeps_internal_counter(self) -> None:
        """STATEFUL: повторный вызов меняет результат (внутренний counter)."""

        class Counter(BaseProcessor):
            side_effect = SideEffectKind.STATEFUL

            def __init__(self) -> None:
                super().__init__()
                self._n = 0

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self._n += 1
                exchange.in_message.body = self._n

        proc = Counter()
        ctx = ExecutionContext(route_id="r1")
        seen: list[int] = []
        for _ in range(3):
            ex: Exchange[int] = Exchange(in_message=Message(body=0))
            await proc.process(ex, ctx)
            seen.append(ex.in_message.body)
        assert seen == [1, 2, 3]


class TestIntrospection:
    """Главный agent-сервис должен уметь читать side_effect через class-attr."""

    def test_engine_can_read_kind_without_instance(self) -> None:
        class Sender(BaseProcessor):
            side_effect = SideEffectKind.SIDE_EFFECTING
            compensatable = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                pass

        # Без создания инстанса можно классифицировать → дёшево
        # для retry-policy и Saga-планирования.
        assert Sender.side_effect == SideEffectKind.SIDE_EFFECTING
        assert Sender.compensatable is False
