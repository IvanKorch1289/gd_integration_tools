"""Observability providers — SLO tracker, health aggregator, audit store, metrics emitters.

W9 P2-13 Phase 2 (cycle 153, MINIMAX plan): извлечено из
``core/di/providers/cache.py`` (868 LOC god-module, misattributed during
M2-#11 batch 7-19). Cache.py содержал 89 funcs в 26 concerns; observability-
related providers (SLO/health/audit/metrics emitters) логически отдельный
домен.

Back-compat: ``core/di/providers/cache.py`` продолжает re-export этих
функций через lazy ``__getattr__`` proxy (см. ADR-0321).

Singleton cache ``_overrides`` is per-domain (NOT shared) — каждый domain
имеет свой override-словарь для изоляции тестов и предотвращения
collisions между несвязанными singleton'ами.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─────────────── SLO tracker ───────────────


def get_slo_tracker_provider() -> Any:
    """Получить SLO tracker из overrides или resolve через ``app.slo_tracker``."""
    if "slo_tracker" in _overrides:
        return _overrides["slo_tracker"]
    module = resolve_module("app.slo_tracker")
    return module.get_slo_tracker()


def set_slo_tracker_provider(tracker: Any) -> None:
    """Установить override для ``slo_tracker`` provider (test-инжекция)."""
    _overrides["slo_tracker"] = tracker


# ─────────────── Health aggregator ───────────────


def get_health_aggregator_provider() -> Any:
    """Получить health aggregator из overrides или resolve через ``app.health_aggregator``."""
    if "health_aggregator" in _overrides:
        return _overrides["health_aggregator"]
    module = resolve_module("app.health_aggregator")
    return module.get_health_aggregator()


def set_health_aggregator_provider(aggregator: Any) -> None:
    """Установить override для ``health_aggregator`` provider (test-инжекция)."""
    _overrides["health_aggregator"] = aggregator


# ─── S79 M2-#11 batch 14: observability providers (ImmutableAuditStore) ──


def get_immutable_audit_store_class_provider() -> Any:
    r"""Возвращает :class:\`ImmutableAuditStore\` (audit store).

    S79 M2-#11 batch 14: lazy resolve для dsl/processors/audit.py.
    """
    if "immutable_audit_store_class" in _overrides:
        return _overrides["immutable_audit_store_class"]
    module = resolve_module("observability.immutable_audit")
    return module.ImmutableAuditStore


def set_immutable_audit_store_class_provider(aclass: Any) -> None:
    """Test-override для ImmutableAuditStore (Sprint 79+)."""
    _overrides["immutable_audit_store_class"] = aclass


# ─── S78 M2-#11 batch 13: record_antivirus_scan metrics emitter ───────────


def get_record_antivirus_scan_provider() -> Any:
    r"""Возвращает :func:\`record_antivirus_scan\` (metrics emitter).

    S78 M2-#11 batch 13: lazy resolve для dsl/processors/scan_file.py.
    """
    if "record_antivirus_scan" in _overrides:
        return _overrides["record_antivirus_scan"]
    module = resolve_module("observability.metrics")
    return module.record_antivirus_scan


def set_record_antivirus_scan_provider(emitter: Any) -> None:
    """Test-override для record_antivirus_scan (Sprint 78+)."""
    _overrides["record_antivirus_scan"] = emitter


# ─── S87 final batch: record_express_message_sent metrics emitter ──────────


def get_record_express_message_sent_provider() -> Any:
    r"""Возвращает \`record_express_message_sent\` (metric emitter).

    S87 final batch: lazy resolve для express/send.py.
    """
    if "record_express_message_sent" in _overrides:
        return _overrides["record_express_message_sent"]
    module = resolve_module("observability.metrics")
    return module.record_express_message_sent


def set_record_express_message_sent_provider(emitter: Any) -> None:
    """Test-override (S87+)."""
    _overrides["record_express_message_sent"] = emitter


__all__ = (
    "get_health_aggregator_provider",
    "get_immutable_audit_store_class_provider",
    "get_record_antivirus_scan_provider",
    "get_record_express_message_sent_provider",
    "get_slo_tracker_provider",
    "set_health_aggregator_provider",
    "set_immutable_audit_store_class_provider",
    "set_record_antivirus_scan_provider",
    "set_record_express_message_sent_provider",
    "set_slo_tracker_provider",
)
