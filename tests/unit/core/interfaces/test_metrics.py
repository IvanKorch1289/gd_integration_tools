"""Unit tests for src.backend.core.interfaces.metrics."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.metrics import MetricsBackend


class TestMetricsBackend:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            MetricsBackend()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(MetricsBackend):
            def inc_counter(
                self,
                name: str,
                value: float = 1.0,
                labels: dict[str, str] | None = None,
            ) -> None:
                pass

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(MetricsBackend):
            def inc_counter(
                self,
                name: str,
                value: float = 1.0,
                labels: dict[str, str] | None = None,
            ) -> None:
                pass

            def set_gauge(
                self, name: str, value: float, labels: dict[str, str] | None = None
            ) -> None:
                pass

            def observe_histogram(
                self, name: str, value: float, labels: dict[str, str] | None = None
            ) -> None:
                pass

            def snapshot(self) -> dict[str, object]:
                return {}

        assert Full() is not None
