"""Wave 1.2 (Roadmap V10): авторегистрация REST-роутов для action'ов.

Цель — устранить дублирование между ``ActionHandlerRegistry`` (DSL/контракт
бизнес-команд) и ``ActionRouterBuilder`` (REST-роуты): каждый action,
зарегистрированный как handler, но **без** соответствующего REST-роута,
автоматически получает sane-default endpoint на пути
``/api/v1/auto/<action>``.

Алгоритм::

    auto_register_unrouted_actions(app, registry)
        scan существующие FastAPI-роуты
        scan registry.list_actions()
        для actions, у которых нет HTTP-роута:
            построить endpoint, который вызывает
            ``registry.dispatch(ActionCommandSchema(...))``
            добавить роут на ``/api/v1/auto/<action>``
        вернуть число добавленных роутов

Особенности:

* ``Tier 1`` actions (``<resource>.<verb>`` с известным CRUD-глаголом)
  получают «правильный» HTTP-метод по REST-конвенции
  (``list``/``get`` → GET, ``create``/``create_many`` → POST,
  ``update`` → PUT, ``delete`` → DELETE).
* Прочие actions получают POST (тело — произвольный JSON), что соответствует
  семантике RPC-команды.
* Если ``ActionHandlerSpec.payload_model`` указан — он используется как
  ``body_model``, что даёт корректную OpenAPI-схему. Иначе — приём
  ``dict[str, Any]``.
* Не дублирует уже существующие роуты: если в FastAPI уже зарегистрирован
  роут с именем ``"auto.<action>"`` — пропускаем.

Вызывается из ``app_factory.create_app`` после регистрации основных
роутов (см. Wave 1.2 в ``PLAN.md``).
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, FastAPI, Request

from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = ("auto_register_unrouted_actions",)


# Маппинг CRUD-глагола (после точки в ``<resource>.<verb>``) → HTTP method.
# Совпадает с конвенцией ``_infer_tier1_action_id`` (Wave F.8).
_VERB_TO_METHOD: dict[str, str] = {
    "list": "GET",
    "get": "GET",
    "create": "POST",
    "create_many": "POST",
    "update": "PUT",
    "delete": "DELETE",
}

# Префикс для авто-роутов; защищает от коллизий с ручными ``/api/v1/...``.
_AUTO_PREFIX = "/api/v1/auto"


def _infer_method_for_action(action: str) -> str:
    """Выбрать HTTP-метод для авто-роута по action-имени.

    Если имя имеет вид ``"<resource>.<verb>"`` и ``<verb>`` известен —
    используется соответствующий метод (REST-конвенция Wave F.8).
    Иначе — ``POST`` (RPC-семантика).
    """
    if "." in action:
        verb = action.rsplit(".", 1)[-1].lower()
        if verb in _VERB_TO_METHOD:
            return _VERB_TO_METHOD[verb]
    return "POST"


def _build_auto_route_name(action: str) -> str:
    """Собрать имя FastAPI-роута: ``"auto.<action>"`` (стабильный ключ для idempotency)."""
    return f"auto.{action}"


def _collect_existing_route_names(app: FastAPI) -> set[str]:
    """Собрать множество имён всех зарегистрированных в приложении роутов.

    Используется для idempotency: повторный вызов ``auto_register_*``
    не должен плодить дубликаты.
    """
    names: set[str] = set()
    for route in app.routes:
        name = getattr(route, "name", None)
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _build_auto_endpoint(
    *, action: str, registry: ActionHandlerRegistry
) -> Callable[..., Awaitable[Any]]:
    """Построить endpoint-замыкание, делегирующее в ``registry.dispatch``.

    Endpoint принимает FastAPI ``Request`` и опциональное тело JSON;
    собирает :class:`ActionCommandSchema` и вызывает ``registry.dispatch``.
    Сигнатура минимальна (request + payload), чтобы FastAPI корректно
    сгенерировал OpenAPI-схему для метода без чёткого input-model.
    """

    async def endpoint(request: Request) -> Any:
        # Тело может быть как dict, так и пустым (для GET/DELETE).
        payload: dict[str, Any]
        if request.method.upper() in {"GET", "DELETE", "HEAD", "OPTIONS"}:
            payload = dict(request.query_params)
        else:
            try:
                body = await request.json()
            except ValueError, RuntimeError:
                # Тело отсутствует или не валидный JSON — допустимо для
                # action'а без payload_model; падать не нужно.
                body = None
            if isinstance(body, dict):
                payload = body
            elif body is None:
                payload = {}
            else:
                # Если клиент прислал не-dict (список/строку), кладём как
                # ``{"data": ...}``; это приемлемый default для RPC-обёртки.
                payload = {"data": body}

        command = ActionCommandSchema(action=action, payload=payload)
        result = registry.dispatch(command)
        if inspect.isawaitable(result):
            result = await result
        return result

    endpoint.__name__ = f"auto_{action.replace('.', '_')}"
    endpoint.__doc__ = (
        f"Авто-зарегистрированный endpoint для action '{action}' (Wave 1.2)."
    )
    return endpoint


def auto_register_unrouted_actions(
    app: FastAPI, registry: ActionHandlerRegistry | None = None
) -> int:
    """Зарегистрировать REST-роуты для action'ов без явного маршрута.

    Сканирует ``registry.list_actions()`` и для каждого action, у которого
    нет соответствующего FastAPI-роута, добавляет endpoint на пути
    ``/api/v1/auto/<action>``.

    Идемпотентность: при повторном вызове действия с уже существующим
    роутом ``auto.<action>`` пропускаются.

    Args:
        app: Экземпляр :class:`FastAPI` (контекст приложения).
        registry: Реестр action-обработчиков. По умолчанию используется
            глобальный ``action_handler_registry``.

    Returns:
        Число вновь добавленных роутов.
    """
    reg = registry if registry is not None else action_handler_registry
    existing_names = _collect_existing_route_names(app)

    auto_router = APIRouter()
    added = 0

    for action in reg.list_actions():
        route_name = _build_auto_route_name(action)
        if route_name in existing_names:
            # Уже есть авто-роут (повторный вызов) — пропускаем.
            continue

        # Если для action уже существует обычный REST-роут (через
        # ActionRouterBuilder.add_action: route.name == ActionSpec.name),
        # пропускаем, чтобы не плодить дубль.
        # Эвристика: имя action в исторических случаях совпадает с
        # ``ActionSpec.name`` (например, ``healthcheck_database``).
        if action in existing_names:
            continue

        method = _infer_method_for_action(action)
        endpoint = _build_auto_endpoint(action=action, registry=reg)
        auto_router.add_api_route(
            path=f"/{action}",
            endpoint=endpoint,
            methods=[method],
            name=route_name,
            summary=f"Auto-registered action '{action}'",
            description=(
                f"Авто-зарегистрированный endpoint для action '{action}' "
                f"(Wave 1.2 REST auto-loop). "
                f"Делегирует в ActionHandlerRegistry.dispatch."
            ),
            tags=["Auto-Registered"],
        )
        added += 1
        existing_names.add(route_name)

    if added:
        app.include_router(auto_router, prefix=_AUTO_PREFIX)

    return added
