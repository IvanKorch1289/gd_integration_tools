"""RouterSpecialistProcessor — Router-Specialist agentic pattern (v19 §6.3 #8).

LLM-based intelligent routing запроса к ОДНОМУ specialist agent. Отличается
от :class:`AgentParallelProcessor` (fan-out): LLM-классификатор выбирает
ровно одного best-fit specialist по confidence, с опциональным fallback.

Closes v19 §6.3 gap (pattern #8 of 9 agentic patterns).
Per Beam.ai [^240^] / Tricentis [^241^] pattern #8.

Пример::

    async def llm_router(
        user_input: str, specialists: list[SpecialistAgent]
    ) -> RoutingDecision:
        return RoutingDecision(
            chosen_agent="billing", confidence=0.92, reasoning="...",
        )

    billing = SpecialistAgent(
        name="billing", capability="billing", description="...",
        handler=billing_handler,
    )
    route = (
        RouteBuilder.from_("support.triage", source="internal:support")
        .router_specialist(
            llm_router=llm_router,
            specialists=[billing, support],
            fallback_specialist="support",
            min_confidence=0.6,
        )
        .build()
    )
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "RouterSpecialistMixin",
    "RouterSpecialistProcessor",
    "RoutingDecision",
    "SpecialistAgent",
)

_log = get_logger(__name__)

LLMRouterFn = Callable[[str, list["SpecialistAgent"]], Awaitable["RoutingDecision"]]
SpecialistHandler = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class SpecialistAgent:
    """Описание одного specialist agent для routing.

    Attributes:
        name: Уникальный ID (matching key для
            :attr:`RoutingDecision.chosen_agent`).
        capability: Машинно-читаемая категория (e.g. ``"billing"``).
        description: Human-readable описание для LLM.
        handler: ``async (input: Any) -> Any`` — фактический agent callable.
    """

    name: str
    capability: str
    description: str
    handler: SpecialistHandler

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SpecialistAgent.name должен быть непустым")
        if not callable(self.handler):
            raise TypeError(
                f"SpecialistAgent.handler должен быть callable, "
                f"получено {type(self.handler).__name__}"
            )


@dataclass(slots=True)
class RoutingDecision:
    """Решение LLM-роутера о выборе specialist.

    Attributes:
        chosen_agent: Имя выбранного specialist (должно совпадать с
            :attr:`SpecialistAgent.name`).
        confidence: Уверенность LLM, ``0.0``–``1.0``.
        reasoning: Текстовое объяснение (для observability/audit).
        alternatives: ``[(specialist_name, score), ...]`` для observability.
        fallback_used: ``True`` если выбран fallback (confidence < threshold
            или unknown name). Устанавливается процессором.
    """

    chosen_agent: str
    confidence: float
    reasoning: str = ""
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    fallback_used: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence должен быть в [0.0, 1.0], получено {self.confidence}"
            )


class RouterSpecialistProcessor(BaseProcessor):
    """Router-Specialist agentic processor (v19 §6.3, pattern #8).

    LLM-based intelligent routing: classify input → choose ONE best-fit
    specialist → delegate. При ``confidence < min_confidence`` и наличии
    ``fallback_specialist`` используется fallback.

    Отличия от :class:`AgentParallelProcessor` (fan-out):
        * **ONE** specialist is chosen (not all called in parallel).
        * **LLM-driven** classification (not static branching).
        * **Confidence threshold** + fallback для safety.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        llm_router: LLMRouterFn,
        specialists: list[SpecialistAgent],
        fallback_specialist: str | None = None,
        min_confidence: float = 0.6,
        name: str | None = None,
    ) -> None:
        """Инициализировать Router-Specialist processor.

        Args:
            llm_router: ``async (input, specialists) -> RoutingDecision``.
            specialists: Список :class:`SpecialistAgent` (непустой).
            fallback_specialist: Имя specialist для fallback при низком
                confidence или unknown name. ``None`` = без fallback.
            min_confidence: Минимальный confidence (0.0–1.0).
            name: Опц. имя процессора.

        Raises:
            ValueError: Пустые specialists, некорректный min_confidence,
                или fallback_specialist не найден среди specialists.
            TypeError: ``llm_router`` не callable.
        """
        if not callable(llm_router):
            raise TypeError("llm_router должен быть callable")
        if not specialists:
            raise ValueError("specialists должен быть непустым списком")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError(
                f"min_confidence должен быть в [0.0, 1.0], получено {min_confidence}"
            )
        names = {s.name for s in specialists}
        if fallback_specialist is not None and fallback_specialist not in names:
            raise ValueError(
                f"fallback_specialist={fallback_specialist!r} не найден "
                f"среди specialists с именами {sorted(names)}"
            )

        super().__init__(name=name or "router_specialist")
        self._llm_router = llm_router
        self._specialists: list[SpecialistAgent] = list(specialists)
        self._specialists_by_name: dict[str, SpecialistAgent] = {
            s.name: s for s in self._specialists
        }
        self._fallback_specialist = fallback_specialist
        self._min_confidence = min_confidence

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Запустить LLM-routing → specialist delegation.

        Flow:
            1. Read input из ``exchange.in_message.body``.
            2. Call ``llm_router(input, specialists)`` → decision.
            3. Если ``confidence < min_confidence`` И есть fallback →
               подменить chosen_agent (mark ``fallback_used=True``).
            4. Найти specialist по chosen_agent (или fallback при отсутствии).
            5. Call ``specialist.handler(input)`` → output.
            6. ``exchange.out_message.body = output``.
            7. Save ``RoutingDecision`` в properties.
        """
        started = time.perf_counter()
        raw_input = self._extract_input(exchange)
        try:
            decision = await self._llm_router(raw_input, self._specialists)
        except Exception as exc:  # noqa: BLE001
            _log.error("LLM router failed: %s", exc)
            exchange.fail(f"router_specialist: LLM router failed: {exc}")
            return

        # 3. Confidence threshold → fallback
        if (
            decision.confidence < self._min_confidence
            and self._fallback_specialist is not None
        ):
            _log.debug(
                "Confidence %.2f < threshold %.2f, fallback=%r",
                decision.confidence,
                self._min_confidence,
                self._fallback_specialist,
            )
            decision = RoutingDecision(
                chosen_agent=self._fallback_specialist,
                confidence=decision.confidence,
                reasoning=(
                    f"[fallback] {decision.reasoning}"
                    if decision.reasoning
                    else "[fallback] low confidence"
                ),
                alternatives=list(decision.alternatives),
                fallback_used=True,
            )
        elif decision.confidence < self._min_confidence:
            _log.debug(
                "Confidence %.2f < threshold %.2f, no fallback",
                decision.confidence,
                self._min_confidence,
            )

        # 4. Resolve specialist (with unknown-name fallback)
        specialist = self._specialists_by_name.get(decision.chosen_agent)
        if specialist is None:
            if self._fallback_specialist is not None:
                _log.warning(
                    "Unknown specialist %r, falling back to %r",
                    decision.chosen_agent,
                    self._fallback_specialist,
                )
                specialist = self._specialists_by_name[self._fallback_specialist]
                decision = RoutingDecision(
                    chosen_agent=specialist.name,
                    confidence=decision.confidence,
                    reasoning=(
                        f"[fallback:unknown] {decision.reasoning}"
                        if decision.reasoning
                        else "[fallback:unknown] specialist not found"
                    ),
                    alternatives=list(decision.alternatives),
                    fallback_used=True,
                )
            else:
                exchange.fail(
                    f"router_specialist: unknown specialist "
                    f"{decision.chosen_agent!r} and no fallback configured"
                )
                return

        # 5. Delegate to specialist
        try:
            output = await specialist.handler(raw_input)
        except Exception as exc:  # noqa: BLE001
            _log.error("Specialist %r failed: %s", specialist.name, exc)
            exchange.fail(
                f"router_specialist: specialist {specialist.name!r} failed: {exc}"
            )
            return

        # 6-7. Persist results
        duration_ms = (time.perf_counter() - started) * 1000.0
        exchange.set_property("routing_decision", decision)
        exchange.set_property("routing_chosen_agent", specialist.name)
        exchange.set_property("routing_confidence", decision.confidence)
        exchange.set_property("routing_fallback_used", decision.fallback_used)
        exchange.set_property("routing_duration_ms", duration_ms)
        exchange.set_property("routing_specialist_capability", specialist.capability)
        exchange.set_out(body=output, headers=dict(exchange.in_message.headers))

    @staticmethod
    def _extract_input(exchange: "Exchange[Any]") -> str:
        body = exchange.in_message.body
        if isinstance(body, str):
            return body
        return str(body) if body is not None else ""

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "router_specialist": {
                "min_confidence": self._min_confidence,
                "fallback_specialist": self._fallback_specialist,
                "specialists": [
                    {
                        "name": s.name,
                        "capability": s.capability,
                        "description": s.description,
                    }
                    for s in self._specialists
                ],
            }
        }


class RouterSpecialistMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.router_specialist(...)``.

    Stateless: ``self._add`` через MRO (контракт см. :class:`RouteBuilder`).
    """

    __slots__ = ()

    def router_specialist(
        self,
        *,
        llm_router: LLMRouterFn,
        specialists: list[SpecialistAgent],
        fallback_specialist: str | None = None,
        min_confidence: float = 0.6,
    ) -> "RouteBuilder":
        """Добавить :class:`RouterSpecialistProcessor` в pipeline.

        Args:
            llm_router: ``async (input, specialists) -> RoutingDecision``.
            specialists: Список :class:`SpecialistAgent` (непустой).
            fallback_specialist: Имя specialist для fallback.
            min_confidence: Confidence threshold (0.0–1.0). Default ``0.6``.

        Returns:
            :class:`RouteBuilder` для fluent-chaining.
        """
        return self._add(  # type: ignore[attr-defined]
            RouterSpecialistProcessor(
                llm_router=llm_router,
                specialists=specialists,
                fallback_specialist=fallback_specialist,
                min_confidence=min_confidence,
            )
        )
