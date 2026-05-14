"""Пакет plugin_runtime — runtime-проверки plugin.toml манифестов.

Экспортирует:
    SemverCheckResult — результат проверки semver-совместимости плагина.
    check_plugin_semver — проверить один plugin.toml на semver-совместимость.
    is_compatible — проверить совместимость requires_core с версией ядра.
    hot_swap — Sprint 7: reload плагина без рестарта приложения.
    HotSwapResult / HotSwapError — детали результата hot_swap.
    PluginLoaderProtocol — минимальный контракт loader для hot_swap.
"""

from __future__ import annotations

from src.backend.core.plugin_runtime.hot_swap import (
    HotSwapError,
    HotSwapResult,
    PluginLoaderProtocol,
    hot_swap,
)
from src.backend.core.plugin_runtime.semver_checker import (
    SemverCheckResult,
    check_plugin_semver,
    is_compatible,
)

__all__ = (
    "HotSwapError",
    "HotSwapResult",
    "PluginLoaderProtocol",
    "SemverCheckResult",
    "check_plugin_semver",
    "hot_swap",
    "is_compatible",
)
