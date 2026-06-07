"""ReflectionLoopProcessor — self-critique + refine agentic pattern (S39 W3).

Generate → Reflect → Refine loop:
1. **Generate** — LLM создаёт начальный draft.
2. **Reflect** — LLM оценивает draft, возвращает ``verdict`` + ``critique``.
3. **Refine** — LLM улучшает draft на основе critique.

Цикл останавливается при ``verdict == stop_verdict`` или после
``max_iterations``.

YAML контракт::

    steps:
      - reflection_loop:
          generator_workflow_id: "generate_draft"
          reflector_workflow_id: "reflect"
          refiner_workflow_id: "refine"
          max_iterations: 3
          stop_verdict: "ok"
          result_property: "reflection_result"

Python контракт через :meth:`AgentDSLMixin.reflection_loop`::

    builder.reflection_loop(
        generator_workflow_id="generate_draft",
        reflector_workflow_id="reflect",
        refiner_workflow_id="refine",
        max_iterations=3,
    )
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import json

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.services.ai.gateway.exceptions import GatewayUnavailable

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("ReflectionLoopProcessor",)

_logger = get_logger(__name__)


class ReflectionLoopProcessor(BaseAIProcessor):
    """Generate → Reflect → Refine с остановкой по stop_verdict.

    Args:
        generator_workflow_id: workflow_id для генерации начального draft.
        reflector_workflow_id: workflow_id для критики draft.
        refiner_workflow_id: workflow_id для улучшения draft (default = generator).
        max_iterations: Максимум итераций reflection + refine.
        stop_verdict: Значение verdict от reflector, при котором цикл останавливается.
        result_property: Свойство, куда сохранить финальный результат.
        history_property: Свойство, куда сохранить историю итераций.
        timeout_s: Таймаут на один LLM-вызов.
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "ai.invoke"
    audit_event: ClassVar[str | None] = "ai.agent.reflection_loop"

    def __init__(
        self,
        *,
        generator_workflow_id: str,
        reflector_workflow_id: str,
        refiner_workflow_id: str | None = None,
        max_iterations: int = 3,
        stop_verdict: str = "ok",
        result_property: str = "reflection_result",
        history_property: str | None = "reflection_history",
        timeout_s: float = 300.0,
        name: str | None = None,
    ) -> None:
        if not generator_workflow_id:
            raise ValueError(
                "ReflectionLoopProcessor: generator_workflow_id обязателен"
            )
        if not reflector_workflow_id:
            raise ValueError(
                "ReflectionLoopProcessor: reflector_workflow_id обязателен"
            )
        super().__init__(name=name or f"reflection_loop:{generator_workflow_id}")
        self.generator_workflow_id = generator_workflow_id
        self.reflector_workflow_id = reflector_workflow_id
        self.refiner_workflow_id = refiner_workflow_id or generator_workflow_id
        self.max_iterations = max_iterations
        self.stop_verdict = stop_verdict
        self.result_property = result_property
        self.history_property = history_property
        self.timeout_s = timeout_s

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        gateway = self._resolve_gateway()
        if gateway is None:
            exchange.set_error(
                f"{self.name}: AIGateway не найден в DI — нельзя выполнить reflection_loop"
            )
            exchange.stop()
            return

        # ── 1. Generate initial draft ──
        draft = await self._generate_draft(gateway, exchange)
        if draft is None:
            exchange.set_error(f"{self.name}: не удалось сгенерировать draft")
            exchange.stop()
            return

        history: list[dict[str, Any]] = [
            {"iteration": 0, "stage": "generate", "draft": draft}
        ]

        current_draft = draft
        final_verdict = ""
        final_critique = ""

        for iteration in range(1, self.max_iterations + 1):
            # ── 2. Reflect ──
            reflection = await self._reflect(
                gateway, exchange, current_draft, iteration
            )
            if reflection is None:
                exchange.set_error(
                    f"{self.name}: reflection failed на итерации {iteration}"
                )
                exchange.stop()
                return

            final_verdict = reflection.get("verdict", "")
            final_critique = reflection.get("critique", "")
            history.append(
                {
                    "iteration": iteration,
                    "stage": "reflect",
                    "verdict": final_verdict,
                    "critique": final_critique,
                }
            )

            if final_verdict.lower() == self.stop_verdict.lower():
                _logger.debug(
                    "%s: stop_verdict reached at iteration %d", self.name, iteration
                )
                break

            if iteration == self.max_iterations:
                # последняя итерация исчерпана без достижения stop_verdict
                break

            # ── 3. Refine ──
            refined = await self._refine(
                gateway, exchange, current_draft, final_critique, iteration
            )
            if refined is None:
                exchange.set_error(
                    f"{self.name}: refine failed на итерации {iteration}"
                )
                exchange.stop()
                return

            current_draft = refined
            history.append(
                {"iteration": iteration, "stage": "refine", "draft": current_draft}
            )
        else:
            _logger.info(
                "%s: max_iterations (%d) reached without stop_verdict",
                self.name,
                self.max_iterations,
            )

        result: dict[str, Any] = {
            "status": "success"
            if final_verdict.lower() == self.stop_verdict.lower()
            else "max_iterations_reached",
            "draft": current_draft,
            "final_verdict": final_verdict,
            "final_critique": final_critique,
            "iterations": len([h for h in history if h.get("stage") == "reflect"]),
        }

        exchange.set_property(self.result_property, result)
        if self.history_property:
            exchange.set_property(self.history_property, history)

    # ── internal helpers ──

    async def _generate_draft(
        self, gateway: Any, exchange: Exchange[Any]
    ) -> str | None:
        """Вызвать generator_workflow_id и вернуть draft-текст."""
        context = self._build_context(exchange)
        response = await self._call_workflow(
            gateway, self.generator_workflow_id, context
        )
        if response is None:
            return None
        return self._extract_text(response)

    async def _reflect(
        self, gateway: Any, exchange: Exchange[Any], draft: str, iteration: int
    ) -> dict[str, Any] | None:
        """Вызвать reflector_workflow_id и вернуть {verdict, critique}."""
        context = {
            **self._build_context(exchange),
            "draft": draft,
            "iteration": iteration,
        }
        response = await self._call_workflow(
            gateway, self.reflector_workflow_id, context
        )
        if response is None:
            return None
        return self._parse_reflection(response)

    async def _refine(
        self,
        gateway: Any,
        exchange: Exchange[Any],
        draft: str,
        critique: str,
        iteration: int,
    ) -> str | None:
        """Вызвать refiner_workflow_id и вернуть улучшенный draft."""
        context = {
            **self._build_context(exchange),
            "draft": draft,
            "critique": critique,
            "iteration": iteration,
        }
        response = await self._call_workflow(gateway, self.refiner_workflow_id, context)
        if response is None:
            return None
        return self._extract_text(response)

    async def _call_workflow(
        self, gateway: Any, workflow_id: str, context: dict[str, Any]
    ) -> Any | None:
        """Один LLM-вызов через AIGateway."""
        from src.backend.core.ai.gateway import AIRequest

        request = AIRequest(
            workflow_id=workflow_id,
            tenant_id="unknown",
            correlation_id="reflection-loop",
            prompt_inline=f"Context: {json.dumps(context, ensure_ascii=False)}",
        )
        try:
            return await gateway.invoke(request)
        except (GatewayUnavailable, OSError, TimeoutError) as exc:
            _logger.warning("%s: gateway.invoke failed: %s", self.name, exc)
            return None
        except Exception as exc:
            _logger.warning(
                "%s: gateway.invoke unexpected error: %s", self.name, exc, exc_info=True
            )
            return None

    @staticmethod
    def _build_context(exchange: Exchange[Any]) -> dict[str, Any]:
        """Сформировать контекст для LLM из exchange."""
        return {
            "body": exchange.in_message.body
            if isinstance(exchange.in_message.body, dict)
            else {},
            "correlation_id": exchange.meta.correlation_id,
        }

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Извлечь текст из AIResponse."""
        structured = getattr(response, "structured", None)
        if isinstance(structured, dict):
            text = structured.get("draft") or structured.get("content") or ""
            if text:
                return str(text)
        content = getattr(response, "content", "")
        return str(content) if content is not None else ""

    @staticmethod
    def _parse_reflection(response: Any) -> dict[str, Any]:
        """Извлечь {verdict, critique} из AIResponse."""
        structured = getattr(response, "structured", None)
        if isinstance(structured, dict):
            return {
                "verdict": str(structured.get("verdict", "")),
                "critique": str(structured.get("critique", "")),
            }
        content = getattr(response, "content", "")
        if content:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return {
                        "verdict": str(parsed.get("verdict", "")),
                        "critique": str(parsed.get("critique", "")),
                    }
            except json.JSONDecodeError:
                _logger.warning(
                    "ReflectionLoopProcessor: reflector returned non-JSON: %r", content
                )
        return {"verdict": "", "critique": ""}

    @staticmethod
    def _resolve_gateway() -> Any | None:
        """Lazy-резолв AIGateway через DI."""
        try:
            from src.backend.services.ai.gateway_adapter import (  # type: ignore[attr-defined]
                get_ai_gateway,
            )

            return get_ai_gateway()
        except Exception:
            try:
                from src.backend.core.di.container import get_container

                container = get_container()
                if container is not None:
                    return container.resolve_optional("ai_gateway")
            except Exception:
                pass
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML DSL."""
        spec: dict[str, Any] = {
            "generator_workflow_id": self.generator_workflow_id,
            "reflector_workflow_id": self.reflector_workflow_id,
        }
        if self.refiner_workflow_id != self.generator_workflow_id:
            spec["refiner_workflow_id"] = self.refiner_workflow_id
        if self.max_iterations != 3:
            spec["max_iterations"] = self.max_iterations
        if self.stop_verdict != "ok":
            spec["stop_verdict"] = self.stop_verdict
        if self.result_property != "reflection_result":
            spec["result_property"] = self.result_property
        if self.history_property != "reflection_history":
            spec["history_property"] = self.history_property
        if self.timeout_s != 300.0:
            spec["timeout_s"] = self.timeout_s
        return {"reflection_loop": spec}
