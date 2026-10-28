"""ADR-0372 — ``Settings.reload()`` и hot-reload конфигурации (cycle 172, CF2).

Класс дефекта (до фикса)
------------------------
``Settings.reload()`` НЕ СУЩЕСТВОВАЛ: корневой ``Settings`` — обычный
``pydantic_settings.BaseSettings``, а не ``BaseSettingsWithLoader``.
Hot-reload callback в ``lifecycle.py`` регистрировался, но
``getattr(settings, "reload", None)`` возвращал ``None`` → callback тихо
ничего не делал, а ``POST /api/v1/admin/config/reload`` отвечал
``{"succeeded": 1, "failed": []}`` — ложный успех.

Контракт после фикса
--------------------
* ``Settings.reload()`` существует и перечитывает все источники;
* вложенные Settings и модульные синглтоны обновляются **in-place**
  (ссылки потребителей не ломаются);
* YAML-кэш сбрасывается → новое значение из YAML реально подхватывается;
* ошибка отдельной модели не роняет reload (попадает в ``failed``);
* без зарегистрированных callback'ов hot-reload сообщает об ОШИБКЕ,
  а не о «успехе».
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.backend.core.config.config_loader import (
    BaseSettingsWithLoader,
    YamlConfigSettingsLoader,
    clear_yaml_cache,
    reload_settings,
)
from src.backend.core.config.hot_reload import ConfigHotReloader
from src.backend.core.config.profile import get_active_profile
from src.backend.core.config.settings import settings

_PROFILES_DIR: Path | None = None


class _ProbeSettings(BaseSettingsWithLoader):
    """Settings-класс, читающий YAML из временного каталога."""

    yaml_group: ClassVar[str] = "probe"
    model_config = SettingsConfigDict(env_prefix="PROBE_", extra="forbid")

    value: int = 0

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Подменяем только YAML-источник (файлы репозитория не трогаем)."""
        assert _PROFILES_DIR is not None
        sources = super().settings_customise_sources(
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
        return tuple(
            YamlConfigSettingsLoader(settings_cls, profiles_dir=_PROFILES_DIR)
            if type(source).__name__ == "YamlConfigSettingsLoader"
            else source
            for source in sources
        )


class _ProbeRoot(BaseSettings):
    """Корень-агрегатор для проверки ``reload_settings``."""

    probe: _ProbeSettings


def _write_profile(profiles_dir: Path, value: int) -> Path:
    """Записывает ``probe.value`` в overlay активного профиля."""
    path = profiles_dir / f"{get_active_profile().value}.yml"
    path.write_text(f"probe:\n  value: {value}\n")
    return path


@pytest.fixture
def profiles_dir(tmp_path: Path) -> Path:
    """Временный каталог с YAML-профилями (репозиторий не меняется)."""
    global _PROFILES_DIR

    directory = tmp_path / "config_profiles"
    directory.mkdir()
    (directory / "base.yml").write_text("probe:\n  value: 0\n")
    _write_profile(directory, 1)
    _PROFILES_DIR = directory
    clear_yaml_cache()
    yield directory
    clear_yaml_cache()
    _PROFILES_DIR = None


class TestSettingsReloadApi:
    """API ``Settings.reload()``."""

    def test_reload_exists_and_is_callable(self) -> None:
        """Метод ``reload()`` есть у корневого ``Settings``."""
        assert callable(getattr(settings, "reload", None))

    def test_reload_returns_report(self) -> None:
        """``reload()`` возвращает отчёт ``reloaded``/``failed``."""
        report = settings.reload()
        assert set(report) == {"reloaded", "failed"}
        assert isinstance(report["reloaded"], list)
        assert isinstance(report["failed"], list)

    def test_reload_keeps_nested_object_identity(self) -> None:
        """Вложенные объекты обновляются in-place (ссылки не ломаются)."""
        app_before = settings.app
        settings.reload()
        assert settings.app is app_before

    def test_reload_updates_module_singletons(self) -> None:
        """Модульные синглтоны (например ``app_base_settings``) тоже обновляются."""
        from src.backend.core.config.base import app_base_settings

        before = app_base_settings
        settings.reload()
        assert app_base_settings is before
        assert app_base_settings.host == settings.app.host

    def test_reload_reports_failed_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ошибка одной модели не роняет reload — она попадает в ``failed``."""
        from src.backend.core.config import config_loader as cl

        class _BrokenSettings(BaseSettingsWithLoader):
            """Модель, которая не собирается."""

            yaml_group: ClassVar[str] = "broken"

            def __init__(self, **kwargs: Any) -> None:
                raise RuntimeError("broken settings")

        monkeypatch.setattr(
            cl,
            "_iter_settings_singletons",
            lambda: iter(
                [
                    (
                        "broken.module",
                        "broken_settings",
                        _BrokenSettings.__new__(_BrokenSettings),
                    )
                ]
            ),
        )
        report = reload_settings(settings)
        assert any("broken.module" in item["name"] for item in report["failed"])
        assert any("broken settings" in item["error"] for item in report["failed"])


class TestHotReloadEffect:
    """Hot-reload реально подхватывает изменение YAML (tmp-каталог)."""

    def test_reload_picks_up_yaml_change(self, profiles_dir: Path) -> None:
        """Изменённый YAML подхватывается при reload (кэш сброшен)."""
        probe = _ProbeSettings()
        root = _ProbeRoot(probe=probe)
        assert probe.value == 1

        _write_profile(profiles_dir, 42)
        report = reload_settings(root)

        assert report["failed"] == []
        assert probe.value == 42, "Новое значение из YAML должно быть применено"
        assert root.probe is probe, "Вложенный объект обновляется in-place"

    @pytest.mark.asyncio
    async def test_hot_reloader_triggers_reload(self, profiles_dir: Path) -> None:
        """``ConfigHotReloader`` реально перечитывает YAML (а не «делает вид»)."""
        probe = _ProbeSettings()
        root = _ProbeRoot(probe=probe)

        _write_profile(profiles_dir, 7)

        reloader = ConfigHotReloader()

        def _reload() -> None:
            reload_settings(root)

        reloader.on_reload(_reload)
        report = await reloader.trigger_reload(reason="test")

        assert report["succeeded"] == 1
        assert report["failed"] == []
        assert probe.value == 7

    @pytest.mark.asyncio
    async def test_trigger_reload_without_callbacks_is_failure(self) -> None:
        """Без callback'ов hot-reload сообщает об ошибке, а не об успехе."""
        reloader = ConfigHotReloader()
        report = await reloader.trigger_reload(reason="test")
        assert report["succeeded"] == 0
        assert report["failed"], "Отсутствие callback'ов — это ошибка, не успех"
        assert report["ok"] is False

    def test_yaml_cache_is_refreshed_on_reload(self, profiles_dir: Path) -> None:
        """После reload YAML-кэш содержит НОВОЕ значение (кэш не устарел)."""
        from src.backend.core.config import config_loader as cl

        _ProbeSettings()
        profile = get_active_profile().value
        _write_profile(profiles_dir, 99)

        reload_settings(_ProbeRoot(probe=_ProbeSettings()))

        cached = cl._read_overlay_yaml_cached(profiles_dir, profile)
        assert cached["probe"]["value"] == 99


class TestLifecycleWiring:
    """Lifespan регистрирует рабочий callback (а не «пустышку»)."""

    @pytest.mark.asyncio
    async def test_callback_reloads_settings(self) -> None:
        """Callback вызывает ``settings.reload()`` (реальная перезагрузка)."""
        from src.backend.core.config.hot_reload import register_settings_reload_callback

        reloader = ConfigHotReloader()
        register_settings_reload_callback(reloader)

        assert len(reloader._callbacks) == 1
        report = await reloader.trigger_reload(reason="test")
        assert report["succeeded"] == 1
        assert report["failed"] == []

    @pytest.mark.asyncio
    async def test_callback_fails_without_reload_method(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если ``settings.reload`` недоступен — это ОШИБКА, а не успех."""
        from src.backend.core.config import settings as settings_mod
        from src.backend.core.config.hot_reload import register_settings_reload_callback

        class _FakeSettings:
            """Настройки без метода ``reload``."""

        monkeypatch.setattr(settings_mod, "settings", _FakeSettings())

        reloader = ConfigHotReloader()
        register_settings_reload_callback(reloader)

        report = await reloader.trigger_reload(reason="test")
        assert report["succeeded"] == 0
        assert report["failed"], "Отсутствие settings.reload() должно быть ошибкой"
        assert "reload" in report["failed"][0]["error"].lower()


class TestWatcherPaths:
    """Пути watcher'а — абсолютные (не зависят от CWD)."""

    def test_watch_makes_path_absolute(self) -> None:
        """``watch()`` приводит путь к абсолютному."""
        reloader = ConfigHotReloader()
        reloader.watch("config_profiles")
        assert all(path.is_absolute() for path in reloader._paths)

    def test_lifecycle_watches_repo_root(self) -> None:
        """Lifespan смотрит на каталог профилей в корне репозитория."""
        from src.backend.core.config.config_loader import repo_root

        root = repo_root()
        assert (root / "config_profiles").is_dir()
        assert root.is_absolute()
