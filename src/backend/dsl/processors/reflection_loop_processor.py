"""ReflectionLoopProcessor — Reflection Loop agentic pattern (v17 §2.1, #4 of 9).

Generate → critique → refine loop. Closes 30% partial gap (AgentBranchProcessor
verdict branch) → full coverage. Per Beam.ai [^240^] / Tricentis [^241^].
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

__all__ = ("ReflectionLoopMixin", "ReflectionLoopProcessor", "ReflectionResult")

_log = get_logger(__name__)

GeneratorFn = Callable[[str], Awaitable[Any]]
CriticFn = Callable[[Any], Awaitable[tuple[str, float]]]


@dataclass(slots=True)
class ReflectionResult:
    """Результат reflection-loop с историей refinements.

    Attributes:
        final_output: Финальный (лучший) output от generator.
        initial_output: Первый output (до refinements).
        critique: Critique последней итерации.
        score: Score последней итерации (0.0–1.0).
        refinements: ``[{"iteration", "output", "critique", "score"}]`` —
            по записи на каждый critic-вызов.
        iterations: Сколько critic-вызовов было сделано.
        duration_ms: Длительность всего цикла.
    """

    final_output: Any
    initial_output: Any
    critique: str = ""
    score: float = 0.0
    refinements: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    duration_ms: float = 0.0


class ReflectionLoopProcessor(BaseProcessor):
    """Reflection Loop agentic processor (v17 §2.1, pattern #4).

    LLM/функция генерирует output → critic оценивает (0–1) → если score
    < ``score_threshold``, generator вызывается снова с prompt+critique.
    До ``max_refinements`` refinements, дальше — лучший достигнутый.
    Per Beam.ai [^240^]: foundational self-improvement pattern.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        generator: GeneratorFn,
        critic: CriticFn,
        max_refinements: int = 3,
        score_threshold: float = 0.8,
        name: str | None = None,
    ) -> None:
        if not callable(generator):
            raise TypeError("generator должен быть callable")
        if not callable(critic):
            raise TypeError("critic должен быть callable")
        if max_refinements < 0:
            raise ValueError(
                f"max_refinements должен быть >= 0, получено {max_refinements}"
            )
        if not 0.0 <= score_threshold <= 1.0:
            raise ValueError(
                f"score_threshold должен быть в [0.0, 1.0], получено {score_threshold}"
            )
        super().__init__(name=name or "reflection_loop")
        self._generator = generator
        self._critic = critic
        self._max_refinements = max_refinements
        self._score_threshold = score_threshold

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Generate → critique → refine (max_refinements раз)."""
        prompt = self._build_prompt(exchange)
        started = time.perf_counter()
        refinements: list[dict[str, Any]] = []

        # 1. Initial generation
        try:
            current_output = await self._generator(prompt)
        except Exception as exc:  # noqa: BLE001
            _log.error("Generator failed on initial call: %s", exc)
            exchange.fail(f"reflection_loop: generator failed: {exc}")
            return

        # 2. Critique + refine loop
        last_critique = ""
        last_score = 0.0
        for i in range(self._max_refinements + 1):
            try:
                last_critique, last_score = await self._critic(current_output)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "Critic raised on iteration %d: %s — keeping prior output", i, exc
                )
                refinements.append(
                    {
                        "iteration": i,
                        "output": current_output,
                        "critique": f"[critic error: {exc}]",
                        "score": 0.0,
                    }
                )
                break

            refinements.append(
                {
                    "iteration": i,
                    "output": current_output,
                    "critique": last_critique,
                    "score": last_score,
                }
            )

            if last_score >= self._score_threshold:
                break  # accepted
            if i >= self._max_refinements:
                _log.warning(
                    "Reflection loop exhausted budget: max_refinements=%d, "
                    "final score=%.2f",
                    self._max_refinements,
                    last_score,
                )
                break

            # 3. Refine
            refine_prompt = (
                f"{prompt}\n\n"
                f"[Refine attempt {i + 1}] "
                f"Critique: {last_critique} (score={last_score:.2f}). "
                f"Please improve the response."
            )
            try:
                current_output = await self._generator(refine_prompt)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Generator failed on refine %d: %s", i + 1, exc)
                break  # keep prior output

        result = ReflectionResult(
            final_output=current_output,
            initial_output=refinements[0]["output"] if refinements else current_output,
            critique=last_critique,
            score=last_score,
            refinements=refinements,
            iterations=len(refinements),
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

        exchange.set_property("reflection_result", result)
        exchange.set_property("reflection_iterations", result.iterations)
        exchange.set_property("reflection_final_score", result.score)
        exchange.set_out(
            body=result.final_output, headers=dict(exchange.in_message.headers)
        )

    @staticmethod
    def _build_prompt(exchange: "Exchange[Any]") -> str:
        body = exchange.in_message.body
        if isinstance(body, str):
            return body
        return str(body) if body is not None else ""

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "reflection_loop": {
                "max_refinements": self._max_refinements,
                "score_threshold": self._score_threshold,
            }
        }


class ReflectionLoopMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.reflection_loop(...)``.

    Stateless: ``self._add`` через MRO (контракт см. :class:`RouteBuilder`).
    """

    __slots__ = ()

    def reflection_loop(
        self,
        *,
        generator: GeneratorFn,
        critic: CriticFn,
        max_refinements: int = 3,
        score_threshold: float = 0.8,
    ) -> "RouteBuilder":
        """Добавить :class:`ReflectionLoopProcessor` в pipeline.

        Args:
            generator: ``async (prompt: str) -> Any`` — LLM/функция-генератор.
            critic: ``async (output: Any) -> tuple[str, float]`` —
                возвращает ``(critique, score 0–1)``.
            max_refinements: Сколько refine-итераций (``0`` = только initial).
            score_threshold: При ``score >=`` output принимается сразу.

        Returns:
            :class:`RouteBuilder` для fluent-chaining.
        """
        return self._add(  # type: ignore[attr-defined]
            ReflectionLoopProcessor(
                generator=generator,
                critic=critic,
                max_refinements=max_refinements,
                score_threshold=score_threshold,
            )
        )
