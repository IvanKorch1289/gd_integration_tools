# ruff: noqa: S101
"""Wave 1.6: AI Safety lifecycle (register_ai_safety + start/stop)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.workspace_manager import AIWorkspaceManager
from src.backend.core.svcs_registry import (
    clear_registry,
    get_service,
    has_service,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture()
def patched_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Подменяет ``ai_workspace_settings.workspace_root`` на tmp_path."""
    from src.backend.core.config import ai as ai_config

    monkeypatch.setattr(
        ai_config.ai_workspace_settings, "workspace_root", tmp_path / "ai_ws"
    )
    monkeypatch.setattr(
        ai_config.ai_workspace_settings, "workspace_ttl_seconds", 0.05
    )
    monkeypatch.setattr(
        ai_config.ai_workspace_settings, "workspace_cleanup_interval_s", 0.05
    )
    return ai_config.ai_workspace_settings


@pytest.mark.asyncio
async def test_register_ai_safety_creates_singletons(
    patched_settings,
) -> None:
    from src.backend.plugins.composition.ai_safety_setup import (
        register_ai_safety,
    )

    register_ai_safety()
    assert has_service(AIWorkspaceManager)
    assert has_service(AIFsFacade)
    m1 = get_service(AIWorkspaceManager)
    m2 = get_service(AIWorkspaceManager)
    assert m1 is m2


@pytest.mark.asyncio
async def test_start_ai_safety_creates_workspace_root(
    patched_settings,
) -> None:
    from src.backend.plugins.composition.ai_safety_setup import (
        register_ai_safety,
        start_ai_safety,
        stop_ai_safety,
    )

    register_ai_safety()
    await start_ai_safety()
    try:
        assert patched_settings.workspace_root.is_dir()
    finally:
        await stop_ai_safety()


@pytest.mark.asyncio
async def test_cleanup_loop_removes_expired(
    patched_settings,
) -> None:
    """TTL=0.05с: cleanup-loop удаляет workspace через ~два tick'а."""
    from src.backend.plugins.composition.ai_safety_setup import (
        register_ai_safety,
        start_ai_safety,
        stop_ai_safety,
    )

    register_ai_safety()
    await start_ai_safety()
    try:
        manager = get_service(AIWorkspaceManager)
        handle = await manager.create_new(tenant="t1")
        assert handle.path.is_dir()
        # ждём, пока cleanup-loop сработает
        for _ in range(50):
            if not handle.path.exists():
                break
            await asyncio.sleep(0.05)
        assert not handle.path.exists()
    finally:
        await stop_ai_safety()


@pytest.mark.asyncio
async def test_stop_cancels_cleanup_task(
    patched_settings,
) -> None:
    from src.backend.plugins.composition.ai_safety_setup import (
        register_ai_safety,
        start_ai_safety,
        stop_ai_safety,
    )

    register_ai_safety()
    await start_ai_safety()
    manager = get_service(AIWorkspaceManager)
    task = manager._cleanup_task
    assert task is not None and not task.done()
    await stop_ai_safety()
    assert task.done()


@pytest.mark.asyncio
async def test_fs_facade_wired_with_capability_check(
    patched_settings,
) -> None:
    """AIFsFacade должна получить capability_check, если CapabilityGate в svcs."""
    from src.backend.core.security.capabilities.gate import CapabilityGate
    from src.backend.core.svcs_registry import register_factory
    from src.backend.plugins.composition.ai_safety_setup import (
        register_ai_safety,
    )

    register_factory(CapabilityGate, lambda: CapabilityGate())
    register_ai_safety()
    facade = get_service(AIFsFacade)
    assert facade._check is not None
