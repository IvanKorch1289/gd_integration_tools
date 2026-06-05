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
        """Benchmark: msgspec должен быть минимум в 2x быстрее orjson (на struct-типе).

        Порог 0.5x (2x speedup) — msgspec нативно сериализует msgspec.Struct
        в C-extension, минуя orjson's pure-Python default callback для
        ``__struct_fields__``. На синтетических 5-полевых структурах
        реальный speedup ~2.5x. S40 W8: подтверждаем v15 §7 target.
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

        # msgspec должен быть минимум в 2x быстрее orjson.
        # Если нет — regress в msgspec или шумное окружение.
        assert t_msgspec <= t_orjson * 0.5, (
            f"msgspec encode speedup < 2x: msgspec={t_msgspec*1e6:.1f}µs, "
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

    def test_enc_hook_raises_on_unsupported_type(self) -> None:
        """_msgspec_enc_hook бросает NotImplementedError на неизвестный тип."""
        with pytest.raises(NotImplementedError):
            es._msgspec_enc_hook(object())

    def test_to_dict_fallback_on_msgspec_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если _encode_msgspec бросает — to_dict_fast fallback'ит на orjson."""
        calls: list[str] = []

        def _fake_encode_msgspec(obj: Any) -> Any:
            calls.append("msgspec")
            raise TypeError("fake msgspec failure")

        def _fake_encode_orjson(obj: Any) -> Any:
            calls.append("orjson")
            return {"fallback": True}

        monkeypatch.setattr(es, "_encode_msgspec", _fake_encode_msgspec)
        monkeypatch.setattr(es, "_encode_orjson", _fake_encode_orjson)

        result = es.to_dict_fast({"a": 1})
        assert calls == ["msgspec", "orjson"]
        assert result == {"fallback": True}

    def test_from_dict_fallback_on_msgspec_exception(self) -> None:
        """Если msgspec.convert бросает — from_dict_fast fallback'ит на cls(**data)."""
        from pydantic import BaseModel

        class PydanticModel(BaseModel):
            id: int

        result = es.from_dict_fast(PydanticModel, {"id": 42})
        assert isinstance(result, PydanticModel)
        assert result.id == 42

    def test_orjson_default_handles_unsupported_type(self) -> None:
        """_orjson_default бросает TypeError на полностью неподдерживаемый тип."""
        class Unserialisable:
            pass

        with pytest.raises(TypeError):
            es._orjson_default(Unserialisable())


# ---------------------------------------------------------------------------
# Real-world benchmarks — S40 W8
# ---------------------------------------------------------------------------
# msgspec speedup проверяем не на синтетических 5-полевых struct'ах, а на
# реальных production-shape'ах: Exchange/Message (pydantic v2 — fallback),
# глубоко вложенные dict'ы (msgspec-friendly), и 1MB payload (throughput).
# Per v15 §7: 6× target на нативных struct'ах; на pydantic — приемлемо
# равенство (fallback). Запускать с ``-s`` чтобы увидеть timings.


