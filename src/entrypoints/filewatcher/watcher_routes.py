"""REST API для управления файловыми наблюдателями.

Предоставляет endpoints для создания, удаления
и просмотра наблюдателей.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.entrypoints.filewatcher.watcher_manager import (
    WatcherSpec,
    watcher_manager,
)

__all__ = ("watcher_router",)

watcher_router = APIRouter(
    prefix="/watchers",
    tags=["File Watchers"],
)


class CreateWatcherRequest(BaseModel):
    """Запрос на создание наблюдателя."""

    directory: str = Field(description="Путь к директории.")
    pattern: str = Field(
        default="*", description="Glob-паттерн файлов."
    )
    route_id: str = Field(
        description="DSL-маршрут для обработки."
    )
    poll_interval: float = Field(
        default=5.0,
        ge=1.0,
        description="Интервал опроса (сек).",
    )


@watcher_router.post("/", summary="Создать наблюдатель")
async def create_watcher(
    body: CreateWatcherRequest,
) -> dict[str, Any]:
    """Создаёт и запускает файловый наблюдатель."""
    spec = WatcherSpec(
        directory=body.directory,
        pattern=body.pattern,
        route_id=body.route_id,
        poll_interval=body.poll_interval,
    )

    try:
        created = watcher_manager.add(spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "id": created.id,
        "directory": created.directory,
        "pattern": created.pattern,
        "route_id": created.route_id,
        "poll_interval": created.poll_interval,
    }


@watcher_router.delete(
    "/{watcher_id}", summary="Удалить наблюдатель"
)
async def delete_watcher(watcher_id: str) -> dict[str, str]:
    """Удаляет файловый наблюдатель."""
    try:
        watcher_manager.remove(watcher_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"status": "deleted", "id": watcher_id}


@watcher_router.get("/", summary="Список наблюдателей")
async def list_watchers() -> list[dict[str, Any]]:
    """Возвращает список активных наблюдателей."""
    return watcher_manager.list_watchers()
