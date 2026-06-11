from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Callable
from typing import Literal

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.workflow.pg_runner_internals import WorkflowState

_logger = get_logger("workflow.executor")

# -- Declarative spec types (serializable, hot-reloadable) --------------

StepKind = Literal[
    "sequential",  # linear processors chain
    "branch",  # if/else on predicate
    "loop",  # while with max_iter
    "for_each",  # map over collection
    "sub_flow",  # spawn child workflow + pause
    "wait",  # durable pause (next_attempt_at)
    "compensate",  # rollback chain (failure-only)
]


class EvalMixin:
    """predicate + expression evaluation для DSLStepExecutor. S61 W3 extraction."""

    __slots__ = ()

    def _eval_predicate(
        self,
        predicate: Callable[[WorkflowState], bool] | str | None,
        state: WorkflowState,
    ) -> bool:
        if predicate is None:
            return True
        if callable(predicate):
            return bool(predicate(state))
        # JMESPath evaluated against exchange_snapshot
        result = self._eval_expression(predicate, state)
        return bool(result)

    def _eval_expression(self, expr: str | None, state: WorkflowState) -> Any:
        if expr is None:
            return None
        try:
            import jmespath

            return jmespath.search(expr, state.exchange_snapshot)
        except Exception as exc:
            _logger.warning(
                "jmespath eval failed", extra={"expr": expr, "error": str(exc)}
            )
            return None
