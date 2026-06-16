from __future__ import annotations

from typing import Any, Self

from src.backend.dsl.builders.base._protocol import _RouteBuilderProtocol
from src.backend.dsl.engine.middleware import (
    ErrorNormalizerMiddleware,
    MetricsMiddleware,
    ProcessorMiddleware,
    TimeoutMiddleware,
)


class MiddlewareMixin(_RouteBuilderProtocol):
    """per-route middleware configuration для RouteBuilder."""

    __slots__ = ()

    _MIDDLEWARE_REGISTRY: dict[
        str, type[ProcessorMiddleware]
    ] = {}  # заполняется при первом вызове

    def middleware(
        self, middleware: str | ProcessorMiddleware | dict[str, Any], **kwargs: Any
    ) -> Self:
        """Добавляет middleware в pipeline (per-route override).

        Args:
            middleware: Либо имя встроенного middleware (``"timeout"``,
                ``"error_normalizer"``, ``"metrics"``), либо готовый
                экземпляр :class:`ProcessorMiddleware`, либо dict с
                ключом ``"type"`` и параметрами.
            **kwargs: Дополнительные параметры при использовании имени.

        Returns:
            RouteBuilder для fluent-chain.

        Example::

            RouteBuilder.from_("orders.import", source="timer:60s")
            .middleware("timeout", seconds=10.0)
            .middleware("metrics")
            .dispatch_action("orders.process")
            .build()
        """
        if isinstance(middleware, str):
            instance = self._build_middleware(middleware, kwargs)
        elif isinstance(middleware, dict):
            spec = dict(middleware)
            name = spec.pop("type", None)
            if not isinstance(name, str):
                raise ValueError("middleware(dict=...) требует строковый ключ 'type'")
            instance = self._build_middleware(name, spec)
        elif isinstance(middleware, ProcessorMiddleware):
            instance = middleware
        else:
            raise TypeError(
                f"middleware(...) ожидает str, dict или ProcessorMiddleware, "
                f"получено {type(middleware).__name__}"
            )

        self._middlewares.append(instance)
        return self

    @classmethod
    def _build_middleware(
        cls, name: str, kwargs: dict[str, Any]
    ) -> ProcessorMiddleware:
        """Создаёт встроенный middleware по имени."""
        if name == "timeout":
            seconds = kwargs.get("seconds", kwargs.get("default_timeout", 30.0))
            return TimeoutMiddleware(default_timeout=float(seconds))
        if name == "error_normalizer":
            return ErrorNormalizerMiddleware()
        if name == "metrics":
            return MetricsMiddleware()
        raise ValueError(
            f"Неизвестный middleware {name!r}. "
            f"Поддерживаются: timeout, error_normalizer, metrics."
        )
