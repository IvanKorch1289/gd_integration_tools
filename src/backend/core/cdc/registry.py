"""CDC backend registry — единая точка входа для всех CDC-source (S101 W1).

DEEP-RESEARCH D15 finding (S92): split-brain между R2.1 scaffold
(``infrastructure/cdc/``) и legacy (``infrastructure/clients/external/cdc/``).
DSL-миксины напрямую импортировали ``infrastructure.sources.cdc.CDCSource``
(concrete), что bypass'ило Protocol-контракт.

S101 W1 consolidation: единый factory ``get_cdc_source()`` возвращает
:data:`CDCSource` Protocol (canonical в ``core/cdc/source.py``). Все
backend'ы (R2.1 + legacy adapter) подключаются через registry.

Использование::

    from src.backend.core.cdc.registry import get_cdc_source

    # R2.1 backend (preferred)
    source = get_cdc_source("poll", profile="dev")
    source = get_cdc_source("listen_notify", profile="pg_prod", channel="cdc")
    source = get_cdc_source("debezium", bootstrap_servers="kafka:9092")

    # Legacy adapter (CDCClient → CDCSource)
    source = get_cdc_source("adapter", profile="oracle_prod", strategy="logminer")

    # Test/dev (in-memory feed)
    source = get_cdc_source("fake", events=[event1, event2])

    # DSL integration
    async for event in source.subscribe(tables=["orders"]):
        ...

Feature flag ``feature_flags.cdc_enabled`` гейтит runtime registry
(default-OFF, как и остальные CDC backends).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.cdc.source import CDCSource, FakeCDCSource
from src.backend.core.logging import get_logger

__all__ = (
    "SUPPORTED_BACKENDS",
    "get_cdc_source",
    "is_backend_available",
    "list_backends",
)

_logger = get_logger("core.cdc.registry")


# Stable backend names (DSL может reference через эту строку).
SUPPORTED_BACKENDS: frozenset[str] = frozenset(
    {
        "poll",  # R2.1 PollCDCBackend (universal timestamp-polling)
        "listen_notify",  # R2.1 ListenNotifyCDCBackend (PG LISTEN/NOTIFY)
        "debezium",  # R2.1 DebeziumEventsCDCBackend (aiokafka, 322 LOC)
        "adapter",  # legacy CDCClient adapter (multi-DB через CDCClient)
        "fake",  # in-memory FakeCDCSource (test/dev)
    }
)


def get_cdc_source(backend: str, /, **kwargs: Any) -> CDCSource:
    """Construct CDCSource для указанного backend.

    Args:
        backend: Имя backend'а — одно из :data:`SUPPORTED_BACKENDS`.
            ``poll`` / ``listen_notify`` / ``debezium`` — R2.1.
            ``adapter`` — legacy ``CDCClient`` через :class:`CDCClientAdapter`.
            ``fake`` — :class:`FakeCDCSource` (test/dev).
        **kwargs: Параметры для backend'а.
            ``profile`` (str, required for prod backends) — имя DB profile.
            ``interval_s`` / ``interval`` (float) — polling interval.
            ``timestamp_column`` (str) — column for polling cursor.
            ``strategy`` (str, adapter only) — polling / listen_notify / logminer.
            ``channel`` (str, listen_notify only) — PG channel.
            ``bootstrap_servers`` (str, debezium only) — Kafka brokers.
            ``events`` (list[CDCEvent], fake only) — pre-loaded events.

    Returns:
        :class:`CDCSource` Protocol instance.

    Raises:
        ValueError: Если ``backend`` не в :data:`SUPPORTED_BACKENDS`.
    """
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"Unknown CDC backend: {backend!r}. Supported: {sorted(SUPPORTED_BACKENDS)}"
        )

    if backend == "poll":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_poll_cdc_backend_class as _get_pcb_cls,
        )
        PollCDCBackend = _get_pcb_cls()

        return PollCDCBackend(
            profile=kwargs["profile"],
            interval_s=kwargs.get("interval_s", kwargs.get("interval", 5.0)),
            timestamp_column=kwargs.get("timestamp_column", "updated_at"),
            batch_size=kwargs.get("batch_size", 100),
            feed=kwargs.get("feed"),
        )
    if backend == "listen_notify":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_listen_notify_cdc_backend_class as _get_lncb_cls,
        )
        ListenNotifyCDCBackend = _get_lncb_cls()

        return ListenNotifyCDCBackend(
            dsn=kwargs.get("dsn") or kwargs.get("profile", ""),
            channel=kwargs.get("channel", "cdc_events"),
        )
    if backend == "debezium":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_debezium_events_cdc_backend_class as _get_decb_cls,
        )
        DebeziumEventsCDCBackend = _get_decb_cls()

        return DebeziumEventsCDCBackend(
            bootstrap_servers=kwargs.get("bootstrap_servers")
            or kwargs.get("profile", ""),
            topic_prefix=kwargs.get("topic_prefix", "debezium"),
            group_id=kwargs.get("group_id", "gd_cdc_consumer"),
        )
    if backend == "adapter":
        # Legacy: wraps CDCClient в CDCSource Protocol.
        from src.backend.core.di.providers.infrastructure_facade import (
            get_cdc_client_adapter_class as _get_cdc_ca_cls,
        )
        CDCClientAdapter = _get_cdc_ca_cls()

        return CDCClientAdapter(
            profile=kwargs["profile"],
            strategy=kwargs.get("strategy", "polling"),
            interval=kwargs.get("interval", 5.0),
            batch_size=kwargs.get("batch_size", 100),
            timestamp_column=kwargs.get("timestamp_column", "updated_at"),
            channel=kwargs.get("channel"),
        )
    # backend == "fake"
    return FakeCDCSource(events=kwargs.get("events", []))


def is_backend_available(backend: str) -> bool:
    """True если backend может быть создан в текущей среде.

    Для R2.1 (poll/listen_notify/debezium/adapter) — всегда True.
    Для backend'ов требующих optional deps (e.g. ``asyncpg`` для
    listen_notify) — проверяет import.
    """
    if backend not in SUPPORTED_BACKENDS:
        return False
    if backend == "listen_notify":
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            return False
    return True


def list_backends() -> list[str]:
    """Sorted list всех SUPPORTED_BACKENDS."""
    return sorted(SUPPORTED_BACKENDS)
