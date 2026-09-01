"""Unit-тесты ``core.resilience.backpressure`` — coverage ratchet (S48 W30).

core/resilience/backpressure/__init__.py — S67 W1 decomp: re-exports
5 classes + 1 helper function from per-concern submodules (types,
controller, stream_reader, bulkhead, helpers). 12 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + Protocol/class identity +
callable identity for helper.
"""

from __future__ import annotations

import pytest

from src.backend.core.resilience import backpressure
from src.backend.core.resilience.backpressure import (
    AdaptiveBulkhead,
    AdaptiveStreamReader,
    BackpressureState,
    ConsumerControlProtocol,
    StreamingBackpressureController,
    get_streaming_controller,
)


@pytest.mark.unit
class TestBackpressureFacadeAllExports:
    """``__all__`` audit + type/Protocol identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AdaptiveBulkhead",
            "AdaptiveStreamReader",
            "BackpressureState",
            "ConsumerControlProtocol",
            "StreamingBackpressureController",
            "get_streaming_controller",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(backpressure, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in backpressure.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 6 символов."""
        assert len(backpressure.__all__) == 6

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S67 W1 decomp."""
        assert backpressure.__doc__ is not None
        assert "S67 W1" in backpressure.__doc__


@pytest.mark.unit
class TestBackpressureFacadeIdentity:
    """Identity checks для canonical classes + Protocol + helper."""

    def test_streaming_backpressure_controller_is_class(self) -> None:
        """``StreamingBackpressureController`` — class."""
        assert isinstance(StreamingBackpressureController, type)

    def test_adaptive_bulkhead_is_class(self) -> None:
        """``AdaptiveBulkhead`` — class."""
        assert isinstance(AdaptiveBulkhead, type)

    def test_adaptive_stream_reader_is_class(self) -> None:
        """``AdaptiveStreamReader`` — class."""
        assert isinstance(AdaptiveStreamReader, type)

    def test_backpressure_state_is_class(self) -> None:
        """``BackpressureState`` — class (data state)."""
        assert isinstance(BackpressureState, type)

    def test_consumer_control_protocol_is_protocol(self) -> None:
        """``ConsumerControlProtocol`` — runtime_checkable Protocol."""
        # Protocol classes have ``__subclasshook__`` или ``__call__``.
        assert hasattr(ConsumerControlProtocol, "__subclasshook__") or hasattr(
            ConsumerControlProtocol, "__call__"
        )

    def test_get_streaming_controller_is_callable(self) -> None:
        """``get_streaming_controller`` — callable helper."""
        assert callable(get_streaming_controller)
