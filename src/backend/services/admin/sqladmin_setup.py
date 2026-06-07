"""sqladmin интеграция для FastAPI на маршруте ``/admin`` (Sprint 7 Team T4).

Тонкий фасад над существующим
:func:`src.backend.utilities.admin_panel.setup_admin.setup_admin` с поддержкой
дополнительных ``ModelView`` (плагины и core-сущности).

Назначение:
    * Дать единый ``register_admin(app, *, extra_views=...)``-API для всех
      инициализаций админ-панели (S7 PLAN.md §4 lines 632-633).
    * Сохранить ленивые импорты тяжёлых зависимостей (``sqladmin``,
      SQLAlchemy engine) — модуль безопасен к импорту из тест-окружения,
      где база отсутствует.
    * Не дублировать существующие ``UserAdmin``/``OrderAdmin``/
      ``OrderKindAdmin``/``FileAdmin``/``OrderFileAdmin`` — переиспользует их
      через legacy-обёртку.

Пример использования::

    from fastapi import FastAPI
    from src.backend.services.admin import register_admin

    app = FastAPI()
    register_admin(app)  # стандартный набор core-сущностей
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ("register_admin",)

_logger = get_logger("services.admin.sqladmin_setup")


def register_admin(
    app: FastAPI, *, extra_views: list[Any] | None = None
) -> object | None:
    """Регистрирует sqladmin на маршруте ``/admin``.

    Args:
        app: FastAPI-приложение, к которому подключается админ-панель.
        extra_views: Дополнительные ``ModelView``-классы (например, из
            плагинов). Если ``None`` — подключается только базовый набор
            из :mod:`src.backend.utilities.admin_panel`.

    Returns:
        Объект :class:`sqladmin.Admin` при успехе, либо ``None`` если
        sqladmin или зависимости БД недоступны (например, при импорте
        в unit-тестах без поднятой инфраструктуры).

    Note:
        Базовый ``setup_admin`` уже монтирует ``/admin``-маршрут на
        ``async_engine`` приложения. Этот фасад нужен прежде всего для
        расширения набора ``ModelView`` без правки legacy-кода.
    """
    try:
        from src.backend.utilities.admin_panel.setup_admin import setup_admin
    except Exception as exc:
        _logger.warning(
            "Не удалось подключить sqladmin (utilities.admin_panel): %s", exc
        )
        return None

    try:
        setup_admin(app=app)
    except Exception as exc:
        _logger.warning("setup_admin(...) упал: %s", exc)
        return None

    if not extra_views:
        return _find_admin_instance(app)

    admin_instance = _find_admin_instance(app)
    if admin_instance is None:
        _logger.debug(
            "Admin-instance не найден в app.state — extra_views (%d) пропущены",
            len(extra_views),
        )
        return None

    for view_cls in extra_views:
        try:
            admin_instance.add_view(view_cls)  # type: ignore[attr-defined]
        except Exception as exc:
            _logger.warning(
                "Не удалось зарегистрировать ModelView %r: %s", view_cls, exc
            )
    return admin_instance


def _find_admin_instance(app: FastAPI) -> object | None:
    """Ищет инстанс :class:`sqladmin.Admin` в ``app.state`` или ``app.routes``.

    sqladmin при монтировании сохраняет ссылку в ``app.state``/маршрутах
    под разными именами в зависимости от версии. Здесь — best-effort:
    при отсутствии возвращает ``None`` без исключений.
    """
    state = getattr(app, "state", None)
    if state is not None:
        for attr in ("admin", "_admin", "sqladmin"):
            value = getattr(state, attr, None)
            if value is not None:
                return value
    return None
