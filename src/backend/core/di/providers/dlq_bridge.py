"""DLQ (Dead-Letter Queue) bridge — lazy accessors for ``messaging.dlq_base``.

Extracted from the monolithic ``infrastructure_facade.py`` (S171 decomp).
Each accessor performs a lazy import so that infrastructure modules are
not loaded until first call, preserving import-time isolation (D102).

Covers:
    * ``DLQEnvelope`` class
    * ``DLQReason`` class
    * ``DLQWriter`` class
    * full ``messaging.dlq_base`` module
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_dlq_envelope_class",
    "get_dlq_base_module",
    "get_dlq_reason_class",
    "get_dlq_writer_class",
)


def get_dlq_envelope_class() -> Any:
    """Возвращает ``DLQEnvelope`` class."""
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

    return DLQEnvelope


def get_dlq_base_module() -> Any:
    """Возвращает ``messaging.dlq_base`` module."""
    from src.backend.infrastructure.messaging import dlq_base

    return dlq_base


def get_dlq_reason_class() -> Any:
    """Возвращает ``messaging.dlq_base.DLQReason`` class."""
    from src.backend.infrastructure.messaging.dlq_base import DLQReason

    return DLQReason


def get_dlq_writer_class() -> Any:
    """Возвращает ``messaging.dlq_base.DLQWriter`` class."""
    from src.backend.infrastructure.messaging.dlq_base import DLQWriter

    return DLQWriter
