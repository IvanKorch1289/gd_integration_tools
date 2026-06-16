"""S55 W2 — choice.py part of control_flow decomp.

Classes: ChoiceBranch, ChoiceProcessor.
Funcs: _normalize_choice_branches.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, run_sub_processors
from src.backend.dsl.engine.processors.control_flow.saga import _serialize_sub

_cf_logger = get_logger("dsl.control_flow")


@dataclass
class ChoiceBranch:
    """Одна ветка ``ChoiceProcessor`` с предикатом или JMESPath-выражением.

    Атрибуты:
        processors: Sub-pipeline ветки (выполняется при истинном условии).
        predicate: Legacy-форма — Python-callable над ``Exchange``.
            Не сериализуется в YAML; используется для in-process тестов.
        expr: JMESPath-выражение поверх ``ex.in_message.body``.
            Сериализуется в YAML и поддерживает write-back round-trip.

    Должна быть указана **ровно одна** из ``predicate``/``expr``.
    """

    processors: list[BaseProcessor]
    predicate: Callable[[Exchange[Any]], bool] | None = None
    expr: str | None = None

    def __post_init__(self) -> None:
        if (self.predicate is None) == (self.expr is None):
            raise ValueError("ChoiceBranch требует ровно одно из 'predicate' / 'expr'")

    def matches(self, exchange: Exchange[Any]) -> bool:
        """Проверяет условие ветки против текущего ``Exchange``."""
        if self.predicate is not None:
            return bool(self.predicate(exchange))
        import jmespath

        return bool(jmespath.search(self.expr, exchange.in_message.body))


class ChoiceProcessor(BaseProcessor):
    """Условное ветвление When/Otherwise.

    Поддерживает две формы веток:
    1. :class:`ChoiceBranch` с ``expr`` (JMESPath) — сериализуется в YAML.
    2. Legacy-tuple ``(predicate, processors)`` — для in-process Python-кода;
       такие ветки не сериализуются и приводят ``to_spec`` к ``None``.

    Пример (новая форма)::

        ChoiceProcessor(
            when=[
                ChoiceBranch(
                    expr="status == 'ok'",
                    processors=[DispatchActionProcessor("orders.update")],
                ),
            ],
            otherwise=[LogProcessor(level="warning")],
        )
    """

    def __init__(
        self,
        when: list[ChoiceBranch]
        | list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "choice")
        self._branches: list[ChoiceBranch] = _normalize_choice_branches(when)
        self._otherwise = otherwise or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        for branch in self._branches:
            if branch.matches(exchange):
                await run_sub_processors(branch.processors, exchange, context)
                return

        await run_sub_processors(self._otherwise, exchange, context)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует Choice в YAML-spec при наличии JMESPath-веток.

        Если хотя бы одна ветка использует callable-predicate (legacy),
        возвращается ``None`` — write-back для такого Choice невозможен.
        """
        when_specs: list[dict[str, Any]] = []
        for branch in self._branches:
            if branch.expr is None:
                return None
            sub = _serialize_sub(branch.processors)
            if sub is None:
                return None
            when_specs.append({"expr": branch.expr, "processors": sub})

        result: dict[str, Any] = {"when": when_specs}
        if self._otherwise:
            otherwise_sub = _serialize_sub(self._otherwise)
            if otherwise_sub is None:
                return None
            result["otherwise"] = otherwise_sub
        return {"choice": result}


def _normalize_choice_branches(
    when: list[ChoiceBranch]
    | list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
) -> list[ChoiceBranch]:
    """Приводит legacy-формат веток к списку :class:`ChoiceBranch`."""
    branches: list[ChoiceBranch] = []
    for item in when:
        if isinstance(item, ChoiceBranch):
            branches.append(item)
        elif isinstance(item, tuple) and len(item) == 2:
            predicate, processors = item
            branches.append(
                ChoiceBranch(processors=list(processors), predicate=predicate)
            )
        else:
            raise ValueError(f"Invalid choice-branch spec: {item!r}")
    return branches
