"""SkillSpec — Pydantic model для AI skill declaration (S66 M2-#8 split).

Extracted из :mod:`core.ai.skill_registry` (S26 W5 662 LOC → split per
single-responsibility, S66 M2-#8):
- :class:`SkillSpec` (this file) — Pydantic v2 data model
- :class:`SkillRegistry` (skill_registry.py) — runtime registry с 11 methods

Re-exported из :mod:`core.ai.skill_registry` для backward-compat public API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


__all__ = ("SkillSpec",)


class SkillSpec(BaseModel):
    """Описание одного AI skill (Pydantic v2).

    Маппится 1:1 на TOML-секцию ``[[skill]]`` из ``plugin.toml`` V11.2.

    Attributes:
        id: Уникальный идентификатор (``"credit.score.calculate"``).
            Конвенция: ``<domain>.<resource>.<action>``.
        version: SemVer-версия (``"1.2.0"``).
        handler: ``"module:function"`` -- должен быть в
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
        tenant_aware: Если ``True`` -- handler получает ``tenant_id`` из
            ``TenantContext`` (через DI).
        feature_flag: Опционально -- имя feature-flag из
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