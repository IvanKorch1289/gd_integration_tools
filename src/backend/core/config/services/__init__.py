"""Per-service settings singletons (PEP 562 lazy facade).

Public API: каждый ``Settings``-класс и singleton-instance (e.g.,
``CacheSettings``, ``cache_settings``) доступен через attribute access.
Сохранена обратная совместимость для всех 38 public symbols через
``__all__``.

Cycle 158+ fix: lazy ``__getattr__`` proxy (per STARTUP_BOTTLENECK Option A).
Original design eagerly импортировал 15 submodules + 38 symbols, что costило
~1.374s cold-import time. После fix — ~0.01s.
"""

from __future__ import annotations

import importlib as _importlib
from typing import Any as _Any

# Per-submodule symbols (single source of truth для lazy proxy).
# Map: submodule_name → list of public symbols.
_PUBLICS: dict[str, list[str]] = {
    "cache": [
        "CacheSettings",
        "RedisSettings",
        "cache_settings",
        "redis_settings",
    ],
    "graphql": [  # S163 W13
        "GraphQLSettings",
        "graphql_settings",
    ],
    "invoker": [
        "InvokerSettings",
        "invoker_settings",
    ],
    "jupyter_hub": [
        "JupyterHubSettings",
        "jupyter_hub_settings",
    ],
    "llm": [  # S164 W2
        "LLMSettings",
        "llm_settings",
    ],
    "logging": [
        "LogStorageSettings",
        "log_settings",
    ],
    "mail": [
        "MailSettings",
        "mail_settings",
    ],
    "queue": [
        "GRPCSettings",
        "QueueSettings",
        "TasksSettings",
        "grpc_settings",
        "queue_settings",
        "tasks_settings",
    ],
    "resilience": [
        "BreakerProfile",
        "FallbackPolicy",
        "ResilienceSettings",
        "resilience_settings",
    ],
    "rpa": [  # S164 W4
        "RPASettings",
        "rpa_settings",
    ],
    "sms": [
        "SMSSettings",
        "sms_settings",
    ],
    "snapshot": [
        "SnapshotSettings",
        "snapshot_settings",
    ],
    "storage": [
        "FileStorageSettings",
        "fs_settings",
    ],
    "watermark": [
        "WatermarkSettings",
        "watermark_settings",
    ],
    "websocket": [  # S163 W13
        "WSSettings",
        "ws_settings",
    ],
}


# Inverse map: name → submodule (для быстрого __getattr__ resolution).
_LAZY_MAP: dict[str, str] = {
    sym: submodule
    for submodule, syms in _PUBLICS.items()
    for sym in syms
}


_cached: dict[str, _Any] = {}
"""Cache resolved attributes для subsequent ``__getattr__`` lookups
в пределах одного процесса (avoid repeated import cost)."""


def __getattr__(name: str) -> _Any:  # PEP 562 lazy module attribute.
    """Lazy import — load submodule когда name впервые requested.

    Saves ~1.36s в ``startup_time.py`` cold-import (per
    CONFIG_SERVICES_BOTTLENECK_2026-09-24.md investigation).
    """
    if name in _LAZY_MAP:
        submodule_name = _LAZY_MAP[name]
        module = _importlib.import_module(
            f".{submodule_name}", __name__
        )
        value = getattr(module, name)
        _cached[name] = value
        return value
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    """``dir()`` через lazy proxy + cached для tab-completion support."""
    return sorted(set(__all__) | set(_cached.keys()))


__all__ = (
    "BreakerProfile",
    "CacheSettings",
    "FallbackPolicy",
    "FileStorageSettings",
    "GRPCSettings",
    "GraphQLSettings",  # S163 W13
    "InvokerSettings",
    "JupyterHubSettings",
    "LLMSettings",  # S164 W2
    "LogStorageSettings",
    "MailSettings",
    "QueueSettings",
    "RPASettings",  # S164 W4
    "RedisSettings",
    "ResilienceSettings",
    "SMSSettings",
    "SnapshotSettings",
    "TasksSettings",
    "WSSettings",  # S163 W13
    "WatermarkSettings",
    "cache_settings",
    "fs_settings",
    "graphql_settings",  # S163 W13
    "grpc_settings",
    "invoker_settings",
    "jupyter_hub_settings",
    "llm_settings",  # S164 W2
    "log_settings",
    "mail_settings",
    "queue_settings",
    "redis_settings",
    "resilience_settings",
    "rpa_settings",  # S164 W4
    "sms_settings",
    "snapshot_settings",
    "tasks_settings",
    "watermark_settings",
    "ws_settings",  # S163 W13
)
