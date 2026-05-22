"""SkillRegistry V11.2 — TOML-manifest для AI-tools (ADR-NEW-22, Sprint 26 W5).

Назначение
----------
Расширение существующего :mod:`services.ai.tools.registry` (``@agent_tool``
Python-декоратор) на TOML-manifest формат — для соответствия R-V15-6
(80% YAML / 20% Python).

Skills декларируются в ``extensions/<plugin>/plugin.toml`` секцией ``[[skill]]``::

    [[skill]]
    id            = "credit.score.calculate"
    version       = "1.2.0"
    handler       = "extensions.credit.functions.score:calculate"
    description   = "Расчёт скоринга по входным данным договора"
    input_schema  = "schemas/credit_score_input.json"
    output_schema = "schemas/credit_score_output.json"
    capabilities  = ["db.read.orders", "ai.invoke.credit_check"]
    policy_ref    = "credit_check_strict"  # ссылка на AIPolicySpec
    protocols     = ["mcp", "langgraph", "openai_tools"]
    timeout_s     = 30
    tenant_aware  = true
    feature_flag  = "CREDIT_SCORE_V2_ENABLED"

Возможности
-----------
* **from_toml_manifest()** — loader manifest'а из plugin.toml.
* **from_python_decorator()** — backward-compat для legacy
  :func:`services.ai.tools.registry.agent_tool`.
* **auto_register_to()** — auto-export в MCP/LangGraph/OpenAI tools
  на основе :attr:`SkillSpec.protocols`.
* **Hot-reload** через ``watchfiles.awatch`` (Wave B) ≤ 2s.
* **CI-gate** ``make skill-schema`` — JSON-Schema валидация.

Capability
----------
SkillRegistry intercepts ``invoke()`` и проверяет каждое имя из
:attr:`SkillSpec.capabilities` через :class:`CapabilityGate.check`.

Scaffold S26 W5: модель + методы-сигнатуры; полная реализация
loader'а + auto-export — Wave S26 W5.

См. docs/adr/0069-skill-registry-v11-2-toml.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ("SkillRegistry", "SkillSpec")


class SkillSpec(BaseModel):
    """Описание одного AI skill (Pydantic v2).

    Маппится 1:1 на TOML-секцию ``[[skill]]`` из ``plugin.toml`` V11.2.

    Attributes:
        id: Уникальный идентификатор (``"credit.score.calculate"``).
            Конвенция: ``<domain>.<resource>.<action>``.
        version: SemVer-версия (``"1.2.0"``).
        handler: ``"module:function"`` — должен быть в
            ``plugin.toml::call_function_modules`` whitelist (ADR R-V15-N V21).
        description: Человекочитаемое описание (для MCP/OpenAI tools schema).
        input_schema: Путь к JSON-Schema input'а (``"schemas/foo.json"``);
            используется для автоматической валидации.
        output_schema: Путь к JSON-Schema output'а.
        capabilities: Список capabilities, обязательных для invoke
            (``["db.read.orders", "ai.invoke.credit_check"]``).
        policy_ref: Ссылка на :class:`AIPolicySpec.name`
            (``"credit_check_strict"``); skill будет выполнен через
            :class:`AIGateway` с этой политикой.
        protocols: Список протоколов для auto-export
            (``["mcp", "langgraph", "openai_tools", "all"]``).
        timeout_s: Per-call таймаут handler'а.
        tenant_aware: Если ``True`` — handler получает ``tenant_id`` из
            ``TenantContext`` (через DI).
        feature_flag: Опционально — имя feature-flag из
            :mod:`core.config.features`; skill доступен только при
            ``FeatureFlags.<name> = True``.
    """

    id: str
    version: str
    handler: str
    description: str = ""
    input_schema: str | None = None
    output_schema: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    policy_ref: str | None = None
    protocols: list[Literal["mcp", "langgraph", "openai_tools", "all"]] = Field(
        default_factory=lambda: ["all"]
    )
    timeout_s: float = Field(default=30.0, ge=0.1)
    tenant_aware: bool = False
    feature_flag: str | None = None


class SkillRegistry:
    """Реестр AI skills (TOML manifest + Python decorator sov).

    Scaffold S26 W5 (ADR-NEW-22). Sov с :mod:`services.ai.tools.registry`
    (existing ``@agent_tool``) — backward-compat сохранён.

    Lookup:

    1. :meth:`from_toml_manifest` — V11.2 TOML loader (новый путь).
    2. :meth:`from_python_decorator` — legacy ``@agent_tool``.

    Auto-export :meth:`auto_register_to`:

    * ``"mcp"`` → :class:`MCPNamespace` (по ``id`` domain — ``credit.*``
      идёт в credit-mcp);
    * ``"langgraph"`` → LangGraph ToolRegistry;
    * ``"openai_tools"`` → OpenAI function-calling spec.

    Hot-reload: при изменении ``plugin.toml`` через watchfiles.awatch (Wave B) —
    diff (old vs new) и unregister/register changes (target ≤ 2s reload).

    Notes:
        Scaffold-методы поднимают ``NotImplementedError`` до полной
        реализации в S26 W5.
    """

    def __init__(self) -> None:
        """Инициализация пустого реестра."""
        self._skills: dict[str, SkillSpec] = {}

    def from_toml_manifest(self, plugin_toml: "Path") -> list[SkillSpec]:
        """Загрузить ``[[skill]]`` секции из ``plugin.toml`` V11.2.

        Args:
            plugin_toml: Абсолютный путь к ``plugin.toml`` плагина.

        Returns:
            Список :class:`SkillSpec` (по одному на секцию ``[[skill]]``).

        Raises:
            ValueError: При нарушении JSON-Schema (capability_required,
                handler не в whitelist).
            NotImplementedError: S26 W5 — полная реализация loader'а.
        """
        del plugin_toml
        raise NotImplementedError("S26 W5: TOML loader (ADR-NEW-22)")

    def from_python_decorator(
        self, func: "Callable[..., Any]"
    ) -> SkillSpec:
        """Создать :class:`SkillSpec` из legacy ``@agent_tool``-функции.

        Args:
            func: Декорированная функция из
                :mod:`services.ai.tools.registry`.

        Returns:
            :class:`SkillSpec` с inferred ``input_schema`` через
            ``typing.get_type_hints``.

        Raises:
            NotImplementedError: S26 W5 — bridge с existing registry.
        """
        del func
        raise NotImplementedError("S26 W5: bridge с services/ai/tools/registry")

    async def invoke(self, skill_id: str, **kwargs: Any) -> Any:
        """Выполнить skill через AIGateway (с capability check + policy).

        Args:
            skill_id: Идентификатор skill (``"credit.score.calculate"``).
            **kwargs: Параметры handler'а
                (валидируются через :attr:`SkillSpec.input_schema`).

        Returns:
            Результат handler'а (валидируется через
            :attr:`SkillSpec.output_schema`).

        Raises:
            KeyError: Skill не найден.
            CapabilityDeniedError: Отсутствует одна из
                :attr:`SkillSpec.capabilities`.
            NotImplementedError: S26 W5 (Capability intercept + AIGateway routing).
        """
        del skill_id, kwargs
        raise NotImplementedError("S26 W5: invoke через AIGateway + capability")

    async def hot_reload(self) -> None:
        """Перечитать ``plugin.toml`` манифесты через watchfiles.

        Используется как callback из ``watchfiles.awatch`` (Wave B) при
        изменении ``extensions/*/plugin.toml``.

        Raises:
            NotImplementedError: S26 W5.
        """
        raise NotImplementedError("S26 W5: hot-reload через watchfiles")

    def export_to_mcp(self) -> list[Any]:
        """Экспортировать skills с ``"mcp"`` в :attr:`SkillSpec.protocols`.

        Returns:
            Список MCP-tools (FastMCP-формат).

        Raises:
            NotImplementedError: S26 W5 + S27 W4 (MCPNamespace integration).
        """
        raise NotImplementedError("S26 W5 + S27 W4: MCP auto-export")

    def export_to_langgraph(self) -> list[Any]:
        """Экспортировать skills с ``"langgraph"`` в protocols.

        Returns:
            Список LangGraph BaseTool subclasses.

        Raises:
            NotImplementedError: S26 W5.
        """
        raise NotImplementedError("S26 W5: LangGraph auto-export")

    def export_to_openai_tools(self) -> list[dict[str, Any]]:
        """Экспортировать skills как OpenAI function-calling spec.

        Returns:
            Список dict-ов формата OpenAI tools.

        Raises:
            NotImplementedError: S26 W5.
        """
        raise NotImplementedError("S26 W5: OpenAI tools auto-export")

    def list_skills(self) -> list[SkillSpec]:
        """Список всех зарегистрированных skills.

        Returns:
            Snapshot всех :class:`SkillSpec` (deterministic order).
        """
        return sorted(self._skills.values(), key=lambda s: s.id)
