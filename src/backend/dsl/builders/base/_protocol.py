"""Structural protocol used by RouteBuilder mixins for type-checking.

This protocol lives in its own module to break the circular import between
``RouteBuilder`` and the mixin files. Mixins inherit from it so that ``self``
is treated as having the common RouteBuilder attributes and helpers without
resorting to ``self: RouteBuilder`` annotations (which mypy rejects because
``RouteBuilder`` is not a nominal superclass of the mixin).
"""

from __future__ import annotations

from typing import Any, Protocol, Self

from src.backend.dsl.engine.processors import BaseProcessor


class _RouteBuilderProtocol(Protocol):
    """Common shape expected by the base RouteBuilder mixins."""

    route_id: str
    source: str
    description: str | None

    _description: str
    _feature_flag: Any
    _middlewares: list[Any]
    _processors: list[BaseProcessor]
    _protocol: Any
    _transport_config: Any

    def _add(self, processor: BaseProcessor) -> Self: ...

    def _add_lazy(self, import_path: str, class_name: str, **kwargs: Any) -> Self: ...

    def _last_processor_or_raise(self) -> BaseProcessor: ...

    @staticmethod
    def _set_first_attr(
        obj: Any, candidates: tuple[str, ...], value: Any
    ) -> str | None: ...

    def _validate_action_names(self) -> None: ...

    @classmethod
    def from_(
        cls, route_id: str, source: str, *, description: str | None = None
    ) -> Self: ...
