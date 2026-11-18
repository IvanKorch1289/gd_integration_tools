"""Подключение sqladmin-панели к FastAPI (ADR-0457 — инверсия ``src/ → extensions``).

ModelView-классы расширений **не импортируются статически**: расширения
регистрируют их в core-реестре ресурсов
(:mod:`src.backend.core.extension_registry`), а потребитель забирает по
ключу ``(domain, "admin", name)``.

Раньше здесь стояли четыре прямых импорта ``extensions.core_entities.*`` —
нарушение слоёв, которое не виделось гейту ``tools/check_layers.py``
(каталог ``src/backend/utilities/**`` вне матрицы слоёв).

Использование::

    setup_admin(app)  # монтирует /admin и регистрирует 5 views
"""

from __future__ import annotations

from fastapi import FastAPI
from sqladmin import Admin

from src.backend.core.extension_registry import get_extension_resource
from src.backend.infrastructure.database.database import get_db_initializer

__all__ = ("setup_admin",)


def setup_admin(app: FastAPI) -> None:
    """Подключить sqladmin к FastAPI app: регистрация 5 views.

    Регистрирует ``UserAdmin``, ``OrderAdmin``, ``OrderKindAdmin``,
    ``OrderFileAdmin``, ``FileAdmin``. Классы берутся из core-реестра
    ресурсов расширений (ADR-0457), engine — из
    :func:`get_db_initializer` (per-app singleton).

    Args:
        app: FastAPI app instance.

    Raises:
        KeyError: Расширение не зарегистрировало admin-ресурс (fail-closed:
            панель без части views хуже, чем явная ошибка на старте).

    """
    admin = Admin(app, get_db_initializer().async_engine)
    admin.add_view(get_extension_resource("users", "admin", "user"))
    admin.add_view(get_extension_resource("orders", "admin", "order"))
    admin.add_view(get_extension_resource("orderkinds", "admin", "orderkind"))
    admin.add_view(get_extension_resource("files", "admin", "order_file"))
    admin.add_view(get_extension_resource("files", "admin", "file"))
