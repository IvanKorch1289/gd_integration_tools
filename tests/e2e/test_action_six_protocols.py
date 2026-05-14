"""E2E-тест: один pilot action auto-регистрируется в 6 протоколах.

Wave ``[wave:s6/k3-e2e-six-protocols]``.

Цель: проверить, что один action (``credit.score.calculate``),
зарегистрированный через ``ActionHandlerRegistry`` (что соответствует
семантике ``@service_dsl(protocols=["all"])``), доступен через **6
транспортов** и каждый возвращает **идентичный** response.

Транспорты:

* REST   — :func:`src.backend.entrypoints.base.dispatch_action`
  (источник для REST endpoints)
* gRPC   — тот же ``dispatch_action`` (см. ``grpc/auto_servicer.py``)
* GraphQL — тот же ``dispatch_action`` (см. ``graphql/schema._dispatch_action``)
* SOAP   — тот же ``dispatch_action`` (см. ``soap/soap_handler._dispatch_via_action``)
* MCP    — ``action_handler_registry.dispatch(command)``
  (см. ``mcp/mcp_server.py``)
* MQTT   — ``action_handler_registry.dispatch(command)``
  (см. ``mqtt/mqtt_handler._handle_message``)

Тест не поднимает реальных серверов (gRPC/MQTT/MCP). Он проверяет
**dispatch-семантику** — все транспорты делегируют через единый реестр
``ActionHandlerRegistry``, поэтому достаточно вызвать соответствующие
helpers / эмулировать их dispatch-цепочку и сравнить результаты.

Архитектурное основание: см. ``entrypoints/base.py``::``dispatch_action``
и ``commands/action_registry.py``::``ActionHandlerRegistry.dispatch``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
    action_handler_registry,
)
from src.backend.schemas.invocation import ActionCommandSchema

# ─────────────────────────── pilot action ───────────────────────────

PILOT_ACTION = "credit.score.calculate"


class _PilotCreditScoreService:
    """Минимальный сервис для pilot action.

    Имитирует расчёт credit score: принимает applicant и возвращает
    структурированный response. Чисто-функциональный (без БД / сети),
    чтобы тест был детерминированным.
    """

    async def calculate(self, applicant_id: int, income: int) -> dict[str, Any]:
        """Возвращает фиксированный результат расчёта.

        Используем простую формулу score = min(900, 300 + income // 1000).
        """
        score = min(900, 300 + income // 1000)
        return {
            "applicant_id": applicant_id,
            "score": score,
            "decision": "APPROVE" if score >= 600 else "REJECT",
        }


_PILOT_SERVICE_INSTANCE = _PilotCreditScoreService()


def _get_pilot_service() -> _PilotCreditScoreService:
    return _PILOT_SERVICE_INSTANCE


# ─────────────────────────── fixtures ───────────────────────────


@pytest.fixture
def register_pilot_action():
    """Регистрирует pilot-action до теста, удаляет после.

    Использует глобальный ``action_handler_registry``, чтобы протоколы
    нашли action. После теста запись удаляется во избежание утечек.
    """
    spec = ActionHandlerSpec(
        action=PILOT_ACTION,
        service_getter=_get_pilot_service,
        service_method="calculate",
    )
    action_handler_registry.register_many([spec])
    yield
    action_handler_registry._handlers.pop(PILOT_ACTION, None)
    action_handler_registry._metadata.pop(PILOT_ACTION, None)


# ─────────────────────────── per-protocol dispatchers ───────────────────────────


async def _via_rest(payload: dict[str, Any]) -> Any:
    """REST использует ``entrypoints.base.dispatch_action``."""
    from src.backend.entrypoints.base import dispatch_action

    return await dispatch_action(action=PILOT_ACTION, payload=payload, source="rest")


async def _via_grpc(payload: dict[str, Any]) -> Any:
    """gRPC использует ``entrypoints.base.dispatch_action`` (через AutoServicer)."""
    from src.backend.entrypoints.base import dispatch_action

    return await dispatch_action(action=PILOT_ACTION, payload=payload, source="grpc")


async def _via_graphql(payload: dict[str, Any]) -> Any:
    """GraphQL вызывает ``dispatch_action`` (см. graphql/schema._dispatch_action)."""
    from src.backend.entrypoints.base import dispatch_action

    return await dispatch_action(action=PILOT_ACTION, payload=payload, source="graphql")


async def _via_soap(payload: dict[str, Any]) -> Any:
    """SOAP делегирует через ``dispatch_action`` (см. ``soap_handler._dispatch_via_action``).

    ``soap_handler._dispatch_via_action`` — однострочный helper, который
    вызывает ``dispatch_action(action=operation, payload=payload,
    source="soap")``. Импортируется inline, чтобы избежать побочных
    импортов из ``soap_handler.py`` (зависимости от FastAPI router и т.п.).
    Контракт выполнения идентичен оригинальной реализации.
    """
    from src.backend.entrypoints.base import dispatch_action

    return await dispatch_action(action=PILOT_ACTION, payload=payload, source="soap")


async def _via_mcp(payload: dict[str, Any]) -> Any:
    """MCP-сервер использует ``action_handler_registry.dispatch`` напрямую.

    См. ``entrypoints/mcp/mcp_server.py:157``.
    """
    command = ActionCommandSchema(action=PILOT_ACTION, payload=payload)
    return await action_handler_registry.dispatch(command)


async def _via_mqtt(payload: dict[str, Any]) -> Any:
    """MQTT handler собирает ``ActionCommandSchema`` и dispatch'ит.

    См. ``entrypoints/mqtt/mqtt_handler._handle_message:185-188``.
    """
    command = ActionCommandSchema(
        action=PILOT_ACTION,
        payload=payload,
        meta={"source": "mqtt", "topic": "gd/credit/score/calculate"},
    )
    return await action_handler_registry.dispatch(command)


# ─────────────────────────── e2e ───────────────────────────


@pytest.mark.asyncio
async def test_six_protocols_return_identical_response(register_pilot_action):
    """Один action в 6 протоколах возвращает идентичный response.

    Покрывает реализацию V15 R-V15-3: auto-registration во всех протоколах.
    Pilot action — ``credit.score.calculate`` — зарегистрирован в едином
    реестре и доступен через REST / gRPC / GraphQL / SOAP / MCP / MQTT.
    """
    payload = {"applicant_id": 42, "income": 250_000}
    expected = {"applicant_id": 42, "score": 550, "decision": "REJECT"}

    rest_result = await _via_rest(payload)
    grpc_result = await _via_grpc(payload)
    graphql_result = await _via_graphql(payload)
    soap_result = await _via_soap(payload)
    mcp_result = await _via_mcp(payload)
    mqtt_result = await _via_mqtt(payload)

    # Все 6 транспортов вернули тот же payload.
    assert rest_result == expected
    assert grpc_result == expected
    assert graphql_result == expected
    assert soap_result == expected
    assert mcp_result == expected
    assert mqtt_result == expected

    # Парная проверка идентичности — все 6 ответов равны между собой.
    responses = (
        rest_result,
        grpc_result,
        graphql_result,
        soap_result,
        mcp_result,
        mqtt_result,
    )
    for r in responses[1:]:
        assert r == responses[0]


@pytest.mark.asyncio
async def test_six_protocols_approve_branch(register_pilot_action):
    """Положительная ветка (decision=APPROVE) консистентна между протоколами.

    Покрывает branching по бизнес-логике — все транспорты получают
    одинаковую decision-семантику.
    """
    payload = {"applicant_id": 7, "income": 350_000}
    expected = {"applicant_id": 7, "score": 650, "decision": "APPROVE"}

    rest = await _via_rest(payload)
    grpc = await _via_grpc(payload)
    graphql = await _via_graphql(payload)
    soap = await _via_soap(payload)
    mcp = await _via_mcp(payload)
    mqtt = await _via_mqtt(payload)

    for resp in (rest, grpc, graphql, soap, mcp, mqtt):
        assert resp == expected


@pytest.mark.asyncio
async def test_action_metadata_registered_for_all_transports(register_pilot_action):
    """После регистрации pilot-action попадает в metadata реестра.

    Проверяет parallel-storage метаданных (Wave 14.1.B). MCP/Gateway-слой
    использует ``list_metadata()`` для discover'а tools — должен видеть
    pilot action.
    """
    metadata = action_handler_registry.get_metadata(PILOT_ACTION)
    assert metadata is not None
    assert metadata.action == PILOT_ACTION


@pytest.mark.asyncio
async def test_unregistered_action_raises_keyerror():
    """Незарегистрированный action → KeyError из реестра.

    Гарантирует, что транспорты получают одинаковую ошибку — это база
    для consistent error-envelope (см. ADR-038 Phase D).
    """
    registry = ActionHandlerRegistry()
    command = ActionCommandSchema(action="missing.action", payload={})
    with pytest.raises(KeyError):
        await registry.dispatch(command)
