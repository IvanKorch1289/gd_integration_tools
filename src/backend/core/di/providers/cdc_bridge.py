"""CDC (Change Data Capture) bridge — lazy accessors for ``cdc.*``.

Extracted from the monolithic ``infrastructure_facade.py`` (S171 decomp).
Each accessor performs a lazy import so that infrastructure modules are
not loaded until first call, preserving import-time isolation (D102).

Covers:
    * ``CDCClientAdapter`` class
    * ``PollCDCBackend`` class
    * ``ListenNotifyCDCBackend`` class
    * ``DebeziumEventsCDCBackend`` class (two alias accessors)
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_poll_cdc_backend_class",
    "get_listen_notify_cdc_backend_class",
    "get_debezium_cdc_backend_class",
    "get_cdc_client_adapter_class",
    "get_debezium_events_cdc_backend_class",
)


def get_poll_cdc_backend_class() -> Any:
    """Возвращает ``cdc.poll_backend.PollCDCBackend`` class."""
    from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

    return PollCDCBackend


def get_listen_notify_cdc_backend_class() -> Any:
    """Возвращает ``cdc.listen_notify_backend.ListenNotifyCDCBackend`` class."""
    from src.backend.infrastructure.cdc.listen_notify_backend import (
        ListenNotifyCDCBackend,
    )

    return ListenNotifyCDCBackend


def get_debezium_cdc_backend_class() -> Any:
    """Возвращает ``cdc.debezium_events_backend.DebeziumEventsCDCBackend`` class."""
    from src.backend.infrastructure.cdc.debezium_events_backend import (
        DebeziumEventsCDCBackend,
    )

    return DebeziumEventsCDCBackend


def get_cdc_client_adapter_class() -> Any:
    """Возвращает ``cdc.cdc_client_adapter.CDCClientAdapter`` class."""
    from src.backend.infrastructure.cdc.cdc_client_adapter import CDCClientAdapter

    return CDCClientAdapter


def get_debezium_events_cdc_backend_class() -> Any:
    """Возвращает ``cdc.debezium_events_backend.DebeziumEventsCDCBackend`` class."""
    from src.backend.infrastructure.cdc.debezium_events_backend import (
        DebeziumEventsCDCBackend,
    )

    return DebeziumEventsCDCBackend
