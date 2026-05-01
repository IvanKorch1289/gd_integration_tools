"""Wave 14.1.E: Action Inventory API.

Эндпоинт ``GET /api/v1/actions/inventory`` отдаёт JSON-каталог
всех зарегистрированных :class:`ActionMetadata` для:

* Streamlit Action Console — drop-down + auto-complete;
* MCP auto-export tool list (вне DSL);
* OpenAPI enrichment (developer portal);
* контрактные тесты (smoke: «зарегистрированы все ожидаемые action»).

Регистрация — через :class:`ActionRouterBuilder` + :class:`ActionSpec`,
как и все остальные endpoints W26.5/14.1. Прямых ``@router.get`` нет.

Опциональный фильтр ``transport`` (``http`` | ``ws`` | ``grpc`` |
``mq`` | ``scheduler`` | ``internal``) — соответствует
:meth:`ActionGatewayDispatcher.list_metadata`.

Авторизация: эндпоинт информационный (метаданные, не payload),
доступен под глобальным :class:`APIKeyMiddleware` как и остальные
admin-роуты, но смонтирован отдельно под ``/actions`` чтобы
Streamlit Console мог обращаться к нему без admin-prefix.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.core.interfaces.action_dispatcher import ActionMetadata
from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec

__all__ = ("router",)


# --------------------------------------------------------------------------- #
# Response schemas                                                            #
# --------------------------------------------------------------------------- #


class ActionMetadataView(BaseModel):
    """JSON-проекция :class:`ActionMetadata` для REST-ответа.

    Pydantic-моделей в core/interfaces нет (это Protocol-уровень
    без runtime-зависимости от ``pydantic``), поэтому конвертация
    выполняется в фасаде через :func:`_metadata_to_view`.
    """

    action: str = Field(..., description="Уникальное имя action.")
    description: str | None = Field(default=None, description="Описание.")
    input_model: str | None = Field(
        default=None,
        description="Полное имя Pydantic-модели payload (или None).",
    )
    output_model: str | None = Field(
        default=None,
        description="Полное имя Pydantic-модели ответа (или None).",
    )
    transports: tuple[str, ...] = Field(
        default=(),
        description="Транспорты, через которые action доступен.",
    )
    side_effect: str = Field(
        default="none",
        description='"none" | "read" | "write" | "external".',
    )
    idempotent: bool = Field(default=False, description="Идемпотентен ли action.")
    permissions: tuple[str, ...] = Field(
        default=(),
        description="Требуемые RBAC/ABAC scopes.",
    )
    rate_limit: int | None = Field(
        default=None,
        description="Лимит вызовов в секунду на арендатора.",
    )
    timeout_ms: int | None = Field(
        default=None,
        description="Таймаут выполнения, мс.",
    )
    deprecated: bool = Field(default=False, description="Помечен ли как устаревший.")
    since_version: str | None = Field(
        default=None,
        description="Версия API, в которой action появился.",
    )
    error_types: tuple[str, ...] = Field(
        default=(),
        description="Известные коды ошибок.",
    )
    tags: tuple[str, ...] = Field(default=(), description="Теги для группировки.")


class ActionInventoryQuery(BaseModel):
    """Опциональные query-параметры фильтра."""

    transport: str | None = Field(
        default=None,
        description=(
            'Фильтр по транспорту: "http" | "ws" | "grpc" | "mq" | '
            '"scheduler" | "internal". Если не задан — возвращаются все.'
        ),
    )


class ActionInventoryResponse(BaseModel):
    """Каталог зарегистрированных actions."""

    actions: list[ActionMetadataView] = Field(
        default_factory=list,
        description="Метаданные всех зарегистрированных action.",
    )
    total: int = Field(..., description="Количество actions в выдаче.")
    transport: str | None = Field(
        default=None,
        description="Применённый фильтр транспорта (None — без фильтра).",
    )


# --------------------------------------------------------------------------- #
# Conversion helpers                                                          #
# --------------------------------------------------------------------------- #


def _model_qualname(model: type[Any] | None) -> str | None:
    """Возвращает ``module.QualName`` для Pydantic-модели или None."""
    if model is None:
        return None
    module = getattr(model, "__module__", None) or ""
    name = getattr(model, "__qualname__", None) or getattr(model, "__name__", "")
    return f"{module}.{name}" if module else name


def _metadata_to_view(meta: ActionMetadata) -> ActionMetadataView:
    """Конвертирует core-DTO :class:`ActionMetadata` в Pydantic-view."""
    return ActionMetadataView(
        action=meta.action,
        description=meta.description,
        input_model=_model_qualname(meta.input_model),
        output_model=_model_qualname(meta.output_model),
        transports=tuple(meta.transports),
        side_effect=meta.side_effect,
        idempotent=meta.idempotent,
        permissions=tuple(meta.permissions),
        rate_limit=meta.rate_limit,
        timeout_ms=meta.timeout_ms,
        deprecated=meta.deprecated,
        since_version=meta.since_version,
        error_types=tuple(meta.error_types),
        tags=tuple(meta.tags),
    )


# --------------------------------------------------------------------------- #
# Facade (service-layer-style getter для ActionSpec)                          #
# --------------------------------------------------------------------------- #


class _ActionInventoryFacade:
    """Адаптер для inventory-эндпоинта.

    Тонкая обёртка над :class:`ActionGatewayDispatcher.list_metadata` —
    форматирует выдачу под REST-схему. Изоляция реализации позволяет
    тестам подменять диспетчер без обращения к global state.
    """

    async def list_inventory(
        self, *, transport: str | None = None
    ) -> ActionInventoryResponse:
        # Lazy import — диспетчер строится в composition root, импорт
        # из entrypoints в core.di выполняется только в runtime.
        from src.core.di.providers import get_action_dispatcher_provider

        dispatcher = get_action_dispatcher_provider()
        metas = dispatcher.list_metadata(transport)
        views = [_metadata_to_view(m) for m in metas]
        return ActionInventoryResponse(
            actions=views,
            total=len(views),
            transport=transport,
        )


_FACADE = _ActionInventoryFacade()


def _get_facade() -> _ActionInventoryFacade:
    return _FACADE


# --------------------------------------------------------------------------- #
# Router                                                                      #
# --------------------------------------------------------------------------- #


router = APIRouter()
builder = ActionRouterBuilder(router)


builder.add_actions(
    [
        ActionSpec(
            name="actions_inventory",
            method="GET",
            path="/inventory",
            summary="Каталог всех зарегистрированных action (Wave 14.1.E)",
            description=(
                "Возвращает список ActionMetadata всех зарегистрированных "
                "actions. Используется Streamlit Action Console, MCP "
                "auto-export, developer portal и контрактными тестами. "
                "Опциональный фильтр transport: http|ws|grpc|mq|scheduler."
            ),
            service_getter=_get_facade,
            service_method="list_inventory",
            query_model=ActionInventoryQuery,
            response_model=ActionInventoryResponse,
            tags=("Actions Inventory",),
        ),
    ]
)
