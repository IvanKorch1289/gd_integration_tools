"""S93 W5 — ForkJoinProcessor: explicit join semantics поверх ParallelProcessor.

DSL-процессор, оборачивающий ``ParallelProcessor`` и применяющий aggregation
стратегию к результатам веток.

Aggregation modes:
- ``collect`` (default): результат = ``{branch_name: result}`` dict, сохраняется
  в ``exchange.properties["fork_join_results"]`` и в ``exchange.body``.
- ``merge``: результаты мерджатся в один dict (B dict'ов → 1 dict) и кладётся
  в body. Полезно для оркестрации независимых lookup'ов.
- ``first``: первый не-None результат (по порядку dict-insertion) становится
  body. Удобно для fallback-цепочек в parallel-режиме.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.fork_join")


class ForkJoinProcessor(BaseProcessor):
    """Fork-Join с explicit aggregation.

    Args:
        branches: Map имя → процессоры (аналог ``parallel``).
        aggregation: ``collect`` | ``merge`` | ``first``.
        timeout_seconds: Опциональный таймаут для ``asyncio.gather``.
    """

    __slots__ = ("_aggregation", "_branches", "_timeout_seconds")

    _VALID_AGGREGATIONS = frozenset({"collect", "merge", "first"})

    def __init__(
        self,
        branches: dict[str, list[BaseProcessor]],
        *,
        aggregation: str = "collect",
        timeout_seconds: float | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "fork_join")
        if aggregation not in self._VALID_AGGREGATIONS:
            raise ValueError(
                f"aggregation must be one of {sorted(self._VALID_AGGREGATIONS)}, "
                f"got {aggregation!r}"
            )
        if not branches:
            raise ValueError("ForkJoinProcessor: branches cannot be empty")
        self._branches = dict(branches)
        self._aggregation = aggregation
        self._timeout_seconds = timeout_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Параллельно выполняет ветки (fork) и объединяет результаты (join).

        Каждая ветка получает собственный копию exchange (body + headers).
        Ветки выполняются concurrently через ``asyncio.gather``; при
        ``timeout_seconds`` — оборачивается в ``asyncio.wait_for``. Если любая
        ветка упала — exchange переходит в ``failed``. Успешные результаты
        агрегируются (collect/merge/first/all) и записываются в body.

        Args:
            exchange: Текущий exchange; результаты — в свойстве
                ``fork_join_results`` и ``in_message.body``.
            context: Контекст выполнения маршрута.
        """
        # Делегируем выполнение в ParallelProcessor (battle-tested).
        # Run inline — повторяет логику ParallelProcessor._run_branch,
        # но это OK: композиция > дублирование.
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        async def run_one(name: str, procs: list[BaseProcessor]) -> None:
            from src.backend.dsl.engine.exchange import ExchangeStatus, Message

            branch_ex = Exchange(
                in_message=Message(
                    body=exchange.in_message.body,
                    headers=dict(exchange.in_message.headers),
                )
            )
            branch_ex.status = ExchangeStatus.processing
            for proc in procs:
                if branch_ex.status in (ExchangeStatus.failed,) or branch_ex.stopped:
                    break
                try:
                    await proc.process(branch_ex, context)
                except Exception as exc:  # noqa: BLE001
                    branch_ex.fail(str(exc))
                    break
            if branch_ex.status == ExchangeStatus.failed:
                errors[name] = branch_ex.error or "unknown error"
            else:
                results[name] = branch_ex.in_message.body

        tasks = [run_one(n, p) for n, p in self._branches.items()]
        if self._timeout_seconds is not None:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=False),
                timeout=self._timeout_seconds,
            )
        else:
            await asyncio.gather(*tasks, return_exceptions=False)

        if errors:
            # Любой fail → exchange fail
            exchange.fail(f"ForkJoin failed: {errors}")
            return

        # Apply aggregation
        aggregated = self._apply_aggregation(results)
        exchange.set_property("fork_join_results", results)
        exchange.in_message.body = aggregated

    def _apply_aggregation(self, results: dict[str, Any]) -> Any:
        if self._aggregation == "collect":
            return dict(results)
        if self._aggregation == "merge":
            merged: dict[str, Any] = {}
            for v in results.values():
                if isinstance(v, dict):
                    merged.update(v)
                else:
                    # non-dict branch в merge: keep as "_<index>"
                    merged[f"branch_{len(merged)}"] = v
            return merged
        if self._aggregation == "first":
            for v in results.values():
                if v is not None:
                    return v
            return None
        # Should not happen (validated in __init__).
        raise ValueError(f"Unknown aggregation: {self._aggregation}")
