"""Workflow runtime settings (Sprint 4 К3-B §5).

D-AUDIT-A8-05 fix (cycle 1): поле ``bootstrap_defaults_enabled`` удалено.
Ранее управляло default-OFF feature-flag для bootstrap saga-деклараций,
но saga-демо удалены в коммите 9164a59, и единственный потребитель поля
(``_bootstrap_default_declarations``) также удалён. Поле осиротело.

Плагины подключают свои workflow декларации через PluginLoader,
ядро не диктует доменно-специфичные workflow.

См. PLAN.md V16 §4 Sprint 4 К3-B (Workflow & Orchestration).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("WorkflowSettings", "workflow_settings")


class WorkflowSettings(BaseSettingsWithLoader):
    """Конфигурация runtime workflow-стека.

    D-AUDIT-A8-05 fix (cycle 1): содержит только ``yaml_group`` + ``model_config``,
    без полей. Расширение — по мере добавления workflow-runtime настроек.
    """

    yaml_group: ClassVar[str] = "workflow"
    model_config = SettingsConfigDict(
        env_prefix="WORKFLOW_", extra="forbid", validate_default=True,
    )


workflow_settings: WorkflowSettings = WorkflowSettings()
"""Глобальный экземпляр workflow-настроек."""
