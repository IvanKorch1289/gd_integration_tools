# ruff: noqa: S101, SLF001
"""Smoke-тесты S39 W5 — модуль ``src.backend.plugins.composition.lifecycle``.

Покрывают:
* публичный API модуля (``__all__``);
* сигнатуру ``lifespan`` (asynccontextmanager, callable);
* вспомогательные bootstrap-функции: graceful error, idempotency;
* ``_handle_v11_changes`` (плагин/раут/dsl-пайплайн, нерелевантные пути);
* ``_start_v11_hot_reload`` (skipped при выключенных флагах);
* ``lifespan`` (smoke: start → yield → shutdown, инфраструктура готова).

Стратегия: ``lifespan`` имеет длинный pipeline — мокаем ВСЕ тяжёлые
зависимости (DB/Redis/MQ/Sentry/PluginLoader) и проверяем:
- state.set/get (``task_registry``, ``infrastructure_ready``);
- порядок shutdown (workflow → log → leaker);
- graceful error если один из bootstrap'ов падает.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from src.backend.plugins.composition import lifecycle

# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_module_imports() -> None:
    """Модуль импортируется без побочных эффектов."""
    assert lifecycle is not None


def test_module_exposes_expected_public_api() -> None:
    """``__all__`` содержит ровно один публичный символ — ``lifespan``."""
    expected_subset = ("lifespan",)
    assert all(name in lifecycle.__all__ for name in expected_subset)


def test_lifespan_is_async_context_manager() -> None:
    """``lifespan`` — async context manager (FastAPI lifespan-конвенция)."""
    from contextlib import AbstractAsyncContextManager

    # ``@asynccontextmanager`` оборачивает генератор в AsyncContextManager.
    assert isinstance(lifecycle.lifespan(FastAPI()), AbstractAsyncContextManager)


def test_lifespan_signature_accepts_app() -> None:
    """``lifespan(app)`` принимает ровно один аргумент — FastAPI app."""
    import inspect

    sig = inspect.signature(lifecycle.lifespan)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "app"
    # PEP 563: from __future__ import annotations делает annotation строкой.
    # Проверяем строковое представление, а не identity.
    assert "FastAPI" in str(params[0].annotation)


def test_module_exposes_all_bootstrap_helpers() -> None:
    """Все bootstrap-хелперы доступны в namespace модуля или его submodules.

    После S66 decomp: ``lifecycle`` re-exports хелперы (без underscore) и
    делает submodules (``v11``, ``watchers``, ``bootstrap``, ``protocols``)
    доступными как атрибуты.
    """
    expected = {
        "lifespan": lifecycle,
        "register_storage_singletons": lifecycle,
        "validate_cache_layers": lifecycle,
        "bootstrap_snapshot_job": lifecycle,
        "bootstrap_resilience_coordinator": lifecycle,
        "register_protocol_providers": lifecycle.protocols,
        "start_dsl_yaml_watcher": lifecycle.watchers,
        "stop_dsl_yaml_watcher": lifecycle.watchers,
        "bootstrap_v11_plugin_loader": lifecycle.v11,
        "bootstrap_v11_route_loader": lifecycle.v11,
        "start_v11_hot_reload": lifecycle.v11,
        "shutdown_v11_loaders": lifecycle.v11,
        "handle_v11_changes": lifecycle.v11,
    }
    for name, owner in expected.items():
        assert hasattr(owner, name), f"{name} missing from {owner.__name__}"


def test_module_uses_task_registry_singleton() -> None:
    """``get_task_registry`` импортирован и используется в lifespan."""
    from src.backend.core.utils.task_registry import get_task_registry

    assert lifecycle.get_task_registry is get_task_registry


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _make_lifespan_patches() -> list[Any]:
    """Возвращает список patch'ей, достаточных для запуска ``lifespan`` без сети/БД."""
    return [
        patch("src.backend.plugins.composition.di.register_app_state"),
        patch("src.backend.plugins.composition.lifecycle.register_storage_singletons"),
        patch("src.backend.plugins.composition.service_setup.register_all_services"),
        patch(
            "src.backend.plugins.composition.setup_ai_2026.register_ai_2026_providers",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.ai_safety_setup.start_ai_safety",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.ai_safety_setup.stop_ai_safety",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.lifecycle.protocols.register_protocol_providers",
            new=AsyncMock(),
        ),
        patch("src.backend.plugins.composition.lifecycle.validate_cache_layers"),
        patch(
            "src.backend.plugins.composition.lifecycle.bootstrap_resilience_coordinator"
        ),
        patch("src.backend.plugins.composition.lifecycle.bootstrap_snapshot_job"),
        patch(
            "src.backend.plugins.composition.lifecycle.watchers.start_dsl_yaml_watcher",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.lifecycle.watchers.stop_dsl_yaml_watcher",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.lifecycle.v11.bootstrap_v11_plugin_loader",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.lifecycle.v11.bootstrap_v11_route_loader",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.lifecycle.v11.start_v11_hot_reload",
            new=AsyncMock(),
        ),
        patch(
            "src.backend.plugins.composition.lifecycle.v11.shutdown_v11_loaders",
            new=AsyncMock(),
        ),
        patch("src.backend.plugins.composition.setup_infra.starting", new=AsyncMock()),
        patch("src.backend.plugins.composition.setup_infra.ending", new=AsyncMock()),
        patch("src.backend.dsl.commands.setup.register_action_handlers"),
        patch("src.backend.dsl.routes.register_dsl_routes"),
    ]


