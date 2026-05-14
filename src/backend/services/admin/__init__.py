"""Пакет ``services/admin`` — единая точка подключения sqladmin к FastAPI.

Реэкспортирует :func:`register_admin` из :mod:`sqladmin_setup` как тонкую
обёртку над уже существующим
:func:`src.backend.utilities.admin_panel.setup_admin`. Назначение пакета —
дать Sprint 7 Team T4 декларативную поверхность для подключения админ-панели
плагинов без вторжения в legacy-расположение ``utilities/admin_panel``.

Использование::

    from fastapi import FastAPI
    from src.backend.services.admin import register_admin

    app = FastAPI()
    register_admin(app)  # инициализирует sqladmin на /admin

Архитектурно ``services/admin`` относится к слою ``services/`` (S7 PLAN.md
§4 lines 632-633): здесь живёт фасад, в ``infrastructure`` — реальные
``ModelView`` через SQLAlchemy. Если необходимо подключить новые ModelView
из плагина, делайте это через :func:`register_admin(app, extra_views=[...])`.
"""

from __future__ import annotations

from src.backend.services.admin.sqladmin_setup import register_admin

__all__ = ("register_admin",)
