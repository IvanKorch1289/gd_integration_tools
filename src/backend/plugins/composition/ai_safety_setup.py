"""AI Safety wiring (Wave 1.6, V15 R-V15-4).

Регистрирует :class:`AIWorkspaceManager` и :class:`AIFsFacade` в svcs;
запускает cleanup-loop в lifespan startup, корректно останавливает
на shutdown через :class:`TaskRegistry`.

AI-плагины получают:

* ``AIWorkspaceManager`` — выдача изолированных workspace-handle'ов;
* ``AIFsFacade`` — единственный санкционированный FS-вход (capability
  ``fs.read.<path>`` для чтения проекта; ``fs.create_new.<workspace>``
  для записи новых файлов в выданный handle).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.sandbox import CodeSandbox, NoOpSandbox
from src.backend.core.ai.workspace_manager import AIWorkspaceManager
from src.backend.core.svcs_registry import get_service, has_service, register_factory

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = (
    "register_ai_safety",
    "register_e2b_sandbox",
    "start_ai_safety",
    "stop_ai_safety",
)

_logger = logging.getLogger("ai_safety.setup")


def _build_workspace_manager() -> AIWorkspaceManager:
    """Сконструировать ``AIWorkspaceManager`` из settings."""
    from src.backend.core.config.ai import ai_workspace_settings

    workspace_root = ai_workspace_settings.workspace_root
    workspace_root.mkdir(parents=True, exist_ok=True)
    return AIWorkspaceManager(
        root=workspace_root,
        ttl_seconds=ai_workspace_settings.workspace_ttl_seconds,
        per_tenant_quota_bytes=ai_workspace_settings.workspace_quota_bytes,
        cleanup_interval_seconds=ai_workspace_settings.workspace_cleanup_interval_s,
    )


def _build_fs_facade() -> AIFsFacade:
    """Сконструировать ``AIFsFacade`` поверх workspace_manager + capability_check."""
    workspace_manager = get_service(AIWorkspaceManager)
    capability_check = None
    try:
        from src.backend.core.security.capabilities.gate import CapabilityGate

        if has_service(CapabilityGate):
            gate = get_service(CapabilityGate)
            capability_check = getattr(gate, "check", None)
    except Exception as _:
        capability_check = None
    return AIFsFacade(
        workspace_manager=workspace_manager,
        capability_check=capability_check,
        plugin="ai-agent",
    )


def register_ai_safety() -> None:
    """Зарегистрировать AI Safety фасады в svcs (идемпотентно)."""
    if not has_service(AIWorkspaceManager):
        register_factory(AIWorkspaceManager, _build_workspace_manager)
    if not has_service(AIFsFacade):
        register_factory(AIFsFacade, _build_fs_facade)
    if not has_service(CodeSandbox):
        register_e2b_sandbox()


def register_e2b_sandbox() -> None:
    """Зарегистрировать :class:`CodeSandbox` (E2B либо :class:`NoOpSandbox`).

    Идемпотентно. При отсутствии ``E2B_API_KEY`` или e2b-code-interpreter
    регистрируется NoOp; никаких ``subprocess.run`` fallback'ов нет.
    """
    if has_service(CodeSandbox):
        return

    def _factory() -> CodeSandbox:
        api_key = os.environ.get("E2B_API_KEY", "").strip()
        if not api_key:
            _logger.warning(
                "E2B_API_KEY не задан — регистрируется NoOpSandbox; "
                "AI code-execution будет отказываться."
            )
            return NoOpSandbox()
        try:
            import e2b_code_interpreter  # noqa: F401
        except ImportError:
            _logger.warning(
                "e2b-code-interpreter не установлен (опц. extra [ai]); "
                "регистрируется NoOpSandbox."
            )
            return NoOpSandbox()
        from src.backend.infrastructure.ai.e2b_sandbox import E2BSandbox

        capability_check = None
        try:
            from src.backend.core.security.capabilities.gate import CapabilityGate

            if has_service(CapabilityGate):
                gate = get_service(CapabilityGate)
                capability_check = getattr(gate, "check", None)
        except Exception as _:
            capability_check = None

        fs_facade = get_service(AIFsFacade) if has_service(AIFsFacade) else None
        return E2BSandbox(
            api_key=api_key, capability_check=capability_check, fs_facade=fs_facade
        )

    register_factory(CodeSandbox, _factory)


async def start_ai_safety(app: "FastAPI" | None = None) -> None:
    """Lifespan startup: запустить cleanup-loop через TaskRegistry."""
    if not has_service(AIWorkspaceManager):
        register_ai_safety()
    manager = get_service(AIWorkspaceManager)
    try:
        from src.backend.core.utils.task_registry import get_task_registry

        task_factory = get_task_registry().create_task
    except Exception as _:
        task_factory = None
    await manager.start_cleanup_loop(task_factory=task_factory)
    _logger.info(
        "AI safety started (root=%s, ttl=%.0fs, quota=%d B)",
        manager.root,
        manager._ttl,
        manager._quota,
    )


async def stop_ai_safety(app: "FastAPI" | None = None) -> None:
    """Lifespan shutdown: остановить cleanup-loop, отменить task."""
    if not has_service(AIWorkspaceManager):
        return
    try:
        manager = get_service(AIWorkspaceManager)
    except Exception as _:
        return
    await manager.shutdown()
    _logger.info("AI safety stopped")
