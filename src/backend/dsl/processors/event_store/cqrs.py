"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors.event_store/cqrs.py``.

Ранее здесь был полный дубликат CQRS-классификации. Теперь legacy-путь
реэкспортирует canonical-классы, поэтому ``Projection``/``CommandBus``/
``QueryBus``/``CQRSMixin`` — те же объекты классов, что и в canonical-пути.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.event_store.cqrs import CommandBus as CommandBus
from src.backend.dsl.engine.processors.event_store.cqrs import CQRSMixin as CQRSMixin
from src.backend.dsl.engine.processors.event_store.cqrs import Projection as Projection
from src.backend.dsl.engine.processors.event_store.cqrs import QueryBus as QueryBus

__all__ = ("CQRSMixin", "CommandBus", "Projection", "QueryBus")
