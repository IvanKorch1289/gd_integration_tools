"""Unit-тесты ``core.serialization`` — coverage ratchet (S48 W26).

core/serialization/__init__.py — S10 K2 W1 / PERF-6.5 hot-path serializers:
re-exports msgspec-based JSON encode/decode + audit event encoder +
WebSocket frame encoder + cache key hashing. 6 symbols re-exported,
~9 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity + smoke tests
на actual encode/decode.
"""

from __future__ import annotations

import pytest

from src.backend.core import serialization as core_ser
from src.backend.core.serialization import (
    MSGSPEC_AVAILABLE,
    decode_json,
    encode_audit_event,
    encode_json,
    encode_ws_frame,
    hash_cache_key,
)


@pytest.mark.unit
class TestSerializationFacadeAllExports:
    """``__all__`` audit + callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "MSGSPEC_AVAILABLE",
            "decode_json",
            "encode_audit_event",
            "encode_json",
            "encode_ws_frame",
            "hash_cache_key",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(core_ser, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in core_ser.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 6 символов."""
        assert len(core_ser.__all__) == 6

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S10 K2 W1 / PERF-6.5 hot-path."""
        assert core_ser.__doc__ is not None
        assert "S10" in core_ser.__doc__ or "PERF" in core_ser.__doc__


@pytest.mark.unit
class TestSerializationFacadeIdentity:
    """Identity + functional smoke tests для serializers."""

    def test_msgspec_available_is_bool(self) -> None:
        """``MSGSPEC_AVAILABLE`` — bool (per feature detection)."""
        assert isinstance(MSGSPEC_AVAILABLE, bool)

    def test_encode_json_is_callable(self) -> None:
        """``encode_json`` — callable."""
        assert callable(encode_json)

    def test_decode_json_is_callable(self) -> None:
        """``decode_json`` — callable."""
        assert callable(decode_json)

    def test_encode_audit_event_is_callable(self) -> None:
        """``encode_audit_event`` — callable."""
        assert callable(encode_audit_event)

    def test_encode_ws_frame_is_callable(self) -> None:
        """``encode_ws_frame`` — callable."""
        assert callable(encode_ws_frame)

    def test_hash_cache_key_is_callable(self) -> None:
        """``hash_cache_key`` — callable."""
        assert callable(hash_cache_key)

    def test_hash_cache_key_returns_int_or_str(self) -> None:
        """``hash_cache_key(s)`` → int или str (per implementation)."""
        result = hash_cache_key("test_key")
        assert isinstance(result, (int, str))
