from __future__ import annotations

"""Config base classes (S65 W3 decomp from base.py 485 LOC).

2 classes → 2 files (per-class file split):
- app_base.py: AppBaseSettings
- scheduler.py: SchedulerSettings

Backward-compat: from src.backend.core.config.base import AppBaseSettings works.
"""


from src.backend.core.config.base.app_base import AppBaseSettings  # S65 W3: re-export
from src.backend.core.config.base.scheduler import (
    SchedulerSettings,  # S65 W3: re-export
)

__all__ = ("AppBaseSettings", "SchedulerSettings")

app_base_settings: AppBaseSettings = AppBaseSettings()

scheduler_settings: SchedulerSettings = (
    SchedulerSettings()
)  # S65 W3 fixup: missing instance
