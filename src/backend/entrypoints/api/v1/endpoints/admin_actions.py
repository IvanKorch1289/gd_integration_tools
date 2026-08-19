"""Admin REST API для Action-Bus (K5 W4).

Эндпоинты предоставляют Streamlit-странице ``50_Action_Bus.py``
доступ к реестру actions и возможность их вызова.

Endpoints (под /api/v1/admin/actions):

    * GET  /list              — список зарегистрированных actions.
    * POST /invoke            — вызов action по имени.
    * GET  /{name}/spec       — спецификация action (params schema).

Флаг-охрана: ``feature_flags.admin_marketplace_endpoints == False``
→ 503 Service Unavailable для всех эндпоинтов.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("router",)

# S202 audit fix: require admin role
_ADMIN_GUARD_OPERATOR = Depends(
    require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN))
)

router = APIRouter(
    dependencies=[_ADMIN_GUARD_OPERATOR], prefix="/admin/actions", tags=["admin"]
)


# ─── Pydantic-схемы запроса/ответа ────────────────────────────────────────────


class ActionSummary(BaseModel):
    """Краткое описание action из реестра."""

    name: str
    description: str
    namespace: str
    tier: str


class ActionInvokeRequest(BaseModel):
    """Тело запроса POST /invoke."""

    name: str = Field(..., description="Имя action из реестра")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Параметры вызова"
    )
    mode: str = Field(
        default="sync", description="Режим вызова: sync / async / background"
    )


class ActionInvokeResponse(BaseModel):
    """Результат вызова action."""

    name: str
    mode: str
    result: Any
    invocation_id: str | None = None


class ActionSpec(BaseModel):
    """Полная спецификация action."""

    name: str
    description: str
    namespace: str
    tier: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


# ─── Вспомогательные функции ──────────────────────────────────────────────────


def _check_flag_enabled() -> None:
    """Проверяет feature-flag admin_marketplace_endpoints.

    Вызывает HTTP 503, если флаг выключен (default-OFF).
    """
    from src.backend.core.config.features import feature_flags  # lazy import

    if not feature_flags.admin_marketplace_endpoints:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin marketplace endpoints отключены (feature_flags.admin_marketplace_endpoints=False)",
        )


def _get_registry() -> Any:
    """Возвращает ActionHandlerRegistry, если доступен.

    При недоступности реестра возвращает None — эндпоинты
    используют mock-данные (placeholder).
    """
    try:
        # D-AUDIT-11601 fix (cycle 116): canonical path
        # src.backend.dsl.commands.action_registry (НЕ
        # src.backend.core.actions.registry — модуль НЕ существует,
        # type: ignore suppress'ил lint но runtime всегда падал
        # в except → mock-fallback). Реальный класс:
        # src/backend/dsl/commands/action_registry.py
        from src.backend.dsl.commands.action_registry import ActionHandlerRegistry

        return ActionHandlerRegistry.get_instance()
    except ImportError, AttributeError, RuntimeError:
        logger.warning("ActionHandlerRegistry недоступен — используется mock")
        return None


def _mock_actions() -> list[ActionSummary]:
    """Возвращает mock-список actions для случая, когда реестр недоступен."""
    return [
        ActionSummary(
            name="system.health.check",
            description="Проверка состояния системы",
            namespace="system",
            tier="1",
        ),
        ActionSummary(
            name="admin.config.reload",
            description="Перезагрузка конфигурации",
            namespace="admin",
            tier="2",
        ),
    ]


def _mock_spec(name: str) -> ActionSpec:
    """Возвращает mock-спецификацию action."""
    return ActionSpec(
        name=name,
        description=f"Спецификация action {name}",
        namespace=name.split(".")[0] if "." in name else "default",
        tier="1",
        params_schema={"type": "object", "properties": {}, "required": []},
        tags=[],
    )


# ─── Эндпоинты ────────────────────────────────────────────────────────────────


@router.get(
    "/list",
    response_model=list[ActionSummary],
    summary="Список зарегистрированных actions",
    description="Возвращает все actions из ActionHandlerRegistry. 503 при default-OFF flag.",
)
async def list_actions() -> list[ActionSummary]:
    """Возвращает список actions из реестра.

    D-AUDIT-9701 fix (cycle 97, API-P1-005): silent mock-fallback заменён
    на fail-LOUD HTTP 503. Раньше: при registry=None ИЛИ registry.list_all()
    exception → silent return _mock_actions() → admin UI получал mock-список
    вместо индикатора сбоя, decisions принимались на недостоверных данных.

    Returns:
        Список :class:`ActionSummary` с name, description, namespace, tier.

    Raises:
        HTTPException: 503 если feature_flags.admin_marketplace_endpoints=False.
        HTTPException: 503 если registry недоступен или list_all() падает.

    """
    _check_flag_enabled()

    registry = _get_registry()
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ActionHandlerRegistry недоступен — список actions не может быть получен",
        )

    try:
        specs = registry.list_all()
    except Exception as exc:
        # narrow: registry.list_all() может кинуть AttributeError (API mismatch),
        # RuntimeError (corrupted state), OSError (storage backend). Bоt
        # ВСЕ → 503 (fail-LOUD, не silent mock).
        logger.error(
            "Ошибка чтения реестра actions (exc_type=%s exc_msg=%s) — 503",
            type(exc).__name__,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Не удалось прочитать реестр actions: {exc}",
        ) from exc

    return [
        ActionSummary(
            name=spec.name,
            description=getattr(spec, "description", ""),
            namespace=getattr(spec, "namespace", "default"),
            tier=str(getattr(spec, "tier", "1")),
        )
        for spec in specs
    ]


@router.post(
    "/invoke",
    response_model=ActionInvokeResponse,
    summary="Вызвать action по имени",
    description="Вызывает action из ActionHandlerRegistry с указанным payload и mode.",
)
async def invoke_action(body: ActionInvokeRequest) -> ActionInvokeResponse:
    """Вызывает action через ActionHandlerRegistry.

    Args:
        body: :class:`ActionInvokeRequest` с name, payload, mode.

    Returns:
        :class:`ActionInvokeResponse` с результатом вызова.

    Raises:
        HTTPException: 503 если флаг выключен; 404 если action не найден.

    """
    _check_flag_enabled()

    registry = _get_registry()
    if registry is None:
        # S202 re-audit fix (cycle 241, P0-FIX-MOCK):
        # Fail-closed — ActionHandlerRegistry недоступен → 503, не silent 200 + mock.
        logger.warning(
            "action_invoke_registry_unavailable action=%s mode=%s", body.name, body.mode
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ActionHandlerRegistry недоступен — invoke отключён",
        )

    try:
        result = await registry.invoke(
            name=body.name, payload=body.payload, mode=body.mode
        )
        return ActionInvokeResponse(
            name=body.name,
            mode=body.mode,
            result=result,
            invocation_id=getattr(result, "invocation_id", None),
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{body.name}' не найден в реестре",
        )


@router.get(
    "/{name}/spec",
    response_model=ActionSpec,
    summary="Спецификация action",
    description="Возвращает полную спецификацию action включая params_schema.",
)
async def get_action_spec(name: str) -> ActionSpec:
    """Возвращает спецификацию action по имени.

    Args:
        name: Имя action в реестре.

    Returns:
        :class:`ActionSpec` с params_schema и метаданными.

    Raises:
        HTTPException: 503 если флаг выключен; 404 если action не найден.

    """
    _check_flag_enabled()

    registry = _get_registry()
    if registry is None:
        return _mock_spec(name)

    try:
        spec = registry.get(name)
        if spec is None:
            raise KeyError(name)
        return ActionSpec(
            name=spec.name,
            description=getattr(spec, "description", ""),
            namespace=getattr(spec, "namespace", "default"),
            tier=str(getattr(spec, "tier", "1")),
            params_schema=getattr(spec, "params_schema", {}),
            tags=list(getattr(spec, "tags", [])),
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{name}' не найден в реестре",
        )
