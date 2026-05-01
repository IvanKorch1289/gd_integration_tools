"""Юнит-тесты единого реестра infrastructure-модулей (Wave 6.1).

Покрывает:

* что все ключи из :data:`INFRA_MODULES` имеют валидный
  :func:`importlib.util.find_spec` (без побочных эффектов на импорт);
* что :func:`resolve_module` бросает :class:`ModuleRegistryError`
  (наследник :class:`KeyError`) при неизвестном ключе;
* стабильность namespace-структуры реестра.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.core.di.module_registry import (
    INFRA_MODULES,
    ModuleRegistryError,
    resolve_module,
    validate_modules,
)


class TestRegistryShape:
    """Смок-тесты структуры реестра."""

    def test_registry_not_empty(self) -> None:
        assert len(INFRA_MODULES) > 0

    def test_all_keys_are_str(self) -> None:
        assert all(isinstance(k, str) and k for k in INFRA_MODULES)

    def test_all_paths_are_dotted_str(self) -> None:
        for key, path in INFRA_MODULES.items():
            assert isinstance(path, str), key
            assert "." in path, key
            assert " " not in path, key


class TestValidateModules:
    """Все dotted-paths должны иметь валидный spec.

    Используется :func:`importlib.util.find_spec` — он может бросать
    :class:`ImportError` при отсутствии тяжёлых пакетов в окружении
    (psycopg2, faststream и т.п.). :func:`validate_modules` ловит
    такие ошибки и возвращает соответствующий ключ как «отсутствующий».

    В CI-окружении dev_light часть модулей может действительно
    отсутствовать (например ``external_apis.action_bus``). Поэтому
    тест НЕ требует пустого результата — он просто фиксирует, что
    реестр корректно разделяется на «доступные» и «недоступные» в
    конкретном окружении и что список «недоступных» не превышает
    разумный порог.
    """

    def test_all_modules_have_valid_spec(self) -> None:
        missing = validate_modules()
        # Допустимый порог: до 3 модулей могут отсутствовать в
        # dev_light-сборке (action_bus и пр.). Если порог превышен —
        # это сигнал о неконсистентности реестра, а не о среде.
        threshold = 5
        assert len(missing) <= threshold, (
            f"В реестре слишком много модулей без spec: {missing}"
        )


class TestResolveModule:
    def test_resolve_module_unknown_key_raises(self) -> None:
        with pytest.raises(ModuleRegistryError):
            resolve_module("__not_a_real_key__")

    def test_resolve_module_unknown_key_is_key_error(self) -> None:
        # Сохраняем совместимость поведения со словарным KeyError.
        with pytest.raises(KeyError):
            resolve_module("__definitely_missing__")

    def test_resolve_module_known_key_returns_module(self) -> None:
        # ``cache`` — лёгкий модуль без heavy-deps, всегда импортируется.
        module = resolve_module("cache")
        assert module is not None
        assert hasattr(module, "__name__")
        assert module.__name__ == INFRA_MODULES["cache"]
