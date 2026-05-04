"""Wave 1.5 — единый мост entrypoint → ActionDispatcher (с DSL-fallback Tier 3).

Назначение: WS / SSE / Webhook / Express теперь сначала пытаются вызвать
зарегистрированный action через :class:`ActionGatewayDispatcher`
(middleware-цепочка + унифицированный envelope), а при отсутствии action
в реестре или при выключенном feature-flag откатываются на исторический
DSL-маршрут (``DslService.dispatch(route_id=...)``).

Семантика точно соответствует ADR-038 Phase D:

* feature-flag ENV per-transport (``USE_ACTION_DISPATCHER_FOR_WS``,
  ``USE_ACTION_DISPATCHER_FOR_WEBHOOK``, ``USE_ACTION_DISPATCHER_FOR_EXPRESS``,
  ``USE_ACTION_DISPATCHER_FOR_SSE``) — все ``false`` по умолчанию;
* DSL-fallback всегда сохраняется как Tier 3 — постепенная миграция;
* action не зарегистрирован в ``action_handler_registry`` → DSL без падения.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = ("BridgeResult", "dispatch_action_or_dsl", "is_dispatcher_enabled_for")


_TRANSPORT_FLAG_ENV: dict[str, str] = {
    "ws": "USE_ACTION_DISPATCHER_FOR_WS",
    "webhook": "USE_ACTION_DISPATCHER_FOR_WEBHOOK",
    "express": "USE_ACTION_DISPATCHER_FOR_EXPRESS",
    "sse": "USE_ACTION_DISPATCHER_FOR_SSE",
}

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def is_dispatcher_enabled_for(transport: str) -> bool:
    """Проверяет, включён ли ActionDispatcher для конкретного транспорта.

    Чтение env'а на каждый запрос — допустимо: оверхед минимальный,
    зато можно горячо переключать без рестарта при отладке (та же
    семантика, что у :func:`_http_dispatcher_enabled`).
    """
    env_name = _TRANSPORT_FLAG_ENV.get(transport)
    if env_name is None:
        return False
    return os.getenv(env_name, "false").strip().lower() in _TRUTHY


@dataclass(slots=True)
class BridgeResult:
    """Унифицированный результат для всех entrypoint-транспортов.

    Attributes:
        success: ``True`` — данные валидны, ``False`` — смотри ``error``.
        data: Полезная нагрузка (тело результата action или DSL exchange).
        error: Текст ошибки (заполнен при ``success=False``).
        via: Источник результата:
            ``"dispatcher"`` — ActionDispatcher с middleware,
            ``"dsl"`` — DSL-fallback (Tier 3),
            ``"missing"`` — ни один не нашёл целевой action/route.
        error_code: Машиночитаемый код ошибки от ActionDispatcher
            (``"action_not_found"``, ``"validation_failed"`` и т.п.) —
            ``None`` для DSL-пути.
    """

    success: bool
    data: Any = None
    error: str | None = None
    via: str = "missing"
    error_code: str | None = None


async def dispatch_action_or_dsl(
    *,
    action_id: str,
    dsl_route_id: str,
    payload: Mapping[str, Any],
    transport: str,
    headers: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> BridgeResult:
    """Выполняет action через ActionDispatcher или fallback на DSL-маршрут.

    Args:
        action_id: Имя action в ``action_handler_registry`` (Tier 1/2).
        dsl_route_id: ID DSL-маршрута для Tier 3 fallback (``route_registry``).
        payload: Полезная нагрузка вызова.
        transport: Имя транспорта (``"ws"`` / ``"webhook"`` / ``"express"``
            / ``"sse"``) — определяет feature-flag и ``DispatchContext.source``.
        headers: Дополнительные заголовки (передаются в DSL fallback и
            записываются в ``DispatchContext.attributes``).
        correlation_id: Сквозной ID запроса (из заголовков транспорта).
        idempotency_key: Ключ идемпотентности (если транспорт его передаёт).
        attributes: Произвольные атрибуты транспорта (sync_id, client_id,
            event_type и т.п.) — попадут в ``DispatchContext.attributes``.

    Returns:
        :class:`BridgeResult`. Поле ``via`` показывает, какой путь
        отработал.
    """
    if is_dispatcher_enabled_for(transport):
        result = await _try_dispatcher(
            action_id=action_id,
            payload=payload,
            transport=transport,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            attributes=_merge_attributes(headers, attributes),
        )
        if result is not None:
            return result

    return await _dispatch_dsl(
        dsl_route_id=dsl_route_id, payload=payload, headers=headers
    )


async def _try_dispatcher(
    *,
    action_id: str,
    payload: Mapping[str, Any],
    transport: str,
    correlation_id: str | None,
    idempotency_key: str | None,
    attributes: Mapping[str, Any],
) -> BridgeResult | None:
    """Пытается выполнить action через ActionDispatcher.

    Возвращает ``None``, если action не зарегистрирован — caller тогда
    идёт по DSL-fallback. Возвращает :class:`BridgeResult` (success или
    error envelope), если dispatcher отработал.
    """
    from src.core.di.contexts import make_dispatch_context
    from src.core.di.providers import get_action_dispatcher_provider

    dispatcher = get_action_dispatcher_provider()
    if not dispatcher.is_registered(action_id):
        return None

    context = make_dispatch_context(
        source=transport,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        attributes=attributes,
    )
    envelope = await dispatcher.dispatch(action_id, dict(payload), context)

    if envelope.success:
        return BridgeResult(success=True, data=envelope.data, via="dispatcher")

    error = envelope.error
    return BridgeResult(
        success=False,
        error=error.message if error else "dispatch failed",
        via="dispatcher",
        error_code=error.code if error else None,
    )


async def _dispatch_dsl(
    *, dsl_route_id: str, payload: Mapping[str, Any], headers: Mapping[str, Any] | None
) -> BridgeResult:
    """Tier 3 fallback: классический DSL-dispatch через ``DslService``.

    Не использует middleware-цепочку и envelope; возвращает «сырой»
    результат маршрута. Ошибка ``KeyError`` интерпретируется как
    «маршрут не найден» (``via="missing"``), любая другая — как сбой
    выполнения (``via="dsl"``, ``success=False``).
    """
    from src.dsl.service import get_dsl_service

    dsl = get_dsl_service()
    try:
        exchange = await dsl.dispatch(
            route_id=dsl_route_id,
            body=dict(payload),
            headers=dict(headers) if headers else None,
        )
    except KeyError:
        return BridgeResult(
            success=False,
            error=f"Маршрут {dsl_route_id!r} не найден",
            via="missing",
            error_code="action_not_found",
        )
    except Exception as exc:  # noqa: BLE001 — мост маппит в envelope.
        return BridgeResult(
            success=False,
            error=str(exc) or exc.__class__.__name__,
            via="dsl",
            error_code="dispatch_failed",
        )

    if exchange.error:
        return BridgeResult(
            success=False,
            data=exchange.out_message.body if exchange.out_message else None,
            error=exchange.error,
            via="dsl",
        )

    body = exchange.out_message.body if exchange.out_message else None
    return BridgeResult(success=True, data=body, via="dsl")


def _merge_attributes(
    headers: Mapping[str, Any] | None, attributes: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Готовит ``DispatchContext.attributes`` из headers + явных атрибутов.

    Headers идут первыми (могут быть перезаписаны явными ``attributes``,
    которые транспорт передаёт точечно — ``sync_id``, ``client_id`` и т.п.).
    """
    merged: dict[str, Any] = {}
    if headers:
        merged.update(headers)
    if attributes:
        merged.update(attributes)
    return merged
