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

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = ("router",)

router = APIRouter(prefix="/admin/actions", tags=["admin"])


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
        from src.backend.core.actions.registry import (
            ActionHandlerRegistry,  # lazy import
        )

        return ActionHandlerRegistry.get_instance()
    except Exception:  # noqa: BLE001
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

    Returns:
        Список :class:`ActionSummary` с name, description, namespace, tier.

    Raises:
        HTTPException: 503 если feature_flags.admin_marketplace_endpoints=False.
    """
    _check_flag_enabled()

    registry = _get_registry()
    if registry is None:
        return _mock_actions()

    try:
        specs = registry.list_all()
        return [
            ActionSummary(
                name=spec.name,
                description=getattr(spec, "description", ""),
                namespace=getattr(spec, "namespace", "default"),
                tier=str(getattr(spec, "tier", "1")),
            )
            for spec in specs
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка чтения реестра actions: %s — возврат mock", exc)
        return _mock_actions()


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
        # Mock-ответ при недоступном реестре
        return ActionInvokeResponse(
            name=body.name,
            mode=body.mode,
            result={"status": "mock", "payload_received": body.payload},
            invocation_id="mock-00000000",
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
