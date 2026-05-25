"""AgentBranchProcessor — verdict-based routing для агентов (S27 W1).

Условная развилка по результату :class:`AgentRunProcessor`. Получает
verdict из exchange.properties и выполняет соответствующую ветку процессоров.

YAML контракт::

    steps:
      - agent_branch:
          source_property: agent_result.content
          branches:
            approve:
              - dispatch_action: { name: credit.create_offer }
            reject:
              - dispatch_action: { name: credit.send_rejection }
          default:
            - dispatch_action: { name: credit.review_manual }

Python контракт через :meth:`AgentDSLMixin.agent_branch`::

    builder.agent_branch(
        source_property="agent_result.structured.verdict",
        branches={
            "approve": [DispatchActionProcessor("credit.create_offer")],
            "reject": [DispatchActionProcessor("credit.send_rejection")],
        },
        default=[DispatchActionProcessor("credit.review_manual")],
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.dsl.engine.processors.base import BaseProcessor, run_sub_processors

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentBranchProcessor",)

_logger = logging.getLogger(__name__)


class AgentBranchProcessor(BaseAIProcessor):
    """Условная развилка по verdict из agent_result.

    Args:
        source_property: Путь к значению-verdict в exchange.
            Поддерживает dot-path: ``"agent_result.content"`` →
            ``properties["agent_result"]["content"]``;
            ``"agent_result.structured.verdict"`` →
            ``properties["agent_result"]["structured"]["verdict"]``.
        branches: Mapping ``verdict_value`` → ``list[BaseProcessor]``.
            Сравнение exact-match (case-sensitive). Для case-insensitive
            preprocessing передавайте уже нормализованные значения.
        default: Опц. ветка fallback при отсутствии verdict в ``branches``.
            При ``None`` — silent skip (логируется warning).
        name: Имя процессора.
    """

    audit_event: ClassVar[str | None] = "ai.agent.branch"
    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        *,
        source_property: str,
        branches: dict[str, list[BaseProcessor]],
        default: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        if not source_property:
            raise ValueError(
                "AgentBranchProcessor: source_property обязателен"
            )
        if not branches and default is None:
            raise ValueError(
                "AgentBranchProcessor: требуется branches или default"
            )
        super().__init__(name=name or f"agent_branch:{source_property}")
        self.source_property = source_property
        self.branches = {k: list(v) for k, v in branches.items()}
        self.default = list(default) if default else None

    async def _run(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        verdict = self._extract_verdict(exchange)
        verdict_str = "" if verdict is None else str(verdict)

        target = self.branches.get(verdict_str)
        if target is None:
            target = self.default
            exchange.set_property(
                "agent_branch_taken",
                "default" if target is not None else "skip",
            )
            if target is None:
                _logger.warning(
                    "%s: verdict=%r не найден в branches и default=None — skip",
                    self.name,
                    verdict_str,
                )
                return
        else:
            exchange.set_property("agent_branch_taken", verdict_str)

        await run_sub_processors(target, exchange, context)

    def _extract_verdict(self, exchange: "Exchange[Any]") -> Any:
        """Достать verdict по dot-path из exchange.properties.

        Поддерживает ``properties["a"]["b"]["c"]`` через
        ``"a.b.c"``.
        """
        parts = self.source_property.split(".")
        cursor: Any = exchange.get_property(parts[0])
        for part in parts[1:]:
            if cursor is None:
                return None
            if isinstance(cursor, dict):
                cursor = cursor.get(part)
            else:
                cursor = getattr(cursor, part, None)
        return cursor

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML.

        Вложенные processors сериализуются через ``to_spec()``, что
        даёт корректный round-trip только если все процессоры в ветках
        поддерживают сериализацию.
        """
        spec: dict[str, Any] = {"source_property": self.source_property}
        branches_spec: dict[str, list[dict[str, Any]]] = {}
        for verdict, processors in self.branches.items():
            branches_spec[verdict] = [
                p.to_spec() or {} for p in processors
            ]
        spec["branches"] = branches_spec
        if self.default is not None:
            spec["default"] = [p.to_spec() or {} for p in self.default]
        return {"agent_branch": spec}
