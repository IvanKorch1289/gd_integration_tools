"""Пакет plugin_runtime — runtime-проверки plugin.toml манифестов.

Экспортирует:
    SemverCheckResult — результат проверки semver-совместимости плагина.
    check_plugin_semver — проверить один plugin.toml на semver-совместимость.
    is_compatible — проверить совместимость requires_core с версией ядра.
"""

from __future__ import annotations

from src.backend.core.plugin_runtime.semver_checker import (
    SemverCheckResult,
    check_plugin_semver,
    is_compatible,
)

__all__ = (
    "SemverCheckResult",
    "check_plugin_semver",
    "is_compatible",
)
