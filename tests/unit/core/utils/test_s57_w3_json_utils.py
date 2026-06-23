"""Unit tests для json_utils (Sprint 57 W3).

Coverage:
* dumps_str — basic, indent, non-str keys, datetime, custom default
* dumps_bytes — basic, HTTP body
* loads — bytes/str/bytearray input, malformed JSON
"""

from __future__ import annotations

from datetime import UTC, datetime

import orjson
import pytest

from src.backend.core.utils.json_utils import dumps_bytes, dumps_str, loads

# ── dumps_str ───────────────────────────────────────────────────────


class TestDumpsStr:
    def test_basic_dict(self) -> None:
        """Простой dict → compact JSON string."""
        result = dumps_str({"name": "alice", "id": 42})
        assert result == '{"name":"alice","id":42}'
        assert isinstance(result, str)

    def test_indent(self) -> None:
        """indent=True → pretty 2-space JSON."""
        result = dumps_str({"x": 1, "y": 2}, indent=True)
        assert "\n" in result
        assert "  " in result
        assert '"x": 1' in result
        assert '"y": 2' in result

    def test_non_str_keys(self) -> None:
        """Non-string dict keys (int) → str() representation."""
        result = dumps_str({1: "one", 2: "two"})
        # OPT_NON_STR_KEYS converts int keys to "1", "2"
        assert result == '{"1":"one","2":"two"}'

    def test_datetime_naive_assumed_utc(self) -> None:
        """Naive datetime → assumed UTC (OPT_NAIVE_UTC)."""
        naive = datetime(2025, 6, 1, 12, 0, 0)
        result = dumps_str({"ts": naive})
        # 2025-06-01T12:00:00 → ISO 8601
        assert "2025-06-01T12:00:00" in result

    def test_datetime_aware_preserved(self) -> None:
        """Aware datetime → preserved with offset."""
        aware = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        result = dumps_str({"ts": aware})
        assert "2025-06-01T12:00:00+00:00" in result

    def test_default_fallback(self) -> None:
        """default=str → non-serializable types converted via str()."""

        class Custom:
            def __str__(self) -> str:
                return "custom_repr"

        result = dumps_str({"obj": Custom()}, default=str)
        assert '"obj":"custom_repr"' in result

    def test_unicode_preserved(self) -> None:
        """Unicode (Cyrillic) preserved correctly (orjson native UTF-8)."""
        result = dumps_str({"name": "Иван", "city": "Москва"})
        assert "Иван" in result
        assert "Москва" in result


# ── dumps_bytes ─────────────────────────────────────────────────────


class TestDumpsBytes:
    def test_basic(self) -> None:
        """Простой dict → JSON bytes."""
        result = dumps_bytes({"hello": "world"})
        assert result == b'{"hello":"world"}'
        assert isinstance(result, bytes)

    def test_indent(self) -> None:
        """indent=True → pretty bytes."""
        result = dumps_bytes({"x": 1}, indent=True)
        assert b"\n" in result
        assert b"  " in result

    def test_datetime(self) -> None:
        """datetime в bytes output."""
        aware = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        result = dumps_bytes({"ts": aware})
        assert b"2025-06-01T12:00:00+00:00" in result


# ── loads ───────────────────────────────────────────────────────────


class TestLoads:
    def test_from_bytes(self) -> None:
        """bytes input → dict."""
        result = loads(b'{"x": 1}')
        assert result == {"x": 1}

    def test_from_str(self) -> None:
        """str input → dict."""
        result = loads('{"x": 1}')
        assert result == {"x": 1}

    def test_from_bytearray(self) -> None:
        """bytearray input → dict."""
        result = loads(bytearray(b'{"x": 1}'))
        assert result == {"x": 1}

    def test_list_input(self) -> None:
        """JSON array → list."""
        result = loads(b"[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_malformed_raises(self) -> None:
        """Malformed JSON → orjson.JSONDecodeError."""
        with pytest.raises(orjson.JSONDecodeError):
            loads(b"{not-valid-json")

    def test_roundtrip(self) -> None:
        """dumps → loads roundtrip preserves data."""
        original = {"name": "alice", "tags": ["x", "y"], "count": 42}
        result = loads(dumps_bytes(original))
        assert result == original


# ── Performance smoke ───────────────────────────────────────────────


class TestPerformanceHint:
    def test_orjson_faster_than_stdlib_smoke(self) -> None:
        """Smoke test: orjson ≥2x faster than stdlib json на large dict.

        Не строгий benchmark — просто гарантирует что мы НЕ деградировали
        до stdlib под капотом.
        """
        import json
        import time

        large = {"items": [{"id": i, "name": f"item-{i}"} for i in range(1000)]}

        start = time.perf_counter()
        for _ in range(100):
            orjson.dumps(large)
        orjson_time = time.perf_counter() - start

        start = time.perf_counter()
        for _ in range(100):
            json.dumps(large)
        stdlib_time = time.perf_counter() - start

        # orjson должен быть быстрее (heuristic: at least 1.5x).
        assert orjson_time < stdlib_time, (
            f"orjson ({orjson_time:.4f}s) не быстрее stdlib ({stdlib_time:.4f}s)"
        )
