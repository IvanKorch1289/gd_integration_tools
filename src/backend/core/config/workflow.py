"""Workflow runtime settings (Sprint 4 К3-B §5).

Управляет default-OFF feature-flag для bootstrap saga-деклараций
(``orders_saga`` + ``payments_saga``). По умолчанию выключено —
плагины подключают свои workflow декларации через PluginLoaderV11,
ядро не диктует доменно-специфичные саги.

См. PLAN.md V16 §4 Sprint 4 К3-B (Workflow & Orchestration).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("WorkflowSettings", "workflow_settings")


class WorkflowSettings(BaseSettingsWithLoader):
    """Конфигурация runtime workflow-стека.

    Поля:
        bootstrap_defaults_enabled: Включает регистрацию saga-деклараций
            (``orders_saga`` + ``payments_saga``) из :mod:`workflows.*`
            на startup. По умолчанию ``False`` — доменно-специфичные
            workflow подключаются через плагины (V11.1a контракт).
    """

    yaml_group: ClassVar[str] = "workflow"
    model_config = SettingsConfigDict(
        env_prefix="WORKFLOW_", extra="forbid", validate_default=True
    )

    bootstrap_defaults_enabled: bool = Field(
        default=False,
        title="Подключить дефолтные saga-декларации на startup",
        description=(
            "Если True — на startup регистрируются orders_saga + "
            "payments_saga из src.backend.workflows. По умолчанию "
            "выключено: доменно-специфичные workflow должны идти "
            "через плагины (extensions/<name>/workflows/)."
        ),
    )


workflow_settings: WorkflowSettings = WorkflowSettings()
"""Глобальный экземпляр workflow-настроек."""