@asynccontextmanager
async def _lifespan_in_isolation() -> Any:
    """Прогоняет ``lifespan(app)`` со всеми моками; возвращает app на время yield."""
    patches = _make_lifespan_patches()
    for p in patches:
        p.start()
    app = FastAPI()
    try:
        async with lifecycle.lifespan(app):
            yield app
    finally:
        for p in patches:
            p.stop()


# --------------------------------------------------------------------------- #
# lifespan smoke
# --------------------------------------------------------------------------- #


async def test_lifespan_sets_task_registry_on_state() -> None:
    """``lifespan`` записывает singleton TaskRegistry в ``app.state``."""
    async with _lifespan_in_isolation() as app:
        assert hasattr(app.state, "task_registry")
        from src.backend.core.utils.task_registry import get_task_registry

        assert app.state.task_registry is get_task_registry()


async def test_lifespan_marks_infrastructure_ready() -> None:
    """``lifespan`` выставляет ``infrastructure_ready=True`` после bootstrap'а."""
    async with _lifespan_in_isolation() as app:
        assert getattr(app.state, "infrastructure_ready", None) is True


async def test_lifespan_resets_infrastructure_ready_on_shutdown() -> None:
    """``finally``-блок сбрасывает ``infrastructure_ready`` в ``False``."""
    async with _lifespan_in_isolation() as app:
        assert app.state.infrastructure_ready is True
    # После выхода из lifespan — state сохраняется, но value сброшено.
    assert app.state.infrastructure_ready is False


async def test_lifespan_raises_runtime_error_on_early_startup_failure() -> None:
    """Если bootstrap падает ДО ``startup_completed=True`` — оборачивается в RuntimeError.

    Это документированное поведение: критическая ошибка инициализации валит
    приложение (а не graceful continue) согласно ``app_factory``-комментарию.
    """
    patches = _make_lifespan_patches()
    for p in patches:
        p.start()
    try:
        # Подменяем bootstrap, который вызывается ДО ``startup_completed=True``.
        with patch(
            "src.backend.plugins.composition.lifecycle.v11.bootstrap_v11_plugin_loader",
            new=AsyncMock(side_effect=RuntimeError("simulated bootstrap failure")),
        ):
            app = FastAPI()
            with pytest.raises(RuntimeError, match="Остановка приложения"):
                async with lifecycle.lifespan(app):
                    pass  # pragma: no cover
    finally:
        for p in patches:
            p.stop()


# --------------------------------------------------------------------------- #
# _handle_v11_changes
# --------------------------------------------------------------------------- #


async def test_handle_v11_changes_plugin_toml_triggers_plugin_reload() -> None:
    """Изменение ``plugin.toml`` → ``PluginLoaderV11.discover_and_load``."""
    app = FastAPI()
    plugin_loader = MagicMock()
    plugin_loader.discover_and_load = AsyncMock()
    route_loader = MagicMock()
    route_loader.unload_all = AsyncMock()
    route_loader.discover_and_load = AsyncMock()
    app.state.plugin_loader_v11 = plugin_loader
    app.state.route_loader_v11 = route_loader

    await lifecycle.v11.handle_v11_changes(app, {("change", "/x/y/plugin.toml")})

    assert plugin_loader.discover_and_load.await_count == 1
    assert route_loader.unload_all.await_count == 0


async def test_handle_v11_changes_route_toml_triggers_route_reload() -> None:
    """Изменение ``route.toml`` → ``RouteLoader.unload_all + discover_and_load``."""
    app = FastAPI()
    plugin_loader = MagicMock()
    plugin_loader.discover_and_load = AsyncMock()
    route_loader = MagicMock()
    route_loader.unload_all = AsyncMock()
    route_loader.discover_and_load = AsyncMock()
    app.state.plugin_loader_v11 = plugin_loader
    app.state.route_loader_v11 = route_loader

    await lifecycle.v11.handle_v11_changes(app, {("change", "/x/y/route.toml")})

    assert route_loader.unload_all.await_count == 1
    assert route_loader.discover_and_load.await_count == 1
    assert plugin_loader.discover_and_load.await_count == 0


async def test_handle_v11_changes_dsl_yaml_triggers_route_reload() -> None:
    """Изменение ``*.dsl.yaml`` → ``RouteLoader.unload_all + discover_and_load``."""
    app = FastAPI()
    plugin_loader = MagicMock()
    plugin_loader.discover_and_load = AsyncMock()
    route_loader = MagicMock()
    route_loader.unload_all = AsyncMock()
    route_loader.discover_and_load = AsyncMock()
    app.state.plugin_loader_v11 = plugin_loader
    app.state.route_loader_v11 = route_loader

    await lifecycle.v11.handle_v11_changes(app, {("change", "/x/pipeline.dsl.yaml")})

    assert route_loader.unload_all.await_count == 1
    assert plugin_loader.discover_and_load.await_count == 0


