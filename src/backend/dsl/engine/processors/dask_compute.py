"""Wave 7.1 — DSL-процессор Dask compute для тяжёлых job'ов.

Поддерживаемые формы graph (декларативные, для YAML/builder):

* ``map``        — apply callable к каждому элементу body.
* ``filter``     — оставить элементы, для которых callable вернул truthy.
* ``map_partitions`` — apply callable к каждой партиции (для DataFrame).
* ``reduce``     — агрегировать через ``operator.add`` либо callable.

Каждая операция запускается через :class:`DaskBackend` (LocalCluster
или distributed). Callable резолвится по dotted path
(``pkg.module:fn``) — это безопасно для YAML-сериализации.

Если граф ``compose`` (несколько шагов) — используется ``dask.bag.Bag``
для streaming-обработки (вместо in-memory list).
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.infrastructure.execution.dask_backend import get_dask_backend

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("DaskComputeProcessor",)

_logger = logging.getLogger("dsl.dask")


def _resolve_callable(dotted: str) -> Callable[..., Any]:
    """Резолвит callable по `module.path:function_name` (или `:method`)."""
    if ":" in dotted:
        module_path, name = dotted.split(":", 1)
    elif "." in dotted:
        module_path, name = dotted.rsplit(".", 1)
    else:
        raise ValueError(f"DaskCompute: невалидный путь к callable: {dotted!r}")
    module = importlib.import_module(module_path)
    fn = getattr(module, name, None)
    if not callable(fn):
        raise ValueError(f"DaskCompute: {dotted!r} не разрешается в callable")
    return fn


class DaskComputeProcessor(BaseProcessor):
    """Wave 7.1 — выполнение dask-graph над ``body``.

    Args:
        graph: Список шагов. Каждый шаг — dict вида ``{"op": "...", "fn": "..."}``.
            Поддерживаемые ``op``: ``map``, ``filter``, ``reduce``.
        output_to: Куда писать результат (``"body"`` — default — заменить body;
            ``"headers.<key>"`` — положить в header).
        scheduler_address: Опц. адрес distributed scheduler.
        n_workers: Число воркеров LocalCluster (если scheduler не задан).

    Пример::

        builder.dask_compute(
            graph=[
                {"op": "map", "fn": "myproject.transforms:enrich"},
                {"op": "filter", "fn": "myproject.transforms:is_valid"},
                {"op": "reduce", "fn": "myproject.transforms:merge"},
            ],
            output_to="body",
        )
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        graph: list[dict[str, Any]],
        output_to: str = "body",
        scheduler_address: str | None = None,
        n_workers: int = 4,
        name: str | None = None,
    ) -> None:
        """Сохраняет описание graph; кластер поднимается лениво."""
        super().__init__(name=name or "dask_compute")
        if not graph:
            raise ValueError("DaskCompute: пустой graph")
        for step in graph:
            if "op" not in step:
                raise ValueError(f"DaskCompute: step без 'op': {step!r}")
        self._graph = graph
        self._output_to = output_to
        self._backend = get_dask_backend(
            scheduler_address=scheduler_address, n_workers=n_workers
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет graph и сохраняет результат в body / header."""
        import dask.bag as db

        body = exchange.in_message.body
        if body is None:
            return
        rows = body if isinstance(body, list) else [body]

        bag = db.from_sequence(rows, npartitions=max(1, min(8, len(rows))))
        for step in self._graph:
            bag = self._apply_step(bag, step)

        if hasattr(bag, "compute"):
            result_iterable = self._backend.compute(bag)
            result = (
                list(result_iterable)
                if hasattr(result_iterable, "__iter__")
                else result_iterable
            )
        else:
            result = bag

        self._write_result(exchange, result)

    def _apply_step(self, bag: Any, step: dict[str, Any]) -> Any:
        """Применяет один шаг graph к dask.bag."""
        op = step["op"]
        match op:
            case "map":
                fn = _resolve_callable(step["fn"])
                return bag.map(fn)
            case "filter":
                fn = _resolve_callable(step["fn"])
                return bag.filter(fn)
            case "reduce":
                fn = _resolve_callable(step["fn"])
                return bag.fold(fn)
            case _:
                raise ValueError(f"DaskCompute: неизвестная операция {op!r}")

    def _write_result(self, exchange: Exchange[Any], result: Any) -> None:
        """Кладёт результат либо в body, либо в headers.<key>."""
        if self._output_to == "body":
            exchange.in_message.body = result
            return
        if self._output_to.startswith("headers."):
            key = self._output_to.split(".", 1)[1]
            exchange.in_message.headers[key] = result
            return
        raise ValueError(
            f"DaskCompute: невалидный output_to={self._output_to!r} (ожидается 'body' или 'headers.<key>')"
        )

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        return {
            "dask_compute": {"graph": list(self._graph), "output_to": self._output_to}
        }
