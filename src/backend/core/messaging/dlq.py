"""DLQ Protocol re-export (Sprint 9 K2 W1).

Re-export :class:`DLQEnvelope`, :class:`DLQReason`, :class:`DLQWriter` из
:mod:`infrastructure.messaging.dlq` для unified import-path:

.. code-block:: python

    from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason, DLQWriter

S8 scaffold находится в infrastructure (исторически); S9 закрепляет
public-API в core, чтобы плагины могли использовать через
``core.messaging.*`` без layer-violation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Lazy re-export: infrastructure реализации импортируются только
    # при type-checking (mypy) и не создают runtime-зависимость core → infrastructure.
    from src.backend.infrastructure.messaging.dlq_base import (
        DLQEnvelope,
        DLQReason,
        DLQWriter,
    )


def __getattr__(name: str) -> Any:
    if not TYPE_CHECKING:
        if name in ("DLQEnvelope", "DLQReason", "DLQWriter"):
            from src.backend.infrastructure.messaging import dlq_base

            return getattr(dlq_base, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ("DLQEnvelope", "DLQReason", "DLQWriter")
