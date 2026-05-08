"""Builders package — декомпозиция ``RouteBuilder`` на миксины (B1 phase-2).

Stage 2.1 PoC уже перенёс первую партию методов (hash/encrypt/decrypt/
compress/decompress) в :mod:`dsl.builders.converters.ConvertersMixin`.
Остальные группы переезжают в Stage 2.2-2.6 по плану
``/home/user/.claude/plans/replicated-seeking-panda.md``.

**Lazy import**: ``RouteBuilder`` импортируется через ``__getattr__`` чтобы
избежать circular import с :mod:`dsl.builder`, который теперь сам зависит
от ``ConvertersMixin`` из этого пакета.

Marker-mixin'ы (CoreMixin/EIPMixin/...) — placeholder для doc/typing
категоризации; будут заменены реальными миксинами по мере переноса
групп методов.
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "RouteBuilder",
    "CoreMixin",
    "EIPMixin",
    "TransportMixin",
    "StreamingMixin",
    "AIMixin",
    "RPAMixin",
    "BankingMixin",
    "BankingAIMixin",
    "StorageMixin",
    "SecurityMixin",
    "ObservabilityMixin",
)


def __getattr__(name: str) -> Any:
    """Lazy resolve ``RouteBuilder`` и marker-mixin'ы — обходим circular import.

    Без этой ленивой схемы ``dsl.builder`` (импортирующий миксины из этого
    пакета) и ``dsl.builders.__init__`` (импортирующий ``RouteBuilder``)
    давали бы ImportError на стадии частичной инициализации модуля.
    """

    if name == "RouteBuilder":
        from src.backend.dsl.builder import RouteBuilder as _R

        return _R

    if name in {
        "CoreMixin",
        "EIPMixin",
        "TransportMixin",
        "StreamingMixin",
        "AIMixin",
        "RPAMixin",
        "BankingMixin",
        "BankingAIMixin",
        "StorageMixin",
        "SecurityMixin",
        "ObservabilityMixin",
    }:
        from src.backend.dsl.builder import RouteBuilder as _R

        return type(name, (_R,), {"__doc__": f"Marker-mixin {name} (B1 phase-1)."})

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
