"""Smoke-тесты для :mod:`src.backend.services.admin.sqladmin_setup`.

Проверяют что:
    * модуль импортируется без побочных эффектов;
    * :func:`register_admin` доступен и не падает при отсутствующей БД;
    * :func:`register_admin` корректно деградирует при сбое legacy-setup.

Стратегия:
    Legacy-модуль ``src.backend.utilities.admin_panel.setup_admin`` при
    реальном импорте тянет SQLAlchemy-engine и Pydantic-settings, что в
    unit-окружении (без полноценного ``.env``) падает с ValidationError.
    Поэтому каждый тест подменяет ``sys.modules['...setup_admin']`` на
    лёгкий stub ДО первого вызова :func:`register_admin`.
"""
# ruff: noqa: S101

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock


def _install_stub_legacy(setup_fn: object) -> None:
    """Подменяет legacy ``setup_admin`` модуль на легковесный stub.

    Это позволяет тестировать :func:`register_admin` без реальной
    инициализации SQLAlchemy/Pydantic-settings.
    """
    stub = types.ModuleType("src.backend.utilities.admin_panel.setup_admin")
    stub.setup_admin = setup_fn  # type: ignore[attr-defined]
    sys.modules["src.backend.utilities.admin_panel.setup_admin"] = stub


def test_admin_package_importable() -> None:
    """Пакет :mod:`services.admin` импортируется и реэкспортирует ``register_admin``."""
    module = importlib.import_module("src.backend.services.admin")
    assert hasattr(module, "register_admin"), "register_admin должен быть экспортирован"


def test_sqladmin_setup_module_importable() -> None:
    """Модуль :mod:`services.admin.sqladmin_setup` импортируется без БД."""
    module = importlib.import_module("src.backend.services.admin.sqladmin_setup")
    assert callable(module.register_admin)


def test_register_admin_returns_none_when_legacy_fails() -> None:
    """register_admin возвращает ``None``, если legacy ``setup_admin`` падает.

    Сценарий: backend-инфраструктура (БД, async_engine) недоступна —
    функция не должна поднимать исключение, а вернуть ``None`` для
    graceful-degradation в dev_light/тест-режимах.
    """

    def _raising_setup(*, app: object) -> None:  # noqa: ARG001
        raise RuntimeError("DB unavailable")

    _install_stub_legacy(_raising_setup)
    fake_app = MagicMock(name="FakeFastAPI")

    from src.backend.services.admin.sqladmin_setup import register_admin

    result = register_admin(fake_app)
    assert result is None


def test_register_admin_calls_legacy_setup() -> None:
    """register_admin вызывает legacy ``setup_admin(app)`` ровно один раз."""
    mock_setup = MagicMock(name="setup_admin", return_value=None)
    _install_stub_legacy(mock_setup)

    fake_app = MagicMock(name="FakeFastAPI")
    fake_app.state = MagicMock()
    fake_app.state.admin = None  # эмулируем отсутствие admin в state

    from src.backend.services.admin.sqladmin_setup import register_admin

    register_admin(fake_app)
    mock_setup.assert_called_once_with(app=fake_app)


def test_register_admin_attaches_extra_views_when_admin_present() -> None:
    """extra_views регистрируются через ``admin.add_view`` при наличии instance."""
    mock_admin = MagicMock(name="AdminInstance")

    def _setup(*, app: object) -> None:
        # эмулируем поведение sqladmin: помещает instance в app.state.admin
        app.state.admin = mock_admin  # type: ignore[attr-defined]

    _install_stub_legacy(_setup)

    fake_app = MagicMock(name="FakeFastAPI")
    fake_app.state = MagicMock()
    fake_app.state.admin = None

    extra_view = MagicMock(name="ExtraView")
    from src.backend.services.admin.sqladmin_setup import register_admin

    result = register_admin(fake_app, extra_views=[extra_view])
    assert result is mock_admin
    mock_admin.add_view.assert_called_once_with(extra_view)
