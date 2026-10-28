"""Config base classes (S65 W3 decomp from base.py 485 LOC).

2 classes → 2 files (per-class file split):
- app_base.py: AppBaseSettings
- scheduler.py: SchedulerSettings

Backward-compat: from src.backend.core.config.base import AppBaseSettings works.
"""

from __future__ import annotations

from src.backend.core.config.base.app_base import (
    AppBaseSettings,  # S65 W3: re-export as AppBaseSettings  # S65 W3: re-export
)
from src.backend.core.config.base.scheduler import (
    SchedulerSettings,  # S65 W3: re-export
)

# ADR-0375: константы runtime-кода как конфигурация. Импорт здесь (а не в
# ``core/config/__init__.py``) — потому что ``core/config/__init__.py``
# выполняется до инициализации ``core.logging``, а создание настроек в этот
# момент тянет логирование (циклический импорт). Здесь уже создаются
# ``app_base_settings``/``scheduler_settings`` — тот же профиль риска.
# Модуль обязан быть в ``sys.modules``: ``Settings.reload()`` пересобирает
# модульные синглтоны только импортированных модулей пакета — так
# hot-reload обновляет значения констант (ADR-0375, ЧАСТЬ C).
from src.backend.core.config.constants_settings import (  # noqa: F401
    ConstantsSettings,
    constants_settings,
)

__all__ = ("AppBaseSettings", "SchedulerSettings")

app_base_settings: AppBaseSettings = AppBaseSettings()

scheduler_settings: SchedulerSettings = (
    SchedulerSettings()
)  # S65 W3 fixup: missing instance
