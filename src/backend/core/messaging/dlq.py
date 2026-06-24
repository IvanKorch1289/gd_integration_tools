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

def __getattr__(name: str) -> Any:
    if not TYPE_CHECKING:
        if name in ("DLQEnvelope", "DLQReason", "DLQWriter"):
            from src.backend.core.di.providers.infrastructure_facade import (
                get_dlq_base_module as _get_dlq_base_fn,
            )

            return getattr(_get_dlq_base_fn(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ("DLQEnvelope", "DLQReason", "DLQWriter")
