"""CDC (Change Data Capture) domain provider — S170 NEW (Milestone 1).

Single entry point для CDC-бэкендов (Debezium/Poll/ListenNotify).
Дополняет E1 facade-pattern (S170 commit `ed02768`).

Usage::

    from src.backend.core.di.providers.cdc import get_cdc_provider

    cdc = get_cdc_provider()
    events = await cdc.fetch_events(since=last_watermark)
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


def get_cdc_provider() -> Any:
    """Вернуть singleton CDC backend."""
    if "cdc" in _overrides:
        return _overrides["cdc"]
    return resolve_module("infrastructure.cdc.registry").get_default_source()


def set_cdc_provider(cdc: Any) -> None:
    """Test-инжекция CDC backend."""
    _overrides["cdc"] = cdc


__all__ = ("get_cdc_provider", "set_cdc_provider")
