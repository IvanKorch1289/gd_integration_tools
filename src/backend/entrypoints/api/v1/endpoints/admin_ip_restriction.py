"""Admin endpoints для управления IP-ограничениями.

Позволяют runtime обновлять глобальные и per-route IP-правила без
рестарта приложения, а также вручную перезагружать конфиг из YAML-файла.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.backend.core.config.config_loader import _resolve_repo_root
from src.backend.core.security.ip_restriction_store import get_ip_restriction_store

__all__ = ("router",)


router = APIRouter(prefix="/ip-restriction", tags=["Admin · IP Restriction"])


class _AdminIPRestrictionSchema(BaseModel):
    """Схема обновления глобальных admin IP-ограничений."""

    admin_ips: list[str] = Field(
        default_factory=list,
        description="Разрешённые IP-адреса и CIDR (например, 192.168.1.0/24).",
    )
    admin_routes: list[str] = Field(
        default_factory=list,
        description="Glob-паттерны административных маршрутов (например, /admin/*).",
    )


class _RouteIPRestrictionSchema(BaseModel):
    """Схема per-route IP-ограничения."""

    allowed_ips: list[str] = Field(
        default_factory=list, description="Разрешённые IP/CIDR для маршрута."
    )
    enabled: bool = Field(default=True, description="Включено ли правило.")


_DEFAULT_CONFIG_PATH: Path = _resolve_repo_root() / "config" / "ip_restriction.yaml"


@router.get(
    "",
    summary="Текущие IP-ограничения",
    description="Возвращает snapshot глобальных и per-route IP-правил.",
)
async def _get_ip_restrictions() -> dict[str, Any]:
    return get_ip_restriction_store().snapshot()


@router.put(
    "",
    summary="Обновить глобальные IP-ограничения",
    description=(
        "Runtime-обновление admin_ips и admin_routes. "
        "Изменения применяются без рестарта приложения."
    ),
)
async def _put_ip_restrictions(body: _AdminIPRestrictionSchema) -> dict[str, Any]:
    get_ip_restriction_store().update_admin(
        admin_ips=set(body.admin_ips), admin_routes=body.admin_routes
    )
    return {"status": "ok"}


@router.put(
    "/routes/{path_pattern:path}",
    summary="Установить per-route IP-ограничение",
    description="Добавляет/обновляет правило для конкретного path-pattern.",
)
async def _put_route_rule(
    path_pattern: str, body: _RouteIPRestrictionSchema
) -> dict[str, str]:
    get_ip_restriction_store().set_route_rule(
        path_pattern=path_pattern, allowed_ips=body.allowed_ips, enabled=body.enabled
    )
    return {"status": "ok"}


@router.delete(
    "/routes/{path_pattern:path}", summary="Удалить per-route IP-ограничение"
)
async def _delete_route_rule(path_pattern: str) -> dict[str, str]:
    get_ip_restriction_store().remove_route_rule(path_pattern)
    return {"status": "ok"}


@router.post(
    "/reload",
    summary="Перезагрузить IP-ограничения из YAML",
    description=(
        "Читает config/ip_restriction.yaml (если существует) и обновляет "
        "глобальные + per-route правила."
    ),
)
async def _reload_ip_restrictions() -> dict[str, Any]:
    loaded = get_ip_restriction_store().reload_from_yaml(_DEFAULT_CONFIG_PATH)
    return {"loaded": loaded, "snapshot": get_ip_restriction_store().snapshot()}
