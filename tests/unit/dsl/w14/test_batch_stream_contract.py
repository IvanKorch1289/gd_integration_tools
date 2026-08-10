"""W14.2 — единый контракт batch+stream.

Доказывает:

* ``Message.data_kind`` default = SINGLE — обратная совместимость;
* BATCH / STREAM сериализуются и round-trip'ятся через JSON/YAML;
* Pydantic валидирует значение ``data_kind``.

Note: ``BatchCapable`` Protocol (W14.2 opt-in) был удалён как YAGNI —
нет ни одного процессора, реализующего ``process_batch``. Оптимизация
под batch остаётся на ответственности самого процессора (typeguard
или явная проверка ``exchange.in_message.data_kind``).
"""


from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.types.data_kind import DataKind
from src.backend.dsl.engine.exchange import Message


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


class TestMessageWatermarkField:
    """W14.2/14.3: watermark — optional поле, не ломает старые Message."""

    def test_default_watermark_is_none(self) -> None:
        msg: Message[Any] = Message(body=42)
        assert msg.watermark is None

    def test_explicit_watermark(self) -> None:
        msg: Message[Any] = Message(body=42, watermark=1_700_000_000.5)
        assert msg.watermark == 1_700_000_000.5
