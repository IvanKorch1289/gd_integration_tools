from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_log = get_logger(__name__)

# Property name для branch decision (consumed by BranchSelector / routing logic).
BRANCH_DECISION_PROPERTY = "branch.decision"
# Sentinel: operator решил "skip downstream" (no follow-up tasks).
BRANCH_SKIP_VALUE = "__skip__"

# Type alias: branch resolver returns task/branch name (or BRANCH_SKIP_VALUE).
BranchResolver = Callable[[Exchange[Any]], str | Awaitable[str]]
Predicate = Callable[[Exchange[Any]], bool | Awaitable[bool]]


def _default_latest_checker(exchange: Exchange[Any]) -> bool:
    """Default latest-run checker: read ``is_latest_run`` from exchange headers.

    Apache Airflow convention: downstream tasks can check
    ``logical_date`` / ``is_latest_run`` metadata injected by scheduler
    to skip intermediate runs during backfill. We expose the same via
    a default predicate so users don't have to write boilerplate.

    Args:
        exchange: current :class:`Exchange` instance (headers + body).

    Returns:
        ``True`` if this is the latest run (proceed),
        ``False`` if older run (skip downstream).
        Returns ``False`` if header is missing — safe default (skip).

    .. note::
        S132 W3 fix: headers live on ``exchange.in_message`` (``Message`` model),
        not directly on ``Exchange``. ``Exchange.get_header`` does NOT exist;
        use ``exchange.in_message.get_header(key, default)``.
        This was a S65 W2 latent refactor artifact (the original code assumed
        Exchange had ``get_header`` directly, but it lives on ``Message``).
    """
    return bool(exchange.in_message.get_header("is_latest_run", False))


# ── BranchPythonOperator ─────────────────────────────────────────────


class LatestOnlyOperator(BaseProcessor):
    """Skip task если текущий run — не latest в DAG.

    Apache Airflow LatestOnlyOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#latestonlyoperator

    Полезен для backfill: при запуске historical runs (backfill mode) часто
    нужно skip промежуточные tasks и оставить только latest.

    Args:
        latest_run_checker: callable(exchange) → bool. ``True`` если это
            latest run, ``False`` если старый. Если None — uses
            :meth:`_default_latest_checker` (checks ``is_latest_run`` header).
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self, latest_run_checker: Predicate | None = None, *, name: str | None = None
    ) -> None:
        super().__init__(name=name or "latest_only")
        self._checker = latest_run_checker or _default_latest_checker

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        is_latest = self._checker(exchange)
        if asyncio.iscoroutine(is_latest):
            is_latest = await is_latest

        if is_latest:
            _log.debug("LatestOnlyOperator: this IS the latest run, proceed")
            return

        _log.debug("LatestOnlyOperator: NOT the latest run, skip downstream")
        exchange.set_property(BRANCH_DECISION_PROPERTY, BRANCH_SKIP_VALUE)
        exchange.set_property("latest_only.skipped", True)
        exchange.stop()

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "latest_only"}
