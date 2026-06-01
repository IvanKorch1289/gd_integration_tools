# ruff: noqa: S101
"""Тесты admin-endpoint /tech/degradation/snapshot (Wave A.5).

Покрывает:
    - TechService.get_degradation_snapshot() возвращает snapshot реестра.
    - После register(...) feature появляется в snapshot.
    - Manual recover() сбрасывает state и видится в новом snapshot.
"""

from __future__ import annotations

import pytest

from src.backend.core.resilience.graceful_degradation import (
    DegradationFeature,
    FeatureState,
    GracefulDegradationRegistry,
    get_graceful_degradation_registry,
)
from src.backend.services.core.tech import TechService


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолирует test от глобального singleton."""
    fresh = GracefulDegradationRegistry()
    monkeypatch.setattr(
        "src.backend.core.resilience.graceful_degradation._registry_singleton",
        fresh,
    )


@pytest.mark.asyncio
async def test_snapshot_endpoint_returns_registered_features() -> None:
    """Зарегистрированные features попадают в snapshot."""
    registry = get_graceful_degradation_registry()

    async def _full() -> str:
        return "full"

    async def _degraded() -> str:
        return "degraded"

    registry.register(
        DegradationFeature(
            name="ai.llm_call",
            full_handler=_full,
            degraded_handler=_degraded,
        )
    )

    service = TechService()
    snapshot = await service.get_degradation_snapshot()
    assert "ai.llm_call" in snapshot
    assert snapshot["ai.llm_call"]["state"] == "healthy"
    assert snapshot["ai.llm_call"]["samples"] == 0


@pytest.mark.asyncio
async def test_snapshot_reflects_recorded_outcomes() -> None:
    """После record_outcome snapshot содержит обновлённый error_rate."""
    registry = get_graceful_degradation_registry()

    async def _full() -> str:
        return "full"

    async def _degraded() -> str:
        return "degraded"

    registry.register(
        DegradationFeature(
            name="rag.retrieval",
            full_handler=_full,
            degraded_handler=_degraded,
            error_threshold=0.5,
            recovery_threshold=0.1,
            window_size=10,
        )
    )
    for _ in range(5):
        await registry.record_outcome("rag.retrieval", success=False)
    for _ in range(5):
        await registry.record_outcome("rag.retrieval", success=True)

    service = TechService()
    snapshot = await service.get_degradation_snapshot()
    assert snapshot["rag.retrieval"]["samples"] == 10
    assert snapshot["rag.retrieval"]["error_rate"] == 0.5


@pytest.mark.asyncio
async def test_manual_recover_visible_in_snapshot() -> None:
    """recover() сбрасывает samples=0 и state=healthy."""
    registry = get_graceful_degradation_registry()

    async def _stub() -> None:
        return None

    registry.register(
        DegradationFeature(
            name="cache.lookup",
            full_handler=_stub,
            degraded_handler=_stub,
            error_threshold=0.2,
            window_size=5,
        )
    )
    for _ in range(5):
        await registry.record_outcome("cache.lookup", success=False)
    assert registry.get_state("cache.lookup") == FeatureState.DEGRADED

    registry.recover("cache.lookup")
    service = TechService()
    snapshot = await service.get_degradation_snapshot()
    assert snapshot["cache.lookup"]["state"] == "healthy"
    assert snapshot["cache.lookup"]["samples"] == 0


def test_setup_infra_bootstrap_registers_default_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_register_default_degradation_features регистрирует все ожидаемые имена."""
    from src.backend.plugins.composition import setup_infra

    fresh = GracefulDegradationRegistry()
    monkeypatch.setattr(
        "src.backend.core.resilience.graceful_degradation._registry_singleton",
        fresh,
    )

    setup_infra._register_default_degradation_features()
    snapshot = fresh.snapshot()
    for expected in (
        "ai.llm_call",
        "rag.retrieval",
        "external.api_call",
        "cache.lookup",
    ):
        assert expected in snapshot
