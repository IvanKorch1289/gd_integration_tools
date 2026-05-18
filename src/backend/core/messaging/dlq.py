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

from src.backend.infrastructure.messaging.dlq_base import (
    DLQEnvelope,
    DLQReason,
    DLQWriter,
)

__all__ = ("DLQEnvelope", "DLQReason", "DLQWriter")
