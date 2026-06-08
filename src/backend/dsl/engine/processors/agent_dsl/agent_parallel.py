"""AgentParallelProcessor — параллельный fan-out агентских вызовов (S27 W1).

Запускает N агентов параллельно через :class:`asyncio.TaskGroup`,
собирает результаты в dict под ``result_property`` exchange'а.
Каждый агент работает на cloned :class:`Exchange`, изоляция гарантируется.

YAML контракт::

    steps:
      - agent_parallel:
          agents:
            - { key: scoring,   workflow_id: credit_scoring,   prompt_inline: "..." }
            - { key: antifraud, workflow_id: credit_antifraud, prompt_inline: "..." }
            - { key: kyc,       workflow_id: kyc_verify,       prompt_inline: "..." }
          result_property: parallel_agents
          timeout_s: 30.0
          continue_on_error: true

Python контракт::

    builder.agent_parallel(
        agents=[
            {"key": "scoring", "workflow_id": "credit_scoring", "prompt_inline": "..."},
            ...
        ],
        timeout_s=30.0,
    )

Результат в ``exchange.properties[result_property]`` =
``{"scoring": {...}, "antifraud": {...}, "kyc": {...}}``,
где каждое значение — словарь как у :class:`AgentRunProcessor` (``content``,
``cost_usd`` и т.д.), либо ``{"error": str}`` если агент упал и
``continue_on_error=True``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentParallelProcessor",)

_logger = get_logger(__name__)


class AgentParallelProcessor(BaseAIProcessor):
    """Параллельный fan-out агентов через :class:`asyncio.TaskGroup`.

    Args:
        agents: Список dict-описаний агентов. Каждый dict обязан
            содержать ``key`` (имя в результирующем dict) и параметры
            :class:`AgentRunProcessor` (``workflow_id``, ``prompt_ref`` /
            ``prompt_inline``, опц. ``policy_ref``, ``context_property``).
        result_property: Свойство exchange для итогового dict.
            Default ``"agent_parallel_results"``.
        timeout_s: Опц. timeout на общую группу через
            :func:`asyncio.wait_for`. При срабатывании — все agents
            возвращают ``{"error": "timeout"}``.
        continue_on_error: При ``True`` — упавший агент даёт
            ``{"error": str}`` в результирующем dict, остальные продолжают.
            При ``False`` — exception всплывает и останавливает Exchange.
        name: Имя процессора.
    """

    audit_event: ClassVar[str | None] = "ai.agent.parallel"

    def __init__(
        self,
        *,
        agents: list[dict[str, Any]],
        result_property: str = "agent_parallel_results",
        timeout_s: float | None = None,
        continue_on_error: bool = True,
        name: str | None = None,
    ) -> None:
        if not agents:
            raise ValueError("AgentParallelProcessor: agents не может быть пустым")
        for idx, agent in enumerate(agents):
            if "key" not in agent:
                raise ValueError(f"AgentParallelProcessor: agents[{idx}] без 'key'")
            if "workflow_id" not in agent:
                raise ValueError(
                    f"AgentParallelProcessor: agents[{idx}] без 'workflow_id'"
                )
        super().__init__(name=name or "agent_parallel")
        self.agents = [dict(a) for a in agents]
        self.result_property = result_property
        self.timeout_s = timeout_s
        self.continue_on_error = continue_on_error

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        results: dict[str, Any] = {}

        async def _invoke_one(spec: dict[str, Any]) -> tuple[str, Any]:
            key = spec["key"]
            agent_kwargs = {k: v for k, v in spec.items() if k != "key"}
            try:
                proc = AgentRunProcessor(**agent_kwargs)
            except Exception as exc:
                return key, {"error": f"init failed: {exc}"}

            sub = exchange.clone()
            try:
                await proc.process(sub, context)
            except Exception as exc:
                if not self.continue_on_error:
                    raise
                return key, {"error": str(exc)}
            value = sub.get_property("agent_result")
            if value is None and sub.error:
                value = {"error": sub.error}
            return key, value

        async def _gather() -> None:
            coros = [_invoke_one(spec) for spec in self.agents]
            collected = await asyncio.gather(
                *coros, return_exceptions=self.continue_on_error
            )
            for item in collected:
                if isinstance(item, BaseException):
                    _logger.error("%s: agent gather raised: %s", self.name, item)
                    continue
                key, value = item
                results[key] = value

        try:
            if self.timeout_s is not None:
                await asyncio.wait_for(_gather(), timeout=self.timeout_s)
            else:
                await _gather()
        except TimeoutError:
            _logger.warning(
                "%s: timeout_s=%.2f exceeded — partial results stored",
                self.name,
                self.timeout_s or 0.0,
            )
            for spec in self.agents:
                results.setdefault(spec["key"], {"error": "timeout"})

        exchange.set_property(self.result_property, results)

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"agents": [dict(a) for a in self.agents]}
        if self.result_property != "agent_parallel_results":
            spec["result_property"] = self.result_property
        if self.timeout_s is not None:
            spec["timeout_s"] = self.timeout_s
        if not self.continue_on_error:
            spec["continue_on_error"] = False
        return {"agent_parallel": spec}
