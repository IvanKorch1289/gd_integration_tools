"""Тесты shim'а ``FileService`` после инверсии слоёв (ADR-0457).

Контракт:
* ``src.backend.services.io.files`` не импортирует ``extensions.*`` напрямую —
  ресурс берётся из core-реестра (``get_extension_resource``);
* ``FileService`` — тот же класс, что в расширении (identity);
* ``get_file_service`` — тот же геттер, что отдаёт расширение (→ тот же
  инстанс-синглтон);
* обращение к атрибуту выдаёт ``DeprecationWarning`` (и сам импорт shim'а —
  legacy-контракт предупреждения об устаревании).
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import Any

import pytest

from extensions.core_entities.files.services import files as ext_files

_SHIM_MODULE = "src.backend.services.io.files"


@pytest.fixture()
def _isolated_file_service(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Изолирует синглтон сервиса файлов и подменяет провайдер репозитория.

    Ключ ``repos.files`` в DI-реестре не существует (S102 P2-11) — сервис
    создаётся только с тестовым override'ом репозитория.
    """
    from src.backend.core.di.providers import db

    monkeypatch.setattr(db, "_overrides", {**db._overrides, "file_repo": object()})
    monkeypatch.setattr(ext_files, "_file_service_instance", None)


def test_shim_file_service_is_extension_class() -> None:
    """``FileService`` из shim'а — тот же объект, что в расширении."""
    from src.backend.services.io.files import FileService as shim_file_service

    assert shim_file_service is ext_files.FileService


def test_shim_get_file_service_is_extension_getter() -> None:
    """Геттер сервиса — тот же callable, что отдаёт расширение."""
    from src.backend.services.io.files import get_file_service as shim_getter

    assert shim_getter is ext_files.get_file_service


def test_shim_get_file_service_returns_same_singleton(
    _isolated_file_service: None,
) -> None:
    """Вызов геттера из shim'а даёт тот же синглтон, что у расширения."""
    from src.backend.services.io.files import get_file_service as shim_getter

    instance = shim_getter()
    assert instance is ext_files.get_file_service()
    assert isinstance(instance, ext_files.FileService)


def test_shim_emits_deprecation_warning_on_attribute_access() -> None:
    """Обращение к атрибуту shim'а выдаёт ``DeprecationWarning``."""
    module = importlib.import_module(_SHIM_MODULE)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert module.FileService is ext_files.FileService
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations
    assert "files" in str(deprecations[0].message)


def test_shim_import_also_emits_deprecation_warning() -> None:
    """Импорт shim'а тоже сигналит об устаревании (legacy-контракт)."""
    sys.modules.pop(_SHIM_MODULE, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module(_SHIM_MODULE)
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations
    assert "files" in str(deprecations[0].message).lower()


def test_shim_unknown_attribute_raises() -> None:
    """Неизвестный атрибут → ``AttributeError``."""
    module = importlib.import_module(_SHIM_MODULE)
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(module, "unknown_attribute")


def test_shim_public_surface_preserved() -> None:
    """Публичная поверхность shim'а не изменилась."""
    module = importlib.import_module(_SHIM_MODULE)
    assert module.__all__ == ("FileService", "get_file_service")
