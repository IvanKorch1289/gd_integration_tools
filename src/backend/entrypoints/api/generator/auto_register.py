from __future__ import annotations

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

ADR-0421: auto-поверхность — универсальный вход к любому action'у, поэтому
endpoint проверяет права: action с ``permissions``/``admin``-префиксом
требует соответствующего права, иначе HTTP 403 (fail-closed).
"""


import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from src.backend.core.api.extensions import (
    ActionHandlerRegistry,
    action_handler_registry,
)
from src.backend.core.types.invocation_command import ActionCommandMetaSchema
from src.backend.dsl.commands.action_registry import (
    ActionPermissionDeniedError,
    resolve_action_permissions,
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

#: HTTP-статус для тела, не совпадающего с формой action'а (422 — тело
#: syntactically корректно, но не проходит контракт action'а).
_UNPROCESSABLE_ENTITY: int = 422

#: Маркеры ошибок связывания аргументов (``method(**payload)``).
#:
#: Отличают «тело не подходит по форме» (→ 422) от настоящего бага внутри
#: бизнес-логики action'а (→ 500, проброс TypeError без изменений).
_BINDING_ERROR_MARKERS: tuple[str, ...] = (
    "unexpected keyword argument",
    "got multiple values for argument",
    "missing required argument",
    "required positional argument",
)


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


def _jsonable(value: Any) -> Any:
    """Рекурсивно превращает SQLAlchemy-модели в dict по колонкам.

    Прочие типы (dict/list/scalars/pydantic) остаются как есть — их
    FastAPI сериализует сам. ponytail: без поддержки вложенных ORM в
    произвольных коллекциях глубже list/dict.
    """
    if hasattr(value, "__table__") and hasattr(value, "__dict__"):
        return {c.name: getattr(value, c.name) for c in value.__table__.columns}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


async def _read_payload(request: Request) -> tuple[dict[str, Any], str]:
    """Читает тело запроса и приводит его к payload action'а.

    Args:
        request: Текущий FastAPI Request.

    Returns:
        tuple: ``(payload, body_kind)``, где ``body_kind`` описывает вид
        исходного тела (``"query"``/``"object"``/``"empty"``/``"list"``/...) —
        используется для описания ожидаемой формы тела в ответе 422.

    """
    if request.method.upper() in {"GET", "DELETE", "HEAD", "OPTIONS"}:
        return dict(request.query_params), "query"
    try:
        body = await request.json()
    except ValueError, RuntimeError:
        # Тело отсутствует или не валидный JSON — допустимо для
        # action'а без payload_model; падать не нужно.
        body = None
    if isinstance(body, dict):
        return body, "object"
    if body is None:
        return {}, "empty"
    # Если клиент прислал не-dict (список/строку), кладём как
    # ``{"data": ...}``; это приемлемый default для RPC-обёртки.
    # Если у action'а нет параметра ``data`` — dispatch упадёт с TypeError,
    # который ниже превращается в 422 с описанием ожидаемой формы тела.
    return {"data": body}, type(body).__name__


def _expected_fields(registry: ActionHandlerRegistry, action: str) -> list[str]:
    """Возвращает имена полей payload-схемы action'а (пусто — схемы нет).

    Args:
        registry: Реестр action-обработчиков.
        action: Имя action'а.

    Returns:
        list[str]: Отсортированные имена полей payload-модели.

    """
    metadata = registry.get_metadata(action)
    input_model = getattr(metadata, "input_model", None)
    model_fields = getattr(input_model, "model_fields", None)
    if not model_fields:
        return []
    return sorted(model_fields)


def _is_binding_error(exc: TypeError) -> bool:
    """Проверяет, что TypeError — ошибка связывания аргументов вызова.

    Args:
        exc: Исключение из ``method(**payload)``.

    Returns:
        ``True``, если ошибка вызвана несовпадением формы тела и сигнатуры
        action'а (→ 422), иначе ``False`` (настоящий баг → 500).

    """
    message = str(exc)
    return any(marker in message for marker in _BINDING_ERROR_MARKERS)


def _invalid_body_detail(
    *,
    action: str,
    body_kind: str,
    payload: dict[str, Any],
    expected_fields: list[str],
    reason: str,
    error: str | None = None,
) -> dict[str, Any]:
    """Собирает ``detail`` для ответа 422 (описание ожидаемой формы тела).

    Args:
        action: Имя action'а.
        body_kind: Вид исходного тела запроса.
        payload: Payload, который ушёл в dispatch.
        expected_fields: Ожидаемые поля (пусто — payload-схемы нет).
        reason: Машиночитаемый код причины.
        error: Текст исходной ошибки (для диагностики).

    Returns:
        dict[str, Any]: Тело ``detail`` для HTTPException.

    """
    if body_kind == "object":
        expected = expected_fields or "не заданы (у action нет payload-схемы)"
        message = (
            f"Тело запроса не соответствует action '{action}': "
            f"ожидаемые поля: {expected}."
        )
    elif body_kind == "empty":
        message = (
            f"Тело запроса пусто, а action '{action}' ожидает параметры: "
            f"{expected_fields or 'не заданы (у action нет payload-схемы)'}."
        )
    else:
        message = (
            "Ожидается JSON-объект в теле запроса "
            '(например {"field": "value"}), '
            f"получено: {body_kind}."
        )
    detail: dict[str, Any] = {
        "code": "invalid_request_body",
        "action": action,
        "reason": reason,
        "detail": message,
        "expected_fields": expected_fields,
        "received_fields": sorted(payload),
    }
    if error:
        detail["error"] = error
    return detail


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
        payload, body_kind = await _read_payload(request)

        # P0 (cycle 59, parity с cycle 4/5/24): пробрасываем
        # principal/permissions из auth middleware (request.state.auth)
        # в ActionCommandSchema.meta. Auto-endpoints наследуют тот же
        # auth context что и явные routes (auth middleware ставит
        # ``request.state.auth`` перед handler).
        #
        # ADR-0421: permissions собираются через
        # ``resolve_action_permissions`` — он учитывает и user-permissions,
        # и admin-роли (``metadata["admin_roles"]`` → ``role:admin``).
        _auth = getattr(request.state, "auth", None)
        _principal = getattr(_auth, "principal", "")
        _permissions = resolve_action_permissions(_auth)

        command = ActionCommandSchema(
            action=action,
            payload=payload,
            meta=ActionCommandMetaSchema(
                principal=_principal, permissions=list(_permissions)
            ),
        )
        try:
            result = registry.dispatch(command)
            if inspect.isawaitable(result):
                result = await result
        except ActionPermissionDeniedError as exc:
            # ADR-0421: action без прав → 403 (fail-closed), детали — в лог/audit.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_detail()
            ) from exc
        except ValidationError as exc:
            # Payload не прошёл payload-схему action'а → 422 (не 500).
            raise HTTPException(
                status_code=_UNPROCESSABLE_ENTITY,
                detail=_invalid_body_detail(
                    action=action,
                    body_kind=body_kind,
                    payload=payload,
                    expected_fields=_expected_fields(registry, action),
                    reason="schema_validation_failed",
                    error=str(exc),
                ),
            ) from exc
        except TypeError as exc:
            # Ошибка связывания аргументов (``method(**payload)``) → тело не
            # подходит по форме → 422. Прочие TypeError — настоящий баг
            # внутри action'а → пробрасываем как 500.
            if not _is_binding_error(exc):
                raise
            raise HTTPException(
                status_code=_UNPROCESSABLE_ENTITY,
                detail=_invalid_body_detail(
                    action=action,
                    body_kind=body_kind,
                    payload=payload,
                    expected_fields=_expected_fields(registry, action),
                    reason="unexpected_body_fields",
                    error=str(exc),
                ),
            ) from exc
        # Auto-endpoint без response_model: FastAPI 0.141 сериализует возврат
        # pydantic-путём и падает на SQLAlchemy-моделях — нормализуем в dict.
        return jsonable_encoder(_jsonable(result))

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
        # Sprint 226 fix: use ``app.add_api_route`` directly (NOT
        # ``APIRouter.add_api_route`` + ``app.include_router``) — in
        # FastAPI 0.141.1 routes added to separate APIRouter via
        # include_router do NOT appear in ``app.routes`` (bug or
        # behavior change). Direct registration ensures the route is
        # visible in ``app.routes`` and properly registered with the
        # auto-prefix path.
        app.add_api_route(
            path=f"{_AUTO_PREFIX}/{action}",
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

    return added
