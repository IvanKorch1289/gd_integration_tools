"""S128 W2 — :class:`DaskMixin`: fluent API для Dask compute в RouteBuilder.

Предоставляет декларативный classmethod ``DaskMixin.dask_compute(...)`` /
``.dask_map(...)`` для создания :class:`RouteBuilder` с шагом
:class:`DaskComputeProcessor`. Утилитарный mixin (не подмешивается в
``RouteBuilder`` — слишком узкий use case для slot'а в MRO).

Используйте::

    from src.backend.dsl.builders.dask_mixin import DaskMixin

    builder = DaskMixin.dask_compute(
        "batch.etl",
        graph=[{"op": "map", "fn": "myproject.transforms:enrich"}],
        output_to="body",
    )
    pipeline = builder.build()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class DaskMixin:
    """Dask compute fluent API для RouteBuilder. S128 W2 (TD-025)."""

    @classmethod
    def dask_compute(
        cls,
        route_id: str,
        graph: list[dict[str, Any]],
        *,
        output_to: str = "body",
        scheduler_address: str | None = None,
        n_workers: int = 4,
        **kwargs: Any,
    ) -> RouteBuilder:
        """Создаёт маршрут с :class:`DaskComputeProcessor` шагом.

        Args:
            route_id: Уникальный ID маршрута.
            graph: Список шагов графа. Каждый шаг — ``{"op": "...", "fn": "..."}``.
                Поддерживаемые ``op``: ``map``, ``filter``, ``reduce``.
            output_to: Куда писать результат (``"body"`` или ``"headers.<key>"``).
            scheduler_address: Опц. адрес distributed scheduler.
            n_workers: Число воркеров LocalCluster (если scheduler не задан).
            **kwargs: Доп. kwargs для processor (например ``name="..."``).

        Returns:
            ``RouteBuilder`` с шагом ``dask_compute``.

        Raises:
            ValueError: Пустой graph или step без ``op``.
        """
        if not graph:
            raise ValueError("DaskMixin.dask_compute: пустой graph")
        for i, step in enumerate(graph):
            if "op" not in step:
                raise ValueError(
                    f"DaskMixin.dask_compute: step[{i}] без 'op': {step!r}"
                )

        from src.backend.dsl.builders.base import RouteBuilder
        from src.backend.dsl.engine.processors.dask_compute import DaskComputeProcessor

        # DaskMixin — утилитарный класс (НЕ mixin в MRO RouteBuilder),
        # поэтому создаём RouteBuilder напрямую.
        builder = RouteBuilder(route_id=route_id)

        processor = DaskComputeProcessor(
            graph=list(graph),
            output_to=output_to,
            scheduler_address=scheduler_address,
            n_workers=n_workers,
            name=kwargs.pop("name", None),
        )
        return builder.to(processor)

    @classmethod
    def dask_map(
        cls,
        route_id: str,
        fn: str,
        *,
        output_to: str = "body",
        **kwargs: Any,
    ) -> RouteBuilder:
        """Shortcut: одностeпенный graph с ``map`` операцией.

        Args:
            route_id: Уникальный ID маршрута.
            fn: Dotted path к callable (``module.path:function``).
            output_to: Куда писать результат.
            **kwargs: Доп. kwargs для ``dask_compute``.
        """
        return cls.dask_compute(
            route_id=route_id,
            graph=[{"op": "map", "fn": fn}],
            output_to=output_to,
            **kwargs,
        )
