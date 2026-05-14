"""Workflow gateways — XOR / AND / OR ветвление поверх Temporal.

PLAN V17 [wave:s3/workflow-gateways], K3 W4.

Модуль предоставляет три типа gateway-элементов из нотации BPMN 2.0,
транслируемых в декларативные примитивы Temporal-workflow:

    * XOR (exclusive gateway) — выбирает первую ветку с условием ``True``.
    * AND (parallel gateway) — запускает все ветки параллельно, ждёт все.
    * OR (inclusive gateway) — запускает все активные ветки, ждёт первую.

Принципы:
    * Все данные — ``dataclass``, без сложной логики в полях.
    * :class:`GatewayCompiler` — чистый класс без состояния (stateless).
    * Компиляция возвращает ``dict``, пригодный для сериализации и
      последующего прохода компилятора (emitter.py / step_compilers.py).
    * Модуль НЕ импортирует ``temporalio`` напрямую — всё через примитивы.

Пример::

    from src.backend.dsl.workflow.gateways import (
        BranchSpec,
        GatewaySpec,
        process_gateway,
    )

    spec = GatewaySpec(
        kind="xor",
        branches=[
            BranchSpec(name="high", condition="score > 0.8", steps=[...]),
            BranchSpec(name="low", condition=None, steps=[...]),  # default
        ],
    )
    result = process_gateway(spec)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = (
    "BranchSpec",
    "GatewayCompiler",
    "GatewaySpec",
    "process_gateway",
)


@dataclass(slots=True, frozen=True)
class BranchSpec:
    """Спецификация одной ветки gateway.

    Args:
        name: Уникальное имя ветки в рамках gateway.
        condition: Строковое выражение-предикат (JMESPath или Python-expr).
            ``None`` означает «default» — ветка без условия (только для XOR).
        steps: Список шагов, выполняемых при активации ветки.
            Каждый шаг — произвольный dict (activity, saga и др.).
    """

    name: str
    condition: str | None
    steps: list[Any] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class GatewaySpec:
    """Спецификация gateway-узла workflow.

    Args:
        kind: Тип gateway: ``"xor"`` | ``"and"`` | ``"or"``.
        branches: Список веток для данного gateway.
    """

    kind: Literal["xor", "and", "or"]
    branches: list[BranchSpec]


class GatewayCompiler:
    """Компилятор gateway-спецификаций в Temporal-примитивы.

    Возвращает ``dict`` — промежуточное IR-представление, которое
    подхватывает компилятор :mod:`dsl.workflow.compiler.step_compilers`.

    Класс не хранит состояния; все методы статические.
    """

    @staticmethod
    def compile_xor(spec: GatewaySpec, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        """Скомпилировать XOR (exclusive) gateway.

        Семантика: из списка веток выбирается первая, чьё ``condition``
        вычисляется в ``True``; ветка с ``condition=None`` — fallback.
        В Temporal реализуется через conditional-activity-dispatch.

        Args:
            spec: Спецификация XOR-gateway.
            ctx: Опциональный контекст компиляции (переменные роута).

        Returns:
            IR-dict с ключами ``type``, ``strategy``, ``branches``.
        """
        return {
            "type": "gateway",
            "strategy": "exclusive",
            "branches": [
                {
                    "name": branch.name,
                    "condition": branch.condition,
                    "steps": branch.steps,
                }
                for branch in spec.branches
            ],
            "ctx": ctx or {},
        }

    @staticmethod
    def compile_and(spec: GatewaySpec, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        """Скомпилировать AND (parallel) gateway.

        Семантика: все ветки запускаются параллельно через
        ``asyncio.gather`` / ``workflow.execute_activity`` fan-out;
        завершение — когда **все** ветки завершены (join-all).

        Args:
            spec: Спецификация AND-gateway.
            ctx: Опциональный контекст компиляции.

        Returns:
            IR-dict с ключами ``type``, ``strategy``, ``join``, ``branches``.
        """
        return {
            "type": "gateway",
            "strategy": "parallel",
            "join": "wait_all",
            "branches": [
                {
                    "name": branch.name,
                    "condition": branch.condition,
                    "steps": branch.steps,
                }
                for branch in spec.branches
            ],
            "ctx": ctx or {},
        }

    @staticmethod
    def compile_or(spec: GatewaySpec, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        """Скомпилировать OR (inclusive) gateway.

        Семантика: из всех веток активируются те, чьё ``condition`` истинно;
        завершение — когда завершена **первая** активная ветка (wait_any).
        Остальные ветки отменяются (cancel-on-first-complete).

        Args:
            spec: Спецификация OR-gateway.
            ctx: Опциональный контекст компиляции.

        Returns:
            IR-dict с ключами ``type``, ``strategy``, ``join``, ``branches``.
        """
        return {
            "type": "gateway",
            "strategy": "inclusive",
            "join": "wait_any",
            "branches": [
                {
                    "name": branch.name,
                    "condition": branch.condition,
                    "steps": branch.steps,
                }
                for branch in spec.branches
            ],
            "ctx": ctx or {},
        }


def process_gateway(spec: GatewaySpec, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Диспетчер компиляции gateway по типу (``kind``).

    Делегирует вызов к соответствующему методу :class:`GatewayCompiler`
    в зависимости от значения ``spec.kind``.

    Args:
        spec: Спецификация gateway.
        ctx: Опциональный контекст компиляции.

    Returns:
        IR-dict, готовый для прохода эмиттера.

    Raises:
        ValueError: Если ``spec.kind`` неизвестен (защита от будущих расширений).
    """
    match spec.kind:
        case "xor":
            return GatewayCompiler.compile_xor(spec, ctx)
        case "and":
            return GatewayCompiler.compile_and(spec, ctx)
        case "or":
            return GatewayCompiler.compile_or(spec, ctx)
        case _:
            raise ValueError(f"Неизвестный тип gateway: {spec.kind!r}")
