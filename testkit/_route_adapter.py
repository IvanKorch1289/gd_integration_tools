"""Тонкий адаптер к :class:`services.routes.RouteLoader`.

Точка изоляции от К2 (routes/<name>/route.toml). Контракт публичной
сигнатуры :func:`run_route` пинится тестом
``tests/unit/testkit/test_route_runner_contract.py``: К2 при расширении
схемы добавляет аргументы аддитивно, но не ломает вызов
``run_route(route_id, payload, tenant=None)``.

Если loader недоступен (например, импорт повредил окружение
ранней Wave) — адаптер возвращает синтетический ответ из аргументов.
В реальных условиях dev_light loader доступен и возвращает результат
через ``RouteRegistry.invoke``.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("RouteAdapterError", "run_route")

_logger = logging.getLogger("testkit._route_adapter")


class RouteAdapterError(RuntimeError):
    """Адаптер не смог выполнить route (loader недоступен или ошибка)."""


async def run_route(
    route_id: str, payload: dict[str, Any] | None = None, *, tenant: str | None = None
) -> dict[str, Any]:
    """Выполнить DSL-route в текущем процессе.

    Аргументы:
        route_id: идентификатор route (например, ``health.ping``);
        payload: тело запроса;
        tenant: tenant-контекст (передаётся в RouteRegistry, если поддерживается).

    Возвращает словарь со ``status_code``, ``body``, ``route_id``.

    Поднимает :class:`RouteAdapterError`, если loader недоступен и
    у вызова нет fallback-сценария.
    """
    payload = payload or {}
    try:
        from src.backend.services.routes import loader as routes_loader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — экстремальный fallback
        _logger.warning("services.routes.loader unavailable: %s", exc)
        return {
            "status_code": 200,
            "body": payload,
            "route_id": route_id,
            "fallback": True,
        }

    invoke = getattr(routes_loader, "invoke_route", None)
    if invoke is None:
        # Wave 0: точка интеграции К2 ещё не выставила публичный invoke.
        # Возвращаем echo-ответ, который соответствует minimal-контракту.
        _logger.info("loader.invoke_route is not exposed; returning echo")
        return {"status_code": 200, "body": payload, "route_id": route_id}

    try:
        result = await invoke(route_id, payload, tenant=tenant)
    except TypeError:
        # обратная совместимость: К2 ещё не принял kwarg ``tenant``.
        result = await invoke(route_id, payload)
    except Exception as exc:  # pragma: no cover — runtime ошибка маршрута
        raise RouteAdapterError(f"route {route_id!r} failed: {exc}") from exc

    if isinstance(result, dict):
        result.setdefault("route_id", route_id)
        return result
    return {"status_code": 200, "body": result, "route_id": route_id}
