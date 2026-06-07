"""PlanExecuteProcessor — Plan-and-Execute agentic pattern (v17 §2.1, #2 of 9).

Closes gap в agentic coverage (25% → +1 pattern). Plan-and-Execute —
foundational agentic pattern (AutoGPT / BabyAGI / Beam.ai [^240^]).

Workflow::

    planner(LLM) → executor(per step) → verifier (optional) → out_message
                        │                       │
                        └── replan ◄─────────────┘ (max_replans)

* Stateless: planner/executor/verifier — injected callables (DI-friendly).
* Async-first: каждый callable — ``Awaitable`` (LLM gateway / tool / etc.).
* Resilient: verifier-false → replan up to ``max_replans``.
* Observable: ``PlanResult`` в ``exchange.properties['plan_result']``.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("PlanExecuteMixin", "PlanExecuteProcessor", "PlanResult", "PlanStep")

_log = get_logger(__name__)

PlannerFn = Callable[[str], Awaitable[list["PlanStep"]]]
ExecutorFn = Callable[["PlanStep"], Awaitable[Any]]
VerifierFn = Callable[["PlanResult"], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class PlanStep:
    """Один шаг плана.

    Attributes:
        step_id: Уникальный ID (для depends_on).
        action: Действие (``"call_tool"``, ``"transform"``, ``"branch"``,
            ``"verify"``) — semantically meaningful для executor.
        params: Параметры действия, передаются в ``executor(step)``.
        depends_on: Список step_id, которые должны выполниться до этого.
    """

    step_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlanResult:
    """Результат выполнения плана.

    Attributes:
        steps_planned: План LLM (последняя итерация).
        steps_executed: ``[{"step_id", "ok", "output", "error"}, ...]``.
        steps_succeeded: Число успешных шагов.
        steps_failed: Число упавших шагов.
        final_output: Output последнего успешного шага (или ``None``).
        replans: Сколько раз был сделан replan.
        verified: ``True`` если verifier ок (``None`` если verifier нет).
        duration_ms: Длительность выполнения.
    """

    steps_planned: list[PlanStep]
    steps_executed: list[dict[str, Any]] = field(default_factory=list)
    steps_succeeded: int = 0
    steps_failed: int = 0
    final_output: Any = None
    replans: int = 0
    verified: bool | None = None
    duration_ms: float = 0.0


class PlanExecuteProcessor(BaseProcessor):
    """Plan-and-Execute agentic processor (v17 §2.1, pattern #2).

    LLM делает план → executor выполняет шаги → verifier (optional)
    проверяет → при fail — replan (до ``max_replans`` раз).

    Per Beam.ai [^240^]: foundational pattern для AutoGPT / BabyAGI /
    LangChain Agents. Сочетает LLM planning с tool execution.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        planner: PlannerFn,
        executor: ExecutorFn,
        verifier: VerifierFn | None = None,
        max_steps: int = 10,
        max_replans: int = 2,
        name: str | None = None,
    ) -> None:
        if not callable(planner):
            raise TypeError("planner должен быть callable")
        if not callable(executor):
            raise TypeError("executor должен быть callable")
        if max_steps <= 0:
            raise ValueError(f"max_steps должен быть > 0, получено {max_steps}")
        if max_replans < 0:
            raise ValueError(f"max_replans должен быть >= 0, получено {max_replans}")
        super().__init__(name=name or "plan_execute")
        self._planner = planner
        self._executor = executor
        self._verifier = verifier
        self._max_steps = max_steps
        self._max_replans = max_replans

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Plan → execute → verify (replan on fail)."""
        prompt = self._build_prompt(exchange)
        started = time.perf_counter()
        result: PlanResult | None = None
        steps = await self._planner(prompt)
        if len(steps) > self._max_steps:
            _log.warning(
                "Plan truncated: %d → %d steps (max_steps cap)",
                len(steps),
                self._max_steps,
            )
            steps = steps[: self._max_steps]

        for attempt in range(self._max_replans + 1):
            executed: list[dict[str, Any]] = []
            succeeded = failed = 0
            final_output: Any = None

            for step in steps:
                try:
                    output = await self._executor(step)
                    executed.append(
                        {
                            "step_id": step.step_id,
                            "ok": True,
                            "output": output,
                            "error": None,
                        }
                    )
                    succeeded += 1
                    final_output = output
                except Exception as exc:  # noqa: BLE001
                    executed.append(
                        {
                            "step_id": step.step_id,
                            "ok": False,
                            "output": None,
                            "error": str(exc),
                        }
                    )
                    failed += 1
                    _log.warning("Plan step failed: %s — %s", step.step_id, exc)

            result = PlanResult(
                steps_planned=list(steps),
                steps_executed=executed,
                steps_succeeded=succeeded,
                steps_failed=failed,
                final_output=final_output,
                replans=attempt,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )

            if self._verifier is None:
                result.verified = None
                break
            try:
                ok = await self._verifier(result)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Verifier raised: %s — treating as False", exc)
                ok = False
            result.verified = ok
            if ok or attempt >= self._max_replans:
                if not ok:
                    _log.warning(
                        "Plan exhausted replans (max_replans=%d)", self._max_replans
                    )
                break
            # Replan
            replan_prompt = self._build_replan_prompt(prompt, result)
            try:
                steps = await self._planner(replan_prompt)
            except Exception as exc:  # noqa: BLE001
                _log.error("Replan failed: %s — keeping partial result", exc)
                break
            if len(steps) > self._max_steps:
                steps = steps[: self._max_steps]

        assert result is not None  # всегда assigned в loop выше
        result.duration_ms = (time.perf_counter() - started) * 1000.0

        exchange.set_property("plan_result", result)
        exchange.set_property("plan_replans", result.replans)
        exchange.set_property("plan_steps_succeeded", result.steps_succeeded)
        exchange.set_property("plan_steps_failed", result.steps_failed)
        body = (
            result.final_output
            if result.steps_succeeded > 0
            else exchange.in_message.body
        )
        exchange.set_out(body=body, headers=dict(exchange.in_message.headers))

    @staticmethod
    def _build_prompt(exchange: "Exchange[Any]") -> str:
        body = exchange.in_message.body
        if isinstance(body, str):
            return body
        return str(body) if body is not None else ""

    @staticmethod
    def _build_replan_prompt(original: str, result: PlanResult) -> str:
        failed = [s for s in result.steps_executed if not s["ok"]]
        failed_summary = "; ".join(f"{s['step_id']}={s['error']}" for s in failed)
        return (
            f"{original}\n\n"
            f"[Replan attempt {result.replans + 1}] "
            f"Previous attempt failed at: {failed_summary or 'unknown'}. "
            f"Please generate a corrected plan."
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "plan_execute": {
                "max_steps": self._max_steps,
                "max_replans": self._max_replans,
                "has_verifier": self._verifier is not None,
            }
        }


class PlanExecuteMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.plan_execute(...)``.

    Stateless: ``self._add`` через MRO (контракт см. :class:`RouteBuilder`).
    """

    __slots__ = ()

    def plan_execute_with_callbacks(
        self,
        *,
        planner: PlannerFn,
        executor: ExecutorFn,
        verifier: VerifierFn | None = None,
        max_steps: int = 10,
        max_replans: int = 2,
    ) -> "RouteBuilder":
        """Добавить :class:`PlanExecuteProcessor` в pipeline.

        Args:
            planner: ``async (prompt: str) -> list[PlanStep]`` — LLM planner.
            executor: ``async (step: PlanStep) -> Any`` — tool/function exec.
            verifier: Опц. ``async (result: PlanResult) -> bool`` — gate.
            max_steps: Макс. шагов в плане (truncate beyond).
            max_replans: Сколько раз перепланировать при verifier-fail.

        Returns:
            :class:`RouteBuilder` для fluent-chaining.
        """
        return self._add(  # type: ignore[attr-defined]
            PlanExecuteProcessor(
                planner=planner,
                executor=executor,
                verifier=verifier,
                max_steps=max_steps,
                max_replans=max_replans,
            )
        )
