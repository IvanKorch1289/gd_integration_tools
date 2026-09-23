"""DLQ providers — DI bridge + memory writer + envelope class (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153): извлечено из ``core/di/providers/workflow.py``
(602 LOC god-module). Содержит di_bridge_dlq + dlq_memory_writer + dlq_envelope_class +
stream_dlq_writer.

Back-compat: ``core/di/providers/workflow.py`` (file) продолжает re-export
все 7 funcs (3 DLQ + stream DLQ writer + set_*) через thin ``__init__.py`` shim (см. ADR-0331).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─────────────── Stream DLQ writer (cycle-5/D-AUDIT-504) ───────────────
#
# MQ subscribers (``entrypoints/stream/subscribers.py``,
# ``entrypoints/stream/invoker_subscribers.py``) используют
# ``get_stream_dlq_writer_provider()`` для enqueue poison message в
# DLQ при exception в handler (B-17 fail-loud pattern).
#
# Composition root (``plugins/composition/di.py``) ОБЯЗАН вызвать
# ``set_stream_dlq_writer_provider(writer)`` после wiring'a
# :class:`InboxDLQWriter` — иначе MQ poison-message теряются
# (silent fallback с warning-логом).


def get_stream_dlq_writer_provider() -> Any:
    """Возвращает ``DLQWriter`` для MQ subscribers.

    Returns:
        ``None`` если composition root не установил writer — MQ handlers
        log warning и drop poison message (fail-loud signal).

    """
    return _overrides.get("stream_dlq_writer")


def set_stream_dlq_writer_provider(writer: Any) -> None:
    """Установить override для ``stream_dlq_writer`` provider."""
    _overrides["stream_dlq_writer"] = writer


# ─── W9 P2-13 Phase 2: DLQ providers (migrated from cache.py) ──────────


def get_di_bridge_dlq_module_provider() -> Any:
    r"""Возвращает \`di_bridge.dlq\` module (SAGA DLQ bridge).

    S87 final batch (legacy): lazy resolve для security/pii_erase.py.
    W9 P2-13 Phase 7: перенесено в workflow/_dlq.py.
    """
    if "di_bridge_dlq" in _overrides:
        return _overrides["di_bridge_dlq"]
    module = resolve_module("di_bridge.dlq")
    return module


def set_di_bridge_dlq_module_provider(module: Any) -> None:
    """Установить override для ``di_bridge_dlq`` provider."""
    _overrides["di_bridge_dlq"] = module


def get_dlq_memory_writer_module_provider() -> Any:
    r"""Возвращает \`messaging.dlq.memory_writer\` module (in-memory DLQ)."""
    if "dlq_memory_writer" in _overrides:
        return _overrides["dlq_memory_writer"]
    module = resolve_module("messaging.dlq.memory_writer")
    return module


def set_dlq_memory_writer_module_provider(module: Any) -> None:
    """Установить override для ``dlq_memory_writer`` provider."""
    _overrides["dlq_memory_writer"] = module


def get_dlq_envelope_class_provider() -> Any:
    r"""Возвращает \`di_bridge.dlq\` module (DLQEnvelope/DLQReason accessors).

    S87 final batch (legacy): lazy resolve для security/pii_erase.py. Модуль
    предоставляет ``get_dlq_envelope_class()`` / ``get_dlq_reason_class()``
    (атрибута ``DLQEnvelope`` в di_bridge.dlq нет — только accessor-функции).
    W9 P2-13 Phase 7: перенесено в workflow/_dlq.py.
    """
    if "dlq_envelope_class" in _overrides:
        return _overrides["dlq_envelope_class"]
    module = resolve_module("di_bridge.dlq")
    return module


def set_dlq_envelope_class_provider(aclass: Any) -> None:
    """Установить override для ``dlq_envelope_class`` provider."""
    _overrides["dlq_envelope_class"] = aclass
