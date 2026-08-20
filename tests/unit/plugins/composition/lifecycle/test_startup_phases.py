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
    """Observability фазы идут ПЕРВЫМИ.

    Причина: OTel/Sentry/ConfigValidator нужен до service registration.
    Phase counts are computed dynamically — adding a 7th phase won't break this.
    """
    from src.backend.plugins.composition.lifecycle.startup_phases import observability

    obs_count = sum(
        1 for p in STARTUP_PHASES
        if p.__module__ == observability.__name__
    )
    # First `obs_count` should all be observability
    for i in range(obs_count):
        assert STARTUP_PHASES[i].__module__ == observability.__name__, (
            f"Phase {i} should be observability, got {STARTUP_PHASES[i].__module__}"
        )
    # After observability, should be different module
    if obs_count < len(STARTUP_PHASES):
        assert STARTUP_PHASES[obs_count].__module__ != observability.__name__, (
            f"Phase {obs_count} should NOT be observability (end of obs block)"
        )


@pytest.mark.unit
def test_startup_phases_order_infrastructure_second() -> None:
    """Infrastructure фазы идут ПОСЛЕ observability, ДО services."""
    from src.backend.plugins.composition.lifecycle.startup_phases import (
        infrastructure,
        observability,
        services,
    )

    # Find boundaries dynamically
    obs_count = sum(
        1 for p in STARTUP_PHASES if p.__module__ == observability.__name__
    )
    infra_count = sum(
        1 for p in STARTUP_PHASES if p.__module__ == infrastructure.__name__
    )
    # Infrastructure should immediately follow observability
    for i in range(obs_count, obs_count + infra_count):
        assert STARTUP_PHASES[i].__module__ == infrastructure.__name__, (
            f"Phase {i} should be infrastructure, got {STARTUP_PHASES[i].__module__}"
        )
    # After infrastructure, should be different module (services)
    if obs_count + infra_count < len(STARTUP_PHASES):
        assert STARTUP_PHASES[obs_count + infra_count].__module__ == services.__name__, (
            f"Phase {obs_count + infra_count} should be services"
        )


@pytest.mark.unit
def test_startup_phases_order_services_last() -> None:
    """Services фазы идут последними (after observability + infrastructure)."""
    from src.backend.plugins.composition.lifecycle.startup_phases import (
        infrastructure,
        observability,
        services,
    )

    # Compute boundaries
    obs_count = sum(
        1 for p in STARTUP_PHASES if p.__module__ == observability.__name__
    )
    infra_count = sum(
        1 for p in STARTUP_PHASES if p.__module__ == infrastructure.__name__
    )
    services_count = sum(
        1 for p in STARTUP_PHASES if p.__module__ == services.__name__
    )

    # All services should be at the end
    for i in range(obs_count + infra_count, len(STARTUP_PHASES)):
        assert STARTUP_PHASES[i].__module__ == services.__name__, (
            f"Phase {i} should be services"
        )
    # Total must match
    assert obs_count + infra_count + services_count == len(STARTUP_PHASES)


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