@pytest.mark.unit
class TestRealWorldBenchmarks:
    """Real-world benchmarks: msgspec vs orjson на production-like данных."""

    def test_msgspec_speedup_real_exchange(self) -> None:
        """Real Exchange snapshot: msgspec path (pydantic → orjson fallback).

        Exchange/Message — pydantic v2 модели; msgspec их нативно не
        кодирует, поэтому ``to_dict_fast`` делает try/except и идёт
        через orjson. Здесь сравниваем dispatch+fallback path против
        чистого orjson — overhead try/except должен оставаться < 50%.
        """
        from src.backend.dsl.engine.exchange import Exchange, Message

        ex = Exchange(
            in_message=Message(
                body={
                    "users": [
                        {"id": i, "name": f"user_{i}", "tags": ["a", "b", "c"]}
                        for i in range(100)
                    ]
                }
            )
        )
        iterations = 1_000

        # msgspec path (fallback to orjson for pydantic)
        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(ex, use_msgspec=True)
        t_msgspec = time.perf_counter() - t0

        # pure orjson path
        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(ex, use_msgspec=False)
        t_orjson = time.perf_counter() - t0

        ratio = t_msgspec / t_orjson if t_orjson > 0 else float("inf")
        print(
            f"\n[real_exchange] msgspec={t_msgspec*1e3:.2f}ms "
            f"orjson={t_orjson*1e3:.2f}ms ratio={ratio:.2f}x"
        )
        # Fallback path не должен стоить дороже 1.5x от чистого orjson.
        assert t_msgspec <= t_orjson * 1.5, (
            f"msgspec fallback regressed on real Exchange: "
            f"msgspec={t_msgspec*1e6:.1f}µs, orjson={t_orjson*1e6:.1f}µs"
        )

    def test_msgspec_speedup_nested_dict(self) -> None:
        """Nested dict (5 levels): msgspec vs orjson.

        Чистый dict — нет pydantic. msgspec C-extension обходит
        orjson pure-Python encoder на traversal глубоких структур.
        Ожидаем msgspec как минимум не медленнее orjson.
        """
        nested = {
            "a": {"b": {"c": {"d": {"e": [1, 2, 3, {"x": "y", "z": [4, 5, 6]}]}}}},
            "meta": {"version": 1, "flags": [True, False, None]},
        }
        iterations = 10_000

        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(nested, use_msgspec=True)
        t_msgspec = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(nested, use_msgspec=False)
        t_orjson = time.perf_counter() - t0

        ratio = t_msgspec / t_orjson if t_orjson > 0 else float("inf")
        print(
            f"\n[nested_dict] msgspec={t_msgspec*1e3:.2f}ms "
            f"orjson={t_orjson*1e3:.2f}ms ratio={ratio:.2f}x"
        )
        # msgspec как минимум не медленнее orjson на чистых dict'ах.
        assert t_msgspec <= t_orjson, (
            f"msgspec slower than orjson on nested dict: "
            f"msgspec={t_msgspec*1e6:.1f}µs, orjson={t_orjson*1e6:.1f}µs"
        )

    def test_msgspec_speedup_large_payload(self) -> None:
        """1MB payload (list of dicts): msgspec vs orjson throughput.

        7500 транзакций → ~1MB JSON. Ожидаем ≥1.5× speedup за счёт
        msgspec C-extension bulk encode (zero-copy через buffer protocol).
        """
        # 7500 transactions → ~1MB JSON
        payload = {
            "transactions": [
                {
                    "id": i,
                    "account": f"ACC{i:08d}",
                    "amount": float(i) * 1.5,
                    "currency": "USD",
                    "tags": ["online", "verified"],
                    "metadata": {"source": "api", "version": 2},
                }
                for i in range(7_500)
            ]
        }
        size_bytes = len(msgspec.json.encode(payload))
        assert size_bytes >= 1_000_000, (
            f"payload only {size_bytes} bytes (expected ≥ 1MB)"
        )

        iterations = 50

        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(payload, use_msgspec=True)
        t_msgspec = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(iterations):
            es.to_dict_fast(payload, use_msgspec=False)
        t_orjson = time.perf_counter() - t0

        ratio = t_msgspec / t_orjson if t_orjson > 0 else float("inf")
        print(
            f"\n[1mb_payload] msgspec={t_msgspec*1e3:.2f}ms "
            f"orjson={t_orjson*1e3:.2f}ms ratio={ratio:.2f}x "
            f"payload={size_bytes/1024:.0f}KB"
        )
        # На 1MB payload msgspec должен быть минимум в 1.5x быстрее.
        assert t_msgspec <= t_orjson / 1.5, (
            f"msgspec throughput < 1.5x on 1MB payload: "
            f"msgspec={t_msgspec*1e3:.2f}ms, orjson={t_orjson*1e3:.2f}ms"
        )
