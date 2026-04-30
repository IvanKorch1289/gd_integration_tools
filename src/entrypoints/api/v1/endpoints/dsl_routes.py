"""Admin REST API для управления DSL-маршрутами через YAMLStore.

Wave 3.8 (bidirectional YAML ↔ Python): CRUD-операции над файловым
хранилищем DSL-маршрутов. Работает поверх :class:`YAMLStore`
(``src/dsl/yaml_store.py``) и round-trip контракта Pipeline.to_yaml()
↔ load_pipeline_from_yaml().

Endpoints (под префиксом ``/api/v1/admin/dsl-routes``):

    * ``GET    /``                     — список route_id.
    * ``GET    /{route_id}``           — yaml + spec + python для маршрута.
    * ``GET    /{route_id}/python``    — только Python-код (text/plain).
    * ``POST   /``                     — создать маршрут (body: yaml).
    * ``PUT    /{route_id}``           — обновить маршрут (body: yaml).
    * ``DELETE /{route_id}``           — удалить маршрут.
    * ``POST   /validate``             — валидация YAML без записи на диск.
    * ``POST   /{route_id}/diff``      — diff с переданным YAML.

Авторизация: эндпоинты монтируются под ``/admin`` — защищены
глобальным :class:`APIKeyMiddleware` (см. ``api_key.py``).

Директория хранилища: env ``DSL_YAML_STORE_DIR`` (default
``<root_dir>/routes_store``). Создаётся автоматически.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.dsl.engine.pipeline import Pipeline
from src.dsl.yaml_loader import load_pipeline_from_yaml
from src.dsl.yaml_store import YAMLStore

__all__ = ("router",)

_logger = logging.getLogger("admin.dsl_routes")

router = APIRouter(tags=["DSL · Routes Store"])


# --- DI ----------------------------------------------------------------


@lru_cache(maxsize=1)
def _yaml_store() -> YAMLStore:
    """Ленивый singleton :class:`YAMLStore` на директорию из настроек.

    Директория берётся из env ``DSL_YAML_STORE_DIR``. Если переменная
    не задана — fallback на ``<root_dir>/routes_store`` (root_dir читается
    лениво из ``app_base_settings`` чтобы не требовать полной конфигурации
    для импорта модуля). ``YAMLStore`` создаёт директорию автоматически.
    """
    raw = os.getenv("DSL_YAML_STORE_DIR")
    if raw:
        store_dir = Path(raw)
    else:
        from src.core.config.base import app_base_settings

        store_dir = Path(app_base_settings.root_dir) / "routes_store"
    return YAMLStore(store_dir)


# --- Pydantic schemas --------------------------------------------------


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


# --- Helpers -----------------------------------------------------------


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


# --- Endpoints ---------------------------------------------------------


@router.get(
    "/dsl-routes",
    response_model=list[str],
    summary="Список route_id всех YAML-маршрутов",
    description="Возвращает отсортированный список route_id, сохранённых в YAMLStore.",
)
async def list_dsl_routes() -> list[str]:
    """Список сохранённых маршрутов."""
    return _yaml_store().list()


@router.get(
    "/dsl-routes/{route_id}",
    response_model=RouteDetailOut,
    summary="Получить YAML + spec + Python маршрута",
    description=(
        "Возвращает YAML-исходник, распарсенный JSON spec и сгенерированный "
        "Python-код для воссоздания Pipeline через RouteBuilder."
    ),
)
async def get_dsl_route(route_id: str) -> RouteDetailOut:
    """Получить детальную информацию о маршруте."""
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


@router.get(
    "/dsl-routes/{route_id}/python",
    summary="Получить Python-код маршрута",
    description="Возвращает Python-код, воссоздающий Pipeline через RouteBuilder.",
    response_class=Response,
)
async def get_dsl_route_python(route_id: str) -> Response:
    """Python-код Pipeline в виде text/plain."""
    store = _yaml_store()
    if not store.exists(route_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Маршрут {route_id!r} не найден",
        )
    pipeline = store.load(route_id)
    return Response(content=pipeline.to_python(), media_type="text/plain")


@router.post(
    "/dsl-routes",
    response_model=RouteDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать новый YAML-маршрут",
    description=(
        "Парсит YAML, валидирует через RouteBuilder и сохраняет в YAMLStore. "
        "Возвращает 409 если маршрут с таким route_id уже существует."
    ),
)
async def create_dsl_route(payload: YamlPayload = Body(...)) -> RouteDetailOut:
    """Создать новый маршрут."""
    pipeline = _parse_yaml_or_400(payload.yaml)
    store = _yaml_store()
    if store.exists(pipeline.route_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Маршрут {pipeline.route_id!r} уже существует. Используйте PUT для обновления.",
        )
    store.save(pipeline)
    _logger.info("dsl-routes: created %r", pipeline.route_id)
    return _to_detail(pipeline)


@router.put(
    "/dsl-routes/{route_id}",
    response_model=RouteDetailOut,
    summary="Обновить существующий YAML-маршрут",
    description=(
        "Парсит YAML, валидирует и перезаписывает существующий маршрут. "
        "404 если маршрут не существует. route_id из path должен совпадать "
        "с route_id из YAML — иначе 400."
    ),
)
async def update_dsl_route(
    route_id: str, payload: YamlPayload = Body(...)
) -> RouteDetailOut:
    """Обновить существующий маршрут."""
    store = _yaml_store()
    if not store.exists(route_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Маршрут {route_id!r} не найден",
        )
    pipeline = _parse_yaml_or_400(payload.yaml)
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


@router.delete(
    "/dsl-routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить YAML-маршрут",
    description="Удаляет файл маршрута. 404 если маршрут не существует.",
)
async def delete_dsl_route(route_id: str) -> Response:
    """Удалить маршрут."""
    store = _yaml_store()
    if not store.delete(route_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Маршрут {route_id!r} не найден",
        )
    _logger.info("dsl-routes: deleted %r", route_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/dsl-routes/validate",
    response_model=RouteValidationOut,
    summary="Валидация YAML без записи на диск",
    description=(
        "Парсит YAML и возвращает статус валидации. Используется UI-редактором "
        "для подсветки ошибок до сохранения."
    ),
)
async def validate_dsl_route(payload: YamlPayload = Body(...)) -> RouteValidationOut:
    """Валидация YAML без сохранения."""
    try:
        pipeline = load_pipeline_from_yaml(payload.yaml)
    except (ValueError, ImportError) as exc:
        return RouteValidationOut(valid=False, error=str(exc))
    return RouteValidationOut(
        valid=True,
        route_id=pipeline.route_id,
        processors_count=len(pipeline.processors),
    )


@router.post(
    "/dsl-routes/{route_id}/diff",
    response_model=RouteDiffOut,
    summary="Diff между сохранённым и предложенным YAML",
    description=(
        "Парсит переданный YAML и возвращает unified-diff с текущей версией "
        "маршрута из YAMLStore. 404 если маршрут не существует."
    ),
)
async def diff_dsl_route(
    route_id: str, payload: YamlPayload = Body(...)
) -> RouteDiffOut:
    """Diff между сохранённым YAML и переданным."""
    store = _yaml_store()
    if not store.exists(route_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Маршрут {route_id!r} не найден",
        )
    current = store.load(route_id)
    proposed = _parse_yaml_or_400(payload.yaml)
    return RouteDiffOut(route_id=route_id, diff=store.diff(current, proposed))
