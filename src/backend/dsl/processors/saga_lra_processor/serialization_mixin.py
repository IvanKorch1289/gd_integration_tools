from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.processors.saga_lra_processor.state import SagaStepSpec

if TYPE_CHECKING:
    from src.backend.dsl.engine.exchange import Exchange


_lra_logger = get_logger("dsl.saga_lra_processor")

# ── State machine constants ────────────────────────────────────────────

#: Terminal success state.
STATE_COMPLETED = "completed"
#: Transient state during compensation.
STATE_COMPENSATING = "compensating"
#: All compensations ran successfully.
STATE_COMPENSATED = "compensated"
#: At least one compensation itself failed.
STATE_FAILED = "failed"
#: Active forward execution.
STATE_RUNNING = "running"

# All known states (used for validation).
_VALID_STATES = frozenset(
    {
        STATE_RUNNING,
        STATE_COMPLETED,
        STATE_COMPENSATING,
        STATE_COMPENSATED,
        STATE_FAILED,
    }
)


class SerializationMixin:
    """step normalization + result publishing для SagaLRAProcessor. S58 W2 extraction."""

    __slots__ = ()

    @staticmethod
    def _normalize_steps(steps: list[SagaStepSpec]) -> list[SagaStepSpec]:
        """Validate step list and return a normalized copy.

        Normalization:

        * Strips non-essential keys (e.g. comments), keeps ``name``,
          ``action``, ``compensation``.
        * Generates a default name (``step_N``) if missing.
        * Detects duplicate names and empty ``action`` callables.
        """
        if not isinstance(steps, list):
            raise TypeError(f"steps должен быть list, получено {type(steps).__name__}")
        seen: set[str] = set()
        normalized: list[SagaStepSpec] = []
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):
                raise TypeError(
                    f"step #{i} должен быть dict, получено {type(raw).__name__}"
                )
            action = raw.get("action")
            if not callable(action):
                raise ValueError(
                    f"step #{i}: 'action' должен быть callable, "
                    f"получено {type(action).__name__}"
                )
            compensation = raw.get("compensation")
            if compensation is not None and not callable(compensation):
                raise ValueError(
                    f"step #{i}: 'compensation' должен быть callable или None, "
                    f"получено {type(compensation).__name__}"
                )
            name = raw.get("name") or f"step_{i}"
            if not isinstance(name, str):
                raise ValueError(
                    f"step #{i}: 'name' должен быть str, получено {type(name).__name__}"
                )
            if name in seen:
                raise ValueError(f"step #{i}: дубликат name {name!r}")
            seen.add(name)
            normalized.append(
                {"name": name, "action": action, "compensation": compensation}
            )
        return normalized

    def _publish_result(
        self,
        exchange: Exchange[Any],
        *,
        completed: list[str],
        failed_step: str | None,
        compensations_run: list[str],
        compensation_errors: list[tuple[str, str]],
        final_state: str,
        error: str | None,
    ) -> None:
        """Publish the full saga state under ``result_property``."""
        result = {
            "saga_id": self._saga_id,
            "state": final_state,
            "completed_steps": list(completed),
            "failed_step": failed_step,
            "compensations_run": list(compensations_run),
            "compensation_errors": list(compensation_errors),
            "error": error,
            "total_steps": len(self._steps),
        }
        exchange.set_property(self._result_property, result)
