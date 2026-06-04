"""Unit-тесты для ABTestProcessor (S10 K3 W3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.dsl.engine.processors.ab_test import ABTestProcessor, select_variant


class _FakeExchange:
    def __init__(self, correlation_id: str | None = None) -> None:
        self.correlation_id = correlation_id
        self._props: dict[str, Any] = {}

    def set_property(self, key: str, value: Any) -> None:
        self._props[key] = value

    def get_property(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)


def test_select_variant_with_correlation_id_deterministic() -> None:
    """Один и тот же correlation_id всегда даёт один и тот же variant."""
    v1 = select_variant(correlation_id="user-42", split=(0.5, 0.5))
    v2 = select_variant(correlation_id="user-42", split=(0.5, 0.5))
    assert v1 == v2


def test_select_variant_different_cid_can_differ() -> None:
    """Большая выборка корр-id даёт примерно ожидаемое распределение."""
    a_count = sum(
        1
        for i in range(1000)
        if select_variant(correlation_id=f"user-{i}", split=(0.5, 0.5)) == "A"
    )
    # 50%-split на 1000 примерах: 400-600 — нормально.
    assert 400 < a_count < 600


def test_select_variant_skewed_split() -> None:
    a_count = sum(
        1
        for i in range(1000)
        if select_variant(correlation_id=f"user-{i}", split=(0.9, 0.1)) == "A"
    )
    assert a_count > 800


def test_select_variant_zero_split_returns_a() -> None:
    assert select_variant(correlation_id="x", split=(0.0, 0.0)) == "A"


def test_processor_requires_experiment_id() -> None:
    with pytest.raises(ValueError, match="experiment_id"):
        ABTestProcessor(experiment_id="")


def test_processor_rejects_invalid_split() -> None:
    with pytest.raises(ValueError, match="split"):
        ABTestProcessor(
            experiment_id="x",
            split=(0.5,),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        ABTestProcessor(experiment_id="x", split=(-0.1, 0.5))


@pytest.mark.asyncio
async def test_process_writes_variant_to_exchange() -> None:
    p = ABTestProcessor(experiment_id="exp1", split=(0.5, 0.5))
    exchange = _FakeExchange(correlation_id="cid")
    await p.process(exchange, SimpleNamespace())
    variant = exchange.get_property("ab_test:exp1")
    assert variant in {"A", "B"}


def test_processor_to_spec_round_trip() -> None:
    p = ABTestProcessor(
        experiment_id="checkout", split=(0.7, 0.3), track_metric="conversion"
    )
    spec = p.to_spec()["ab_test"]
    assert spec["experiment_id"] == "checkout"
    assert spec["split"] == [0.7, 0.3]
    assert spec["track_metric"] == "conversion"
