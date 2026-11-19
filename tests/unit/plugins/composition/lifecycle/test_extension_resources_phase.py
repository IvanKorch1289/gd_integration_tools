"""Регресс: startup-фаза pre-load ресурсов расширений (волна 36, P2-1).

До волны 36 ресурсы расширений (ADR-0457) подгружались лениво — при первом
обращении к core-реестру. Тяжёлый импорт попадал в request-path, а поломка
расширения обнаруживалась в рантайме (500), а не на старте.

Фаза ``extensions.phase_extension_resources`` грузит расширения на старте
(после инфраструктуры, до сервисов) и сообщает о состоянии загрузки.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestExtensionResourcesStartupPhase:
    """Фаза загружает расширения и не роняет старт при поломке расширения."""

    @pytest.mark.asyncio
    async def test_phase_loads_extensions(self) -> None:
        """После фазы реестр содержит домены расширений."""
        from src.backend.core.extension_registry import (
            get_extension_registry,
            reset_extension_resources,
        )
        from src.backend.plugins.composition.lifecycle.startup_phases.extensions import (
            phase_extension_resources,
        )

        reset_extension_resources()
        try:
            await phase_extension_resources(object())  # type: ignore[arg-type]

            domains = get_extension_registry().domains()
            assert "orders" in domains
            assert "users" in domains
        finally:
            reset_extension_resources()

    @pytest.mark.asyncio
    async def test_phase_survives_broken_extension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сломанное расширение не роняет старт (best-effort startup)."""
        import src.backend.core.extension_registry as registry_mod
        from src.backend.plugins.composition.lifecycle.startup_phases.extensions import (
            phase_extension_resources,
        )

        registry_mod.reset_extension_resources()
        monkeypatch.setattr(
            registry_mod, "load_extension_resources", lambda **_kwargs: None
        )

        # Фаза не бросает исключение, даже если загрузка ничего не дала.
        await phase_extension_resources(object())  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_phase_registered_between_infrastructure_and_services(self) -> None:
        """Фаза стоит после инфраструктуры и до сервисов."""
        from src.backend.plugins.composition.lifecycle.startup_phases import (
            STARTUP_PHASES,
            extensions,
            infrastructure,
            services,
        )

        modules = [p.__module__ for p in STARTUP_PHASES]
        ext_index = modules.index(extensions.__name__)
        infra_index = modules.index(infrastructure.__name__)
        services_index = modules.index(services.__name__)

        assert infra_index < ext_index < services_index
