"""Unit tests for src.backend.core.interfaces.watermark_store."""

from __future__ import annotations

from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.core.types.watermark import WatermarkState


class TestWatermarkStore:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def load(
                self, route_id: str, processor_name: str
            ) -> WatermarkState | None:
                return None

            async def save(
                self, route_id: str, processor_name: str, state: WatermarkState
            ) -> None:
                pass

        assert isinstance(Fake(), WatermarkStore)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), WatermarkStore)
