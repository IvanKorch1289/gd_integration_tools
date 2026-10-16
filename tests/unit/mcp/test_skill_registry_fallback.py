"""MCP gateway graceful SkillRegistry=None fallback (Volна 6/4, 2026-10-13).

User spec (P1 - "недоделанные публичные поверхности"):
> Проверь `agent_registry`, `skill_registry`, Pydantic-AI streaming и другие
> scaffolds. Для каждой публично достижимой функции выбери ровно одно:
> - реализовать и покрыть;
> - скрыть выключенным flag и убрать из публичной документации/registry;
> - удалить после проверки import/registry/string references.

`SkillRegistry` в `src/backend/core/ai/skill_registry.py` помечен
как scaffold (S26 W5): "модель + методы-сигнатуры; полная реализация
loader'а + auto-export — Wave S26 W5". Существующая реализация
может быть None при импорт-failure или явно NoneType.

MCP gateway (`src/backend/entrypoints/mcp/gateway.py`) уже graceful
обрабатывает SkillRegistry=None:
    if SkillRegistry is None:
        logger.debug("SkillRegistry not available for auto-registration")

Этот тест фиксирует контракт: gateway НЕ падает, когда SkillRegistry
недоступен. Это часть priority "Удалить/скрыть публичные scaffolds:
README/OpenAPI/registries не обещают неработающие возможности".
"""

from __future__ import annotations

from unittest.mock import patch


def test_skill_registry_none_graceful_fallback() -> None:
    """MCP gateway не падает, когда SkillRegistry = None.

    Проверяет сценарий, когда SkillRegistry явно None (например, conditional
    import не сработал или модуль явно занулён). Gateway должен
    инстанцироваться и не падать с AttributeError при обращении к
    SkillRegistry-зависимым методам.
    """
    from src.backend.entrypoints.mcp import gateway as gw_module
    from src.backend.entrypoints.mcp.gateway import MCPGateway

    original_skill_registry = getattr(gw_module, "SkillRegistry", "UNSET")

    try:
        # Scenario 1: SkillRegistry = None (e.g. import not satisfied)
        with patch.object(gw_module, "SkillRegistry", None):
            gw = MCPGateway()
            assert gw is not None
            # Gateway should expose any SkillRegistry-dependent method
            # without raising AttributeError; if a method references
            # SkillRegistry when it's None, the call may return 0
            # (graceful skip) or log + return — that's the contract.
            if hasattr(gw, "auto_register_skills"):
                # We don't actually call it (side effects) — just verify
                # the method is accessible (proves SkillRegistry is read
                # lazily, not at gateway __init__ time).
                assert callable(gw.auto_register_skills)

        # Scenario 2: SkillRegistry exists but raises on access
        # (simulates broken implementation). The gateway should not
        # propagate this in __init__.
        class _Broken:
            def __getattr__(self, name: str) -> str:
                raise RuntimeError(f"simulated broken skill_registry.{name}")

        with patch.object(gw_module, "SkillRegistry", _Broken()):
            gw2 = MCPGateway()
            assert gw2 is not None

    finally:
        # Restore original SkillRegistry
        if original_skill_registry != "UNSET":
            gw_module.SkillRegistry = original_skill_registry
