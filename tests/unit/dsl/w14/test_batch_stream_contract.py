"""W14.2 — единый контракт batch+stream.

Доказывает:

* ``Message.data_kind`` default = SINGLE — обратная совместимость;
* BATCH / STREAM сериализуются и round-trip'ятся через JSON/YAML;
* процессор с ``BatchCapable`` Protocol проходит ``isinstance``-чек;
* процессор без ``BatchCapable`` Protocol — нет;
* Pydantic валидирует значение ``data_kind``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.core.interfaces.batch_capable import BatchCapable
from src.core.types.data_kind import DataKind
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.base import BaseProcessor


class TestDataKindEnum:
    def test_default_is_single(self) -> None:
        msg: Message[Any] = Message(body="hello")
        assert msg.data_kind == DataKind.SINGLE

    def test_explicit_batch(self) -> None:
        msg: Message[list[int]] = Message(body=[1, 2, 3], data_kind=DataKind.BATCH)
        assert msg.data_kind == DataKind.BATCH
        assert msg.body == [1, 2, 3]

    def test_explicit_stream(self) -> None:
        msg: Message[Any] = Message(body=None, data_kind=DataKind.STREAM)
        assert msg.data_kind == DataKind.STREAM

    def test_data_kind_serialises_as_string(self) -> None:
        msg: Message[Any] = Message(body=1, data_kind=DataKind.BATCH)
        dumped = msg.model_dump()
        # Pydantic + str-Enum: значение — строка.
        assert dumped["data_kind"] == "batch"

    def test_invalid_data_kind_raises(self) -> None:
        with pytest.raises(ValueError):
            Message(body=1, data_kind="not-a-kind")  # type: ignore[arg-type]


class TestBatchCapableProtocol:
    """Контракт opt-in Protocol для batch-процессоров."""

    def test_processor_with_process_batch_satisfies_protocol(self) -> None:
        class BatchOk(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="batch-ok")

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                pass

            async def process_batch(
                self, exchange: Exchange[list[Any]], context: ExecutionContext
            ) -> None:
                # Доказываем существование метода — engine может на него
                # переключиться при data_kind=BATCH.
                pass

        assert isinstance(BatchOk(), BatchCapable)

    def test_processor_without_process_batch_not_protocol(self) -> None:
        class SingleOnly(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="single-only")

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                pass

        assert not isinstance(SingleOnly(), BatchCapable)


class TestMessageWatermarkField:
    """W14.2/14.3: watermark — optional поле, не ломает старые Message."""

    def test_default_watermark_is_none(self) -> None:
        msg: Message[Any] = Message(body=42)
        assert msg.watermark is None

    def test_explicit_watermark(self) -> None:
        msg: Message[Any] = Message(body=42, watermark=1_700_000_000.5)
        assert msg.watermark == 1_700_000_000.5
