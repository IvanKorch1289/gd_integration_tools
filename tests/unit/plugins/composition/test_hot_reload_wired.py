"""D-AUDIT-A12-06 fix (cycle 1): ConfigHotReloader wired в production lifespan.

Без фикса :class:`ConfigHotReloader` оставался dead code — никто в
production не вызывал ``watch()`` / ``start()``. Операторы не могли
перезагружать ``config_profiles/*.yml`` без рестарта приложения.

После фикса:
- ``_start_config_hot_reload`` зарегистрирован в starting_operations.
- ``_stop_config_hot_reload`` зарегистрирован в ending_operations.
- Watch: ``.env`` + ``config_profiles/`` directory.
- Callback: settings.reload() если доступен.
"""


from __future__ import annotations

from src.backend.plugins.composition.setup_infra import lifecycle


class TestHotReloadWired:
    """D-AUDIT-A12-06 fix (cycle 1): ConfigHotReloader wired в production."""

    def test_start_config_hot_reload_registered_in_starting_operations(self) -> None:
        """_start_config_hot_reload присутствует в starting_operations."""
        names = [name for name, *_ in lifecycle.starting_operations]
        assert "start_config_hot_reload" in names, (
            "starting_operations должна содержать start_config_hot_reload"
        )

    def test_stop_config_hot_reload_registered_in_ending_operations(self) -> None:
        """_stop_config_hot_reload присутствует в ending_operations."""
        names = [name for name, *_ in lifecycle.ending_operations]
        assert "stop_config_hot_reload" in names, (
            "ending_operations должна содержать stop_config_hot_reload"
        )

    def test_start_config_hot_reload_function_exists(self) -> None:
        """_start_config_hot_reload — async функция в lifecycle module."""
        assert hasattr(lifecycle, "_start_config_hot_reload")
        assert callable(lifecycle._start_config_hot_reload)
        import inspect

        assert inspect.iscoroutinefunction(lifecycle._start_config_hot_reload), (
            "_start_config_hot_reload должен быть async функцией"
        )

    def test_stop_config_hot_reload_function_exists(self) -> None:
        """_stop_config_hot_reload — async функция в lifecycle module."""
        assert hasattr(lifecycle, "_stop_config_hot_reload")
        assert callable(lifecycle._stop_config_hot_reload)
        import inspect

        assert inspect.iscoroutinefunction(lifecycle._stop_config_hot_reload), (
            "_stop_config_hot_reload должен быть async функцией"
        )
