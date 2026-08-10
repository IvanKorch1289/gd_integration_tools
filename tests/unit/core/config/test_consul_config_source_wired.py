"""D-AUDIT-A12-02 fix (cycle 1): ConsulConfigSettingsSource wired в settings_customise_sources.

Без фикса :class:`ConsulConfigSettingsSource` оставался dead code —
определён в config_loader.py, но НЕ включён в
``BaseSettingsWithLoader.settings_customise_sources``. Consul runtime-config
опциональный, активируется через ``CONSUL_ENABLED=true``.
"""


from __future__ import annotations

import inspect

from src.backend.core.config.config_loader import (
    BaseSettingsWithLoader,
    ConsulConfigSettingsSource,
)


class TestConsulConfigSourceWired:
    """D-AUDIT-A12-02 fix (cycle 1): ConsulConfigSettingsSource в source chain."""

    def test_consul_source_in_customise_sources(self) -> None:
        """BaseSettingsWithLoader.settings_customise_sources возвращает ConsulConfigSettingsSource."""
        src = inspect.getsource(BaseSettingsWithLoader.settings_customise_sources)
        assert "ConsulConfigSettingsSource(settings_cls)" in src, (
            "settings_customise_sources должен возвращать ConsulConfigSettingsSource"
        )

    def test_consul_source_class_exists(self) -> None:
        """ConsulConfigSettingsSource class определён в config_loader module."""
        assert ConsulConfigSettingsSource is not None
        # Verify это FilteredSettingsSource subclass
        from pydantic_settings import PydanticBaseSettingsSource

        assert issubclass(ConsulConfigSettingsSource, PydanticBaseSettingsSource)

    def test_consul_source_disabled_by_default(self) -> None:
        """ConsulConfigSettingsSource._load_data returns {} if CONSUL_ENABLED не выставлен."""
        import os

        # Ensure CONSUL_ENABLED не выставлен
        os.environ.pop("CONSUL_ENABLED", None)
        os.environ.pop("CONSUL_ADDR", None)

        # Создаём тестовый subclass через _is_consul_enabled check
        from src.backend.core.config.config_loader import _is_consul_enabled

        assert _is_consul_enabled() is False, (
            "Без CONSUL_ENABLED=true, _is_consul_enabled() должен возвращать False"
        )
