"""Типы DI-контейнера для DSL.

Sprint 40 W1 — lightweight DI primitives для RouteBuilder / call_function.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class InjectMarker:
    """Маркер параметра, требующего DI-резолва.

    Аналог ``fastapi.Depends``, но для DSL-контекста (non-request).
    """

    key: str | None = None
    """Ключ в ``module_registry`` или ``app.state``. Если ``None`` —
    тип параметра используется как lookup-key (convention-over-configuration)."""

    factory: Callable[..., Any] | None = None
    """Опциональная factory-функция. Если задана — вызывается вместо
    registry/app_state lookup."""

    def __call__(self) -> Any:
        """Hack для type-checker'ов: ``= Container.depends()`` выглядит
        как default-значение, но на самом деле — маркер."""
        return self
