"""Core RouteBuilder contracts (S3-3 / M2-#21, W9 P2-13 split).

Базовые контракты — identity, output sink, processor chain. Эти протоколы
лежат в фундаменте public API surface и импортируются остальными семействами
через ``_protocols/__init__.py`` ре-экспорт.

ADR-0320: вынесено из ``_protocols.py`` (1094 LOC god-module) в отдельный
sub-module ``_core.py`` как часть W9 P2-13 (god-object decomposition).
"""

from __future__ import annotations

from typing import Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


def _shares_prefix(a: str, b: str, n: int = 3) -> bool:
    """True если ``a`` и ``b`` имеют общий prefix длиной ≥ ``n``.

    Helper для ``__getattr__`` diagnostic (cycle 204 Tier 3):
    если запрошенный attr похож на mixin-name — suggest category.
    """
    if len(a) < n or len(b) < n:
        return False
    return a[:n].lower() == b[:n].lower()


@_runtime_checkable
class _RouteProcessorSteps(_Protocol):
    """Contract: processor chain management."""

    def _add_processor(self, processor: Any) -> Any: ...
    def _add_lazy(self, module: str, cls_name: str, **kwargs: Any) -> Any: ...


@_runtime_checkable
class _RouteCore(_Protocol):
    """Contract: core route identity + output."""

    @property
    def route_id(self) -> str: ...
    def to(self, sink: str, **kwargs: Any) -> Any: ...
    def log(self, level: str = "info", message: str = "") -> Any: ...
