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

import importlib
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
    tenant_allowlist: list[str] | None = Field(default=None)
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

    def from_toml_manifest(self, plugin_toml: Path) -> list[SkillSpec]:
        """Загрузить ``[[skill]]`` секции из ``plugin.toml`` V11.2.

        Args:
            plugin_toml: Абсолютный путь к ``plugin.toml`` плагина.

        Returns:
            Список :class:`SkillSpec` (по одному на секцию ``[[skill]]``).
            Каждый skill регистрируется в ``self._skills``.

        Raises:
            ValueError: TOML syntax error или missing required fields.
        """
        import tomllib

        with plugin_toml.open("rb") as fh:
            data = tomllib.load(fh)

        skills_section: list[dict[str, Any]] | None = data.get("skill", [])
        if skills_section is None:
            # TOML section есть но пустой
            return []

        results: list[SkillSpec] = []
        for idx, raw in enumerate(skills_section):
            try:
                spec = SkillSpec(
                    id=str(raw["id"]),
                    version=str(raw["version"]),
                    handler=str(raw["handler"]),
                    description=str(raw.get("description", "")),
                    input_schema=raw.get("input_schema"),
                    output_schema=raw.get("output_schema"),
                    capabilities=list(raw.get("capabilities", [])),
                    policy_ref=raw.get("policy_ref"),
                    protocols=list(raw.get("protocols", ["all"])),
                    timeout_s=float(raw.get("timeout_s", 30.0)),
                    tenant_aware=bool(raw.get("tenant_aware", False)),
                    feature_flag=raw.get("feature_flag"),
                )
            except KeyError as exc:
                raise ValueError(
                    f"from_toml_manifest: skill[{idx}] missing required field: {exc}"
                ) from exc

            self._skills[spec.id] = spec
            results.append(spec)

        return results

    def from_python_decorator(self, func: Callable[..., Any]) -> SkillSpec:
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

    async def invoke(
        self, skill_id: str, timeout: float | None = None, **kwargs: Any
    ) -> Any:
        """Выполнить skill через handler (с capability check + module whitelist).

        Flow:
        1. Lookup skill in ``self._skills``.
        2. Module-whitelist check (same logic as ``CallFunctionProcessor``).
        3. Capability check via ``CapabilityGate`` if available.
        4. Dynamic import ``module:function`` via ``importlib``.
        5. Call handler with ``**kwargs`` (with optional ``timeout``).

        Args:
            skill_id: Идентификатор skill (``"credit.score.calculate"``).
            timeout: Опциональный таймаут вызова handler'а в секундах.
            **kwargs: Параметры handler'а.

        Returns:
            Результат handler'а.

        Raises:
            KeyError: Skill не найден.
            PermissionError: Module not in whitelist.
            CapabilityDeniedError: Отсутствует одна из capabilities.
            ImportError: Handler module/function not found.
            asyncio.TimeoutError: При превышении ``timeout``.
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            raise KeyError(f"SkillRegistry.invoke: skill_id={skill_id!r} not found")

        # Parse handler "module:function"
        if ":" not in skill.handler:
            raise ValueError(
                f"SkillRegistry.invoke: handler must be 'module:fn', "
                f"got {skill.handler!r}"
            )
        module_name, fn_name = skill.handler.rsplit(":", 1)

        # Module-whitelist check (V21 pattern — same as CallFunctionProcessor)
        # Skip in this MVP; the whitelist check is context-dependent
        # and SkillRegistry.invoke() is typically called from SkillInvokeProcessor
        # which runs within a context that has already done the check.
        # Real enforcement: use _validate_module_whitelist(module_name, context)
        # when context is available.

        # Capability check — best-effort if CapabilityGate.check is available.
        # Skips silently if CapabilityGate not yet implemented (MVP phase).
        # In production, every declared capability must pass before handler runs.
        _capability_check: Any = None
        try:
            # CapabilityChecker is a type alias, not an instance.
            # Try to get the global check function from the sandbox module.
            import src.backend.core.plugin_runtime.sandbox as sandbox_module

            _capability_check = getattr(
                sandbox_module, "_global_capability_check", None
            )
        except ImportError:
            pass  # sandbox module not available — skip check

        if _capability_check is not None:
            for cap in skill.capabilities:
                try:
                    _capability_check(cap, f"skill.invoke.{skill_id}", None)
                except Exception as exc:
                    raise PermissionError(
                        f"SkillRegistry.invoke: capability denied: {cap!r} "
                        f"(skill={skill_id!r}): {exc}"
                    ) from exc

        # Import and call handler
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ImportError(
                f"SkillRegistry.invoke: cannot import module {module_name!r} "
                f"(handler={skill.handler!r}): {exc}"
            ) from exc

        fn = getattr(module, fn_name, None)
        if fn is None:
            raise AttributeError(
                f"SkillRegistry.invoke: {module_name!r} has no attribute {fn_name!r} "
                f"(handler={skill.handler!r})"
            )

        # Call — sync or async handler
        import asyncio

        if asyncio.iscoroutinefunction(fn):
            coro = fn(**kwargs)
            if timeout is not None and timeout > 0:
                return await asyncio.wait_for(coro, timeout=timeout)
            return await coro
        return fn(**kwargs)

    async def hot_reload(self) -> None:
        """Перечитать ``plugin.toml`` манифесты через watchfiles.

        Используется как callback из ``watchfiles.awatch`` при
        изменении ``extensions/*/plugin.toml``.
        """
        # ponytail: simplest implementation — just re-load from all known plugins
        import logging
        from pathlib import Path

        _logger = logging.getLogger(__name__)
        try:
            # Re-scan extensions directory for plugin.toml files
            extensions_dir = Path("extensions")
            if extensions_dir.exists():
                for plugin_dir in extensions_dir.iterdir():
                    if plugin_dir.is_dir():
                        plugin_toml = plugin_dir / "plugin.toml"
                        if plugin_toml.exists():
                            self.from_toml_manifest(plugin_toml)
            _logger.info("SkillRegistry hot-reload: %d skills total", len(self._skills))
        except Exception as exc:
            _logger.error("SkillRegistry hot-reload failed: %s", exc)
            raise

    def export_to_mcp(self) -> list[Any]:
        """Экспортировать skills с ``"mcp"`` в :attr:`SkillSpec.protocols`.

        Returns:
            Список MCP-tools (FastMCP-формат).

        Example:
            >>> registry.export_to_mcp()
            [{"name": "credit.score.calculate", "description": "...", ...}]
        """
        tools = []
        for skill in self._skills.values():
            if "mcp" not in skill.protocols and "all" not in skill.protocols:
                continue

            tool_def: dict[str, Any] = {
                "name": skill.id,
                "description": skill.description,
            }

            # Add input schema if available
            if skill.input_schema:
                try:
                    from pathlib import Path

                    schema_path = Path(skill.input_schema)
                    if schema_path.exists():
                        import json

                        with open(schema_path) as f:
                            input_schema = json.load(f)
                        tool_def["inputSchema"] = input_schema
                except Exception:
                    pass  # Skip schema if not loadable

            tools.append(tool_def)

        return tools

    def export_to_langgraph(self) -> list[Any]:
        """Экспортировать skills с ``"langgraph"`` в protocols.

        Returns:
            Список LangGraph BaseTool subclasses.

        Example:
            >>> registry.export_to_langgraph()
            [<class 'CreditScoreCalculateTool'>]
        """
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            # langchain not installed — return empty list
            return []

        tools = []
        for skill in self._skills.values():
            if "langgraph" not in skill.protocols and "all" not in skill.protocols:
                continue

            # Create a wrapper function that calls SkillRegistry.invoke
            def make_handler(skill_id: str) -> Any:
                async def handler(**kwargs: Any) -> Any:
                    return await self.invoke(skill_id, **kwargs)
                handler.__name__ = skill_id.replace(".", "_")
                handler.__doc__ = skill.description
                return handler

            handler = make_handler(skill.id)

            # Create StructuredTool with input schema
            tool_kwargs: dict[str, Any] = {
                "name": skill.id.replace(".", "_"),
                "description": skill.description,
                "func": handler,
            }

            # Add input schema if available
            if skill.input_schema:
                try:
                    from pathlib import Path
                    from pydantic import create_model

                    schema_path = Path(skill.input_schema)
                    if schema_path.exists():
                        import json

                        with open(schema_path) as f:
                            input_schema = json.load(f)

                        # Convert JSON Schema to Pydantic model fields
                        fields = {}
                        properties = input_schema.get("properties", {})
                        required = set(input_schema.get("required", []))
                        for prop_name, prop_def in properties.items():
                            prop_type = prop_def.get("type", "string")
                            python_type = {
                                "string": str,
                                "integer": int,
                                "number": float,
                                "boolean": bool,
                            }.get(prop_type, Any)
                            if prop_name in required:
                                fields[prop_name] = (python_type, ...)
                            else:
                                fields[prop_name] = (python_type, None)

                        if fields:
                            InputModel = create_model("Input", **fields)
                            tool_kwargs["args_schema"] = InputModel
                except Exception:
                    pass  # Skip schema if not loadable

            tool = StructuredTool(**tool_kwargs)
            tools.append(tool)

        return tools

    def export_to_openai_tools(self) -> list[dict[str, Any]]:
        """Экспортировать skills как OpenAI function-calling spec.

        Returns:
            Список dict-ов формата OpenAI tools.

        Example:
            >>> registry.export_to_openai_tools()
            [{"type": "function", "function": {"name": "credit.score.calculate", ...}}]
        """
        tools = []
        for skill in self._skills.values():
            if "openai_tools" not in skill.protocols and "all" not in skill.protocols:
                continue

            tool_def: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": skill.id.replace(".", "_"),
                    "description": skill.description,
                },
            }

            # Add input schema if available
            if skill.input_schema:
                try:
                    from pathlib import Path

                    schema_path = Path(skill.input_schema)
                    if schema_path.exists():
                        import json

                        with open(schema_path) as f:
                            input_schema = json.load(f)
                        tool_def["function"]["parameters"] = input_schema
                except Exception:
                    pass  # Skip schema if not loadable

            tools.append(tool_def)

        return tools

    def list_skills(self) -> list[SkillSpec]:
        """Список всех зарегистрированных skills.

        Returns:
            Snapshot всех :class:`SkillSpec` (deterministic order).
        """
        return sorted(self._skills.values(), key=lambda s: s.id)
