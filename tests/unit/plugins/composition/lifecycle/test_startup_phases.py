"""Sprint 19 iteration 10: startup_phases smoke test.

Verifies:
* STARTUP_PHASES list has 19 phases in correct order
* Each phase function has correct signature
* Phases are categorized in correct modules (observability/infrastructure/services)
* Idempotent: re-importing doesn't cause issues
"""
from __future__ import annotations

import inspect

import pytest

from src.backend.plugins.composition.lifecycle.startup_phases import (
    STARTUP_PHASES,
    infrastructure,
    observability,
    services,
)


@pytest.mark.unit
def test_startup_phases_count() -> None:
    """STARTUP_PHASES должен иметь 19 фаз (5 obs + 3 infra + 11 services).

    Если добавляешь новую фазу, обнови этот test.
    """
    assert len(STARTUP_PHASES) == 19, (
        f"Expected 19 phases, got {len(STARTUP_PHASES)}"
    )


@pytest.mark.unit
def test_startup_phases_order_observability_first() -> None:
    """Observability фазы (5) должны идти ПЕРВЫМИ.

    Причина: OTel/Sentry/ConfigValidator нужен до service registration.
    """
    obs_phases = [
        p for p in STARTUP_PHASES
        if p.__module__ == "src.backend.plugins.composition.lifecycle.startup_phases.observability"
    ]
    assert len(obs_phases) == 6, (
        f"Expected 6 observability phases, got {len(obs_phases)}"
    )
    # First 6 should all be observability
    for i in range(6):
        assert STARTUP_PHASES[i].__module__ == (
            "src.backend.plugins.composition.lifecycle.startup_phases.observability"
        ), f"Phase {i} should be observability, got {STARTUP_PHASES[i].__module__}"


@pytest.mark.unit
def test_startup_phases_order_infrastructure_second() -> None:
    """Infrastructure фазы (3) должны идти ПОСЛЕ observability, ДО services."""
    # Index 6-8 should be infrastructure
    for i in [6, 7, 8]:
        assert STARTUP_PHASES[i].__module__ == (
            "src.backend.plugins.composition.lifecycle.startup_phases.infrastructure"
        ), f"Phase {i} should be infrastructure"


@pytest.mark.unit
def test_startup_phases_order_services_last() -> None:
    """Services фазы (10) должны идти последними (9-18)."""
    for i in range(9, 19):
        assert STARTUP_PHASES[i].__module__ == (
            "src.backend.plugins.composition.lifecycle.startup_phases.services"
        ), f"Phase {i} should be services"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_phases_accept_app_argument() -> None:
    """Каждая фаза должна принимать app: FastAPI аргумент.

    Это контракт, которому следуют все startup_phases.
    """
    for i, phase in enumerate(STARTUP_PHASES):
        sig = inspect.signature(phase)
        params = list(sig.parameters.keys())
        # First param должен быть app
        assert params[0] == "app", f"Phase {i} ({phase.__name__}) first param should be 'app', got '{params[0]}'"
        # Return type annotation: None (void) — но with PEP 563 string annotations,
        # sig.return_annotation is the string 'None', not the type None itself.
        assert sig.return_annotation in (None, "None"), (
            f"Phase {i} ({phase.__name__}) should return None, "
            f"got {sig.return_annotation!r}"
        )


@pytest.mark.unit
def test_all_phases_are_coroutines() -> None:
    """Все startup_phases должны быть async (coroutine functions)."""
    for i, phase in enumerate(STARTUP_PHASES):
        assert inspect.iscoroutinefunction(phase), (
            f"Phase {i} ({phase.__name__}) must be async (coroutine function)"
        )


@pytest.mark.unit
def test_modules_export_required_phases() -> None:
    """Каждый модуль должен экспортировать свой __all__."""
    for module in (observability, infrastructure, services):
        assert hasattr(module, "__all__"), f"Module {module.__name__} missing __all__"
        all_names = module.__all__
        # Каждое имя должно быть callable в модуле
        for name in all_names:
            attr = getattr(module, name, None)
            assert callable(attr), f"{module.__name__}.{name} not callable"


@pytest.mark.unit
def test_idempotent_import() -> None:
    """Re-importing должен быть safe (no side effects)."""
    # If we got here without error, import worked
    # Re-import and verify same identity
    from src.backend.plugins.composition.lifecycle.startup_phases import (
        STARTUP_PHASES as SP2,
    )
    assert STARTUP_PHASES is SP2, "Re-import returned different list"
