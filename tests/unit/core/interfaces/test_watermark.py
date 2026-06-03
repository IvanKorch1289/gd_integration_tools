"""Unit tests for src.backend.core.interfaces.watermark."""

from __future__ import annotations

from src.backend.core.interfaces.watermark import WatermarkEmitter


class TestWatermarkEmitter:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            def current_watermark(self) -> float | None:
                return 1.0

        assert isinstance(Fake(), WatermarkEmitter)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), WatermarkEmitter)
