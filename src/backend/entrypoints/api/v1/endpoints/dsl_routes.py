"""Admin REST API для управления DSL-маршрутами через YAMLStore.

W26.5: маршруты регистрируются декларативно — ActionSpec для JSON-
эндпоинтов и ``router.add_api_route`` для text/plain (Python-код).

Endpoints (под ``/api/v1/admin/dsl-routes``):

    * GET    /              — список route_id.
    * GET    /{route_id}    — yaml + spec + python для маршрута.
    * GET    /{route_id}/python  — text/plain Python-код.
    * POST   /              — создать маршрут (body: yaml).
    * PUT    /{route_id}    — обновить маршрут (body: yaml).
    * DELETE /{route_id}    — удалить маршрут.
    * POST   /validate      — валидация YAML без записи на диск.
    * POST   /{route_id}/diff  — diff с переданным YAML.

Авторизация: эндпоинты монтируются под ``/admin`` — защищены
глобальным :class:`APIKeyMiddleware`.

Директория хранилища: env ``DSL_YAML_STORE_DIR`` (default
``<root_dir>/routes_store``). Создаётся автоматически.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml
from src.backend.dsl.yaml_store import YAMLStore
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)

__all__ = ("router",)

_logger = logging.getLogger("admin.dsl_routes")


# --- DI --------------------------------------------------------------------


@lru_cache(maxsize=1)
def _yaml_store() -> YAMLStore:
    """Ленивый singleton :class:`YAMLStore` на директорию из настроек."""
    raw = os.getenv("DSL_YAML_STORE_DIR")
    if raw:
        store_dir = Path(raw)
    else:
        from src.backend.core.config.base import app_base_settings

        store_dir = Path(app_base_settings.root_dir) / "routes_store"
    return YAMLStore(store_dir)


# --- Pydantic schemas ------------------------------------------------------


class YamlPayload(BaseModel):
    """Тело запроса с YAML-описанием маршрута."""

    yaml: str = Field(..., description="YAML-описание Pipeline маршрута.")


class RouteDetailOut(BaseModel):
    """Детальная информация о маршруте: YAML + spec + Python-код."""

    route_id: str
    yaml: str
    spec: dict
    python: str


class RouteValidationOut(BaseModel):
    """Результат валидации YAML без записи на диск."""

    valid: bool
    route_id: str | None = None
    processors_count: int = 0
    error: str | None = None


class RouteDiffOut(BaseModel):
    """Unified diff между текущим и предложенным YAML."""

    route_id: str
    diff: str


class RouteIdPath(BaseModel):
    """Path-параметр идентификатора маршрута."""

    route_id: str = Field(..., description="route_id YAML-маршрута.")


# --- Helpers ---------------------------------------------------------------


def _parse_yaml_or_400(yaml_str: str) -> Pipeline:
    """Парсит YAML в Pipeline или поднимает 400 при ошибке."""
    try:
        return load_pipeline_from_yaml(yaml_str)
    except (ValueError, ImportError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Невалидный YAML: {exc}"
        ) from exc


def _to_detail(pipeline: Pipeline) -> RouteDetailOut:
    """Сборка ответа RouteDetailOut из Pipeline."""
    return RouteDetailOut(
        route_id=pipeline.route_id,
        yaml=pipeline.to_yaml(),
        spec=pipeline.to_dict(),
        python=pipeline.to_python(),
    )


# --- Service facade --------------------------------------------------------


class _DSLRoutesFacade:
    """Адаптер над :class:`YAMLStore` для action-маршрутов."""

    async def list_routes(self) -> list[str]:
        return _yaml_store().list()

    async def get_route(self, *, route_id: str) -> RouteDetailOut:
        store = _yaml_store()
        if not store.exists(route_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Маршрут {route_id!r} не найден",
            )
        try:
            pipeline = store.load(route_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка загрузки маршрута: {exc}",
            ) from exc
        return _to_detail(pipeline)

    async def create_route(self, *, yaml: str) -> RouteDetailOut:
        pipeline = _parse_yaml_or_400(yaml)
        store = _yaml_store()
        if store.exists(pipeline.route_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Маршрут {pipeline.route_id!r} уже существует. "
                    "Используйте PUT для обновления."
                ),
            )
        store.save(pipeline)
        _logger.info("dsl-routes: created %r", pipeline.route_id)
        return _to_detail(pipeline)

    async def update_route(self, *, route_id: str, yaml: str) -> RouteDetailOut:
        store = _yaml_store()
        if not store.exists(route_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Маршрут {route_id!r} не найден",
            )
        pipeline = _parse_yaml_or_400(yaml)
        if pipeline.route_id != route_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"route_id в path ({route_id!r}) не совпадает с route_id в YAML "
                    f"({pipeline.route_id!r})"
                ),
            )
        store.save(pipeline)
        _logger.info("dsl-routes: updated %r", route_id)
        return _to_detail(pipeline)

    async def delete_route(self, *, route_id: str) -> Response:
        store = _yaml_store()
        if not store.delete(route_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Маршрут {route_id!r} не найден",
            )
        _logger.info("dsl-routes: deleted %r", route_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def validate_route(self, *, yaml: str) -> RouteValidationOut:
        try:
            pipeline = load_pipeline_from_yaml(yaml)
        except (ValueError, ImportError) as exc:
            return RouteValidationOut(valid=False, error=str(exc))
        return RouteValidationOut(
            valid=True,
            route_id=pipeline.route_id,
            processors_count=len(pipeline.processors),
        )

    async def diff_route(self, *, route_id: str, yaml: str) -> RouteDiffOut:
        store = _yaml_store()
        if not store.exists(route_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Маршрут {route_id!r} не найден",
            )
        current = store.load(route_id)
        proposed = _parse_yaml_or_400(yaml)
        return RouteDiffOut(route_id=route_id, diff=store.diff(current, proposed))


_FACADE = _DSLRoutesFacade()


def _get_facade() -> _DSLRoutesFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter(tags=["DSL · Routes Store"])
builder = ActionRouterBuilder(router)

common_tags = ("DSL · Routes Store",)


# Python-код требует response_class=Response с media_type='text/plain' —
# это не вписывается в ActionSpec-генерацию, поэтому endpoint регистрируется
# через add_api_route.
async def _get_route_python(route_id: str) -> Response:
    """Python-код Pipeline в виде text/plain."""
    store = _yaml_store()
    if not store.exists(route_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Маршрут {route_id!r} не найден",
        )
    pipeline = store.load(route_id)
    return Response(content=pipeline.to_python(), media_type="text/plain")


router.add_api_route(
    path="/dsl-routes/{route_id}/python",
    endpoint=_get_route_python,
    methods=["GET"],
    summary="Получить Python-код маршрута",
    description="Возвращает Python-код, воссоздающий Pipeline через RouteBuilder.",
    response_class=Response,
    name="get_dsl_route_python",
)


builder.add_actions(
    [
        ActionSpec(
            name="list_dsl_routes",
            method="GET",
            path="/dsl-routes",
            summary="Список route_id всех YAML-маршрутов",
            description="Возвращает отсортированный список route_id, сохранённых в YAMLStore.",
            service_getter=_get_facade,
            service_method="list_routes",
            response_model=list[str],
            tags=common_tags,
        ),
        ActionSpec(
            name="get_dsl_route",
            method="GET",
            path="/dsl-routes/{route_id}",
            summary="Получить YAML + spec + Python маршрута",
            description=(
                "Возвращает YAML-исходник, распарсенный JSON spec и сгенерированный "
                "Python-код для воссоздания Pipeline через RouteBuilder."
            ),
            service_getter=_get_facade,
            service_method="get_route",
            path_model=RouteIdPath,
            response_model=RouteDetailOut,
            tags=common_tags,
        ),
        ActionSpec(
            name="create_dsl_route",
            method="POST",
            path="/dsl-routes",
            summary="Создать новый YAML-маршрут",
            description=(
                "Парсит YAML, валидирует через RouteBuilder и сохраняет в YAMLStore. "
                "Возвращает 409 если маршрут с таким route_id уже существует."
            ),
            status_code=status.HTTP_201_CREATED,
            service_getter=_get_facade,
            service_method="create_route",
            body_model=YamlPayload,
            response_model=RouteDetailOut,
            tags=common_tags,
        ),
        ActionSpec(
            name="update_dsl_route",
            method="PUT",
            path="/dsl-routes/{route_id}",
            summary="Обновить существующий YAML-маршрут",
            description=(
                "Парсит YAML, валидирует и перезаписывает существующий маршрут. "
                "404 если маршрут не существует. route_id из path должен совпадать "
                "с route_id из YAML — иначе 400."
            ),
            service_getter=_get_facade,
            service_method="update_route",
            path_model=RouteIdPath,
            body_model=YamlPayload,
            response_model=RouteDetailOut,
            tags=common_tags,
        ),
        ActionSpec(
            name="delete_dsl_route",
            method="DELETE",
            path="/dsl-routes/{route_id}",
            summary="Удалить YAML-маршрут",
            description="Удаляет файл маршрута. 404 если маршрут не существует.",
            status_code=status.HTTP_204_NO_CONTENT,
            service_getter=_get_facade,
            service_method="delete_route",
            path_model=RouteIdPath,
            tags=common_tags,
        ),
        ActionSpec(
            name="validate_dsl_route",
            method="POST",
            path="/dsl-routes/validate",
            summary="Валидация YAML без записи на диск",
            description=(
                "Парсит YAML и возвращает статус валидации. Используется UI-редактором "
                "для подсветки ошибок до сохранения."
            ),
            service_getter=_get_facade,
            service_method="validate_route",
            body_model=YamlPayload,
            response_model=RouteValidationOut,
            tags=common_tags,
        ),
        ActionSpec(
            name="diff_dsl_route",
            method="POST",
            path="/dsl-routes/{route_id}/diff",
            summary="Diff между сохранённым и предложенным YAML",
            description=(
                "Парсит переданный YAML и возвращает unified-diff с текущей версией "
                "маршрута из YAMLStore. 404 если маршрут не существует."
            ),
            service_getter=_get_facade,
            service_method="diff_route",
            path_model=RouteIdPath,
            body_model=YamlPayload,
            response_model=RouteDiffOut,
            tags=common_tags,
        ),
    ]
)
