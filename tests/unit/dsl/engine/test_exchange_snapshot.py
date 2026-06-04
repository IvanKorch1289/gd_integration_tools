"""Tests for src.backend.dsl.engine.exchange_snapshot."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

import msgspec
import pytest

from src.backend.dsl.engine import exchange_snapshot as es

# ---------------------------------------------------------------------------
# Test fixtures — два типа: msgspec.Struct (fast path) и @dataclass (fast path)
# ---------------------------------------------------------------------------


class OrderStruct(msgspec.Struct):
    """msgspec.Struct — нативно поддерживается обоими направлениями."""

    id: int
    symbol: str
    qty: float
    price: float
    note: str = ""


@dataclass
class TradeDC:
    """dataclass — поддерживается msgspec.to_builtins, но НЕ pydantic."""

    id: int
    symbol: str
    qty: float
    price: float
    counter: int = 0


# ---------------------------------------------------------------------------
# Tests — encode (to_dict_fast)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToDictMsgspec:
    """Тесты encode-пути to_dict_fast."""

    def test_to_dict_msgspec_basic(self) -> None:
        """Round-trip: msgspec.Struct → dict → msgspec.Struct (идентичные поля)."""
        original = OrderStruct(id=1, symbol="AAPL", qty=100.5, price=178.25)
        encoded = es.to_dict_fast(original)
        assert encoded == {
            "id": 1,
            "symbol": "AAPL",
            "qty": 100.5,
            "price": 178.25,
            "note": "",
        }
        # Round-trip decode.
        decoded = es.from_dict_fast(OrderStruct, encoded)
        assert decoded.id == 1
        assert decoded.symbol == "AAPL"

    def test_to_dict_msgspec_faster(self) -> None:
        """Benchmark: msgspec должен быть не медленнее orjson (на struct-типе).

        Порог 1.5x — допускаем шум/накладные расходы, но не даём msgspec
        стать в 1.5 раза медленнее orjson. На реальных нагрузках msgspec
        быстрее в ~2x.
        """
        original = OrderStruct(id=42, symbol="MSFT", qty=10.0, price=300.0)
        iterations = 5_000

        # msgspec path
        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(original, use_msgspec=True)
        t_msgspec = time.perf_counter() - t0

        # orjson path (принудительный fallback)
        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(original, use_msgspec=False)
        t_orjson = time.perf_counter() - t0

        # msgspec ≤ 1.5× orjson. Если нет — либо regress в msgspec, либо
        # тест запущен в слишком шумном окружении (CI на shared-хосте).
        assert t_msgspec <= t_orjson * 1.5, (
            f"msgspec encode regressed: msgspec={t_msgspec*1e6:.1f}µs, "
            f"orjson={t_orjson*1e6:.1f}µs"
        )

    def test_to_dict_orjson_fallback(self) -> None:
        """use_msgspec=False принудительно использует orjson."""
        original = OrderStruct(id=1, symbol="AAPL", qty=100.5, price=178.25)
        fast = es.to_dict_fast(original, use_msgspec=True)
        slow = es.to_dict_fast(original, use_msgspec=False)
        assert fast == slow
        # sanity: orjson-путь даёт тот же dict, что и msgspec.
        assert slow == {
            "id": 1,
            "symbol": "AAPL",
            "qty": 100.5,
            "price": 178.25,
            "note": "",
        }

    def test_to_dict_handles_datetime(self) -> None:
        """datetime-поля сериализуются через enc_hook → ISO 8601."""

        @dataclass
        class WithDT:
            ts: datetime
            symbol: str

        obj = WithDT(ts=datetime(2024, 1, 15, 10, 30, 0), symbol="AAPL")
        encoded = es.to_dict_fast(obj)
        assert encoded["symbol"] == "AAPL"
        assert encoded["ts"] == "2024-01-15T10:30:00"

    def test_to_dict_dataclass_roundtrip(self) -> None:
        """dataclass без datetime — должен идти через msgspec fast path."""
        original = TradeDC(id=7, symbol="GOOG", qty=50.0, price=150.0, counter=42)
        encoded = es.to_dict_fast(original)
        assert encoded["symbol"] == "GOOG"
        assert encoded["counter"] == 42


# ---------------------------------------------------------------------------
# Tests — decode (from_dict_fast)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFromDictMsgspec:
    """Тесты decode-пути from_dict_fast."""

    def test_from_dict_msgspec_basic(self) -> None:
        """dict → msgspec.Struct round-trip."""
        data = {"id": 5, "symbol": "TSLA", "qty": 25.0, "price": 250.0, "note": "x"}
        result = es.from_dict_fast(OrderStruct, data)
        assert isinstance(result, OrderStruct)
        assert result.id == 5
        assert result.symbol == "TSLA"
        assert result.qty == 25.0
        assert result.note == "x"

    def test_msgspec_not_available_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Когда msgspec недоступен — обе функции идут через orjson/cls(**data).

        Эмулируем отсутствие: ставим ``_HAS_MSGSPEC = False`` и заменяем
        ссылку ``_msgspec`` на ``None`` в модуле.
        """
        monkeypatch.setattr(es, "_HAS_MSGSPEC", False)
        monkeypatch.setattr(es, "_msgspec", None)

        # encode через orjson fallback.
        original = OrderStruct(id=1, symbol="AAPL", qty=1.0, price=1.0)
        encoded = es.to_dict_fast(original)
        assert encoded["symbol"] == "AAPL"

        # decode через cls(**data) fallback.
        decoded = es.from_dict_fast(OrderStruct, encoded)
        assert decoded.symbol == "AAPL"
        assert isinstance(decoded, OrderStruct)

    def test_to_dict_handles_pydantic_via_fallback(self) -> None:
        """Pydantic-модели идут через orjson fallback (msgspec их не знает)."""
        from pydantic import BaseModel

        class PM(BaseModel):
            id: int
            symbol: str
            qty: float

        obj = PM(id=1, symbol="AAPL", qty=10.0)
        encoded = es.to_dict_fast(obj)
        # orjson сериализует pydantic v2 через .model_dump() или .dict() — проверим,
        # что либо fast-path вернул dict, либо мы попали в orjson. В обоих
        # случаях encoded — dict с правильными полями.
        assert isinstance(encoded, dict)
        assert encoded["symbol"] == "AAPL"
        assert encoded["id"] == 1

    def test_from_dict_extra_keys_ignored_by_msgspec(self) -> None:
        """msgspec.convert по умолчанию НЕ строгий — лишние ключи игнорируются.

        Это поведение (отличающееся от pydantic) лучше зафиксировать тестом.
        Проверяем, что лишний ключ не поднимает исключение, а просто отбрасывается.
        """
        data = {"id": 1, "symbol": "A", "qty": 1.0, "price": 1.0, "note": "",
                "extra_unknown": 999}
        result = es.from_dict_fast(OrderStruct, data)
        assert isinstance(result, OrderStruct)
        assert result.id == 1
        assert result.symbol == "A"
        # msgspec не заводит лишних атрибутов на result.
        assert not hasattr(result, "extra_unknown")
