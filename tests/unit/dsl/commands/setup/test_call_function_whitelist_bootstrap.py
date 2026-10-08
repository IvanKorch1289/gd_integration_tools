"""Sprint 226 — bootstrap-интеграция call_function whitelist.

Контракт: при вызове :func:`register_action_handlers` (cold-path на startup)
орchestrator ОБЯЗАН поднять whitelist ``call_function`` модулей
из :mod:`manifests` через :func:`load_plugin_manifests_for_migrations`,
а затем зарегистрировать его в :class:`CallFunctionProcessor._active_whitelist`.

Без этой интеграции шаг ``call_function: { ref: ... }`` в любом
YAML-пайплайне всегда давал PermissionError в strict-режиме
(см. :mod:`dsl.engine.processors.function_call`).

Эти тесты регрессионно фиксируют:
1. Свойство :func:`_collect_call_function_whitelist_from_manifests` —
   должен найти ``extensions.<name>.domain.X``-стиль декларации
   в ``plugin.toml`` и долить в whitelist.
2. Свойство :func:`register_action_handlers` — должен вызвать сборщик
   whitelist'а при bootstrap (cold-path инвариант).
3. Контрактный путь ``from plugin.toml → CallFunctionProcessor._active_whitelist``
   для одного объявленного плагина (тест с временным каталогом
   ``tmp_path``, чтобы не трогать prod-каталог ``extensions/``).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from src.backend.dsl.engine.processors.function_call import CallFunctionProcessor


def test_collect_whitelist_helper_exists() -> None:
    """``_collect_call_function_whitelist_from_manifests`` определена в orchestrator."""
    from src.backend.dsl.commands.setup import orchestrator

    assert hasattr(
        orchestrator, "_collect_call_function_whitelist_from_manifests"
    ), "Sprint 226 regression: whitelist collect helper not in orchestrator"
    assert callable(orchestrator._collect_call_function_whitelist_from_manifests)


def test_register_action_handlers_calls_collect_helper() -> None:
    """Orchestrator при bootstrap вызывает сборщик whitelist'а."""
    from src.backend.dsl.commands.setup import orchestrator

    source = inspect.getsource(orchestrator.register_action_handlers)
    assert "_collect_call_function_whitelist_from_manifests" in source, (
        "Sprint 226 regression: register_action_handlers "
        "must call _collect_call_function_whitelist_from_manifests "
        "before _register_* to populate the whitelist before any "
        "call_function step runs"
    )


def test_whitelist_helper_populates_from_manifest(tmp_path: Path) -> None:
    """Helper читает plugin.toml с ``call_function_modules`` и доливает в whitelist.

    Использует временный каталог, чтобы не трогать prod-каталог ``extensions/``.
    Внутри tmp_path создаём минимальный ``plugin.toml`` с одной записью и
    dummy-файл ``plugin.py`` (entry_class проверяется на load, но мы
    манипулируем только manifest-scanning частью).
    """
    from src.backend.dsl.commands.setup import orchestrator

    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()
    plugin_dir = extensions_dir / "fake_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(
        'name = "fake_plugin"\n'
        'version = "0.1.0"\n'
        'requires_core = ">=0.20,<0.21"\n'
        'entry_class = "fake_plugin.plugin:FakePlugin"\n'
        'trust_tier = "B"\n'
        'call_function_modules = ["fake_plugin.services.mod_a"]\n',
        encoding="utf-8",
    )
    # Подменим ``settings.v11.extensions_dir`` через monkeypatch.
    import src.backend.core.config.settings as settings_module

    expected_path = extensions_dir  # захватываем в closure

    class _StubSettings:
        class _StubV11:
            extensions_dir = expected_path

        v11 = _StubV11()

    monkey = getattr(__import__("pytest"), "MonkeyPatch")
    mp = monkey()
        # type: ignore[unused-ignore]
    mp.setattr(settings_module, "settings", _StubSettings)

    # Гарантируем, что whitelist до теста пуст от прошлых вызовов.
    CallFunctionProcessor._active_whitelist.clear()
    try:
        orchestrator._collect_call_function_whitelist_from_manifests()
        assert "fake_plugin.services.mod_a" in (
            CallFunctionProcessor.get_active_whitelist()
        ), (
            "Sprint 226 regression: helper must read plugin.toml and "
            "register call_function_modules into active whitelist"
        )
    finally:
        CallFunctionProcessor._active_whitelist.clear()
        mp.undo()


def test_whitelist_helper_survives_missing_dir(monkeypatch) -> None:
    """Helper no-op если settings.v11.extensions_dir не задан."""
    from src.backend.dsl.commands.setup import orchestrator
    import src.backend.core.config.settings as settings_module

    class _StubSettings:
        class _StubV11:
            extensions_dir = None

        v11 = _StubV11()

    monkeypatch.setattr(settings_module, "settings", _StubSettings)

    # Должен быть no-op, а не raise.
    CallFunctionProcessor._active_whitelist.clear()
    try:
        orchestrator._collect_call_function_whitelist_from_manifests()
        # Whitelist остался пустым.
        assert CallFunctionProcessor.get_active_whitelist() == frozenset()
    finally:
        CallFunctionProcessor._active_whitelist.clear()