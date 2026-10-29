"""ADR-0390 (волна 18, кластер G1) — env-override ``DSL_ALLOWED_PATHS``.

Регрессия: ``DSL_ALLOWED_PATHS`` — документированный override поверх YAML-профиля
(ADR-0358 §2), но pydantic-settings для ``list[str]`` требует JSON. Значение
``/data/uploads:/tmp/dsl`` роняло сборку Settings:

``SettingsError: error parsing value for field "allowed_paths"``

Приложение не стартовало (терялись audit-события). Теперь env-строка
разбирается собственным парсером (разделитель ``:``).
"""

from __future__ import annotations

import pytest

from src.backend.core.config.dsl import DSLSettings


def test_env_allowed_paths_with_colon_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env-строка с разделителем ``:`` собирает Settings (без SettingsError)."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", "/data/uploads:/tmp/dsl")

    settings = DSLSettings()

    assert settings.allowed_paths == ["/data/uploads", "/tmp/dsl"]


def test_env_allowed_paths_overrides_yaml_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env-override приоритетнее YAML-профиля (ADR-0358 §2)."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", "/only/env")

    settings = DSLSettings()

    assert settings.allowed_paths == ["/only/env"]


def test_env_allowed_paths_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одно значение без разделителя — валидный список из одного элемента."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", "/single/path")

    settings = DSLSettings()

    assert settings.allowed_paths == ["/single/path"]


def test_env_allowed_paths_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробелы вокруг элементов не попадают в allowlist."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", " /a : /b ")

    settings = DSLSettings()

    assert settings.allowed_paths == ["/a", "/b"]


def test_yaml_list_still_works_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без env-override YAML-профиль (список) применяется как раньше."""
    monkeypatch.delenv("DSL_ALLOWED_PATHS", raising=False)

    settings = DSLSettings()

    assert isinstance(settings.allowed_paths, list)
    assert all(isinstance(p, str) for p in settings.allowed_paths)
    assert settings.allowed_paths


def test_settings_package_imports_with_env_override() -> None:
    """Свежий старт приложения с env-override не падает (интеграционный).

    Проверяется в подпроцессе: singleton-настройки собираются при первом
    импорте, поэтому переиспользовать уже импортированный модуль нельзя.
    """
    import os
    import subprocess
    import sys

    env = {**os.environ, "DSL_ALLOWED_PATHS": "/data/uploads:/tmp/dsl"}
    code = (
        "from src.backend.core.config.settings import settings;"
        "print(settings.dsl.allowed_paths)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "/data/uploads" in result.stdout
    assert "/tmp/dsl" in result.stdout