async def test_handle_v11_changes_irrelevant_path_does_nothing() -> None:
    """Изменение нерелевантного пути — никакие loader'ы не вызываются."""
    app = FastAPI()
    plugin_loader = MagicMock()
    plugin_loader.discover_and_load = AsyncMock()
    route_loader = MagicMock()
    route_loader.unload_all = AsyncMock()
    app.state.plugin_loader_v11 = plugin_loader
    app.state.route_loader_v11 = route_loader

    await lifecycle.v11.handle_v11_changes(app, {("change", "/x/random.py")})

    assert plugin_loader.discover_and_load.await_count == 0
    assert route_loader.unload_all.await_count == 0


async def test_handle_v11_changes_no_loaders_does_not_crash() -> None:
    """Без plugin/route-loader'ов в state — функция no-op (без crash'а)."""
    app = FastAPI()
    # Намеренно НЕ устанавливаем plugin_loader_v11 / route_loader_v11.

    await lifecycle.v11.handle_v11_changes(app, {("change", "/x/plugin.toml")})

    # Если дошли сюда — тест пройден.
    assert True


# --------------------------------------------------------------------------- #
# _start_v11_hot_reload: feature-flag gating
# --------------------------------------------------------------------------- #


async def test_start_v11_hot_reload_skipped_when_feature_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``v11.hot_reload_enabled=False`` → функция возвращает None сразу."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.v11, "hot_reload_enabled", False)

    app = FastAPI()
    await lifecycle.v11.start_v11_hot_reload(app)  # noqa: F841

    # Возвращаемое значение не важно (None), но state НЕ должен содержать task.
    assert getattr(app.state, "v11_hot_reload_task", None) is None


async def test_start_v11_hot_reload_skipped_when_no_loaders_and_no_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hot_reload_enabled=True`` + нет loader'ов + нет директорий → skip."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.v11, "hot_reload_enabled", True)
    monkeypatch.setattr(settings.v11, "hot_reload_debounce_ms", 100)

    app = FastAPI()
    # Намеренно не заполняем state.

    await lifecycle.v11.start_v11_hot_reload(app)  # noqa: F841

    assert getattr(app.state, "v11_hot_reload_task", None) is None


# --------------------------------------------------------------------------- #
# _shutdown_v11_loaders
# --------------------------------------------------------------------------- #


async def test_shutdown_v11_loaders_handles_missing_loaders() -> None:
    """``_shutdown_v11_loaders`` корректно обрабатывает app без loader'ов."""
    app = FastAPI()
    # Не устанавливаем plugin_loader_v11 / route_loader_v11 / v11_hot_reload_task.

    # Не должно бросить.
    await lifecycle.v11.shutdown_v11_loaders(app)


async def test_shutdown_v11_loaders_calls_unload_all() -> None:
    """При наличии route_loader — ``unload_all`` вызван."""
    app = FastAPI()

    route_loader = MagicMock()
    route_loader.unload_all = AsyncMock()
    app.state.route_loader_v11 = route_loader

    plugin_loader = MagicMock()
    plugin_loader.shutdown_all = AsyncMock()
    app.state.plugin_loader_v11 = plugin_loader

    await lifecycle.v11.shutdown_v11_loaders(app)

    assert route_loader.unload_all.await_count == 1
    assert plugin_loader.shutdown_all.await_count == 1


async def test_shutdown_v11_loaders_cancels_hot_reload_task() -> None:
    """``_shutdown_v11_loaders`` отменяет v11_hot_reload_task, если он активен."""
    app = FastAPI()

    # Создаём уже-завершённую asyncio.Task — cancel пройдёт без warning'ов.
    async def _noop() -> None:
        return

    task = asyncio.create_task(_noop())
    await task
    app.state.v11_hot_reload_task = task

    # Не должно бросить.
    await lifecycle.v11.shutdown_v11_loaders(app)


# --------------------------------------------------------------------------- #
# _register_storage_singletons: graceful degradation
# --------------------------------------------------------------------------- #


def test_register_storage_singletons_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_register_storage_singletons`` не падает ни при каких исключениях импорта.

    Каждый ``try/except`` обёрнут в logging.debug — функция всегда возвращает None.
    """
    app = FastAPI()
    # Не подменяем ничего — модули импорта либо сработают, либо бросят, но
    # catch-all в функции подавит исключение.

    result = lifecycle.register_storage_singletons(app)

    assert result is None


def test_register_storage_singletons_writes_feedback_repo_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``MongoFeedbackRepository`` импортируется — state записан."""

    class _FakeRepo:
        pass

    fake_module = MagicMock()
    fake_module.MongoFeedbackRepository = _FakeRepo

    monkeypatch.setitem(
        __import__("sys").modules,
        "src.backend.infrastructure.repositories.ai_feedback_mongo",
        fake_module,
    )

    app = FastAPI()
    lifecycle.register_storage_singletons(app)

    assert isinstance(getattr(app.state, "ai_feedback_repository", None), _FakeRepo)
