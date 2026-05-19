"""Deprecation facade — orders_saga переехал в extensions/ (Sprint 9 K5 W4).

Sprint 9 K5 W4 (GAP-15.4): orders_saga.py перенесён в
``extensions/core_entities/orders/workflows/orders_saga.py``. Этот shim
сохраняет backwards-compat для одного спринта; будет удалён в S10.

Новый правильный импорт:

.. code-block:: python

    from extensions.core_entities.orders.workflows.orders_saga import (
        build_orders_saga_workflow,
    )
"""

from __future__ import annotations

import warnings

from extensions.core_entities.orders.workflows.orders_saga import *  # noqa: F401,F403
from extensions.core_entities.orders.workflows.orders_saga import (
    build_orders_saga_workflow,
)

warnings.warn(
    "src.backend.workflows.orders_saga is deprecated. "
    "Import from extensions.core_entities.orders.workflows.orders_saga.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("build_orders_saga_workflow",)
