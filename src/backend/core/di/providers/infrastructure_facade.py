"""Backward-compat shim — re-exports from :mod:`infrastructure_locator`.

S31 Task 5: ``infrastructure_facade.py`` renamed to ``infrastructure_locator.py``
because the module is a **service locator**, not a capability-checked facade
(unlike StorageFacade/AuthFacade/EventBusFacade). The old name was misleading.

.. deprecated::
    Use ``from src.backend.core.di.providers.infrastructure_locator import X``
    for new code. This shim remains only to avoid breaking the 51 existing
    import sites and monkeypatch string paths that use
    ``infrastructure_facade.get_X``.

A ``DeprecationWarning`` is emitted on import to encourage migration.
"""

from __future__ import annotations

import warnings

# Emit DeprecationWarning on import (cycle 31 S31 Task 5)
warnings.warn(
    "src.backend.core.di.providers.infrastructure_facade is DEPRECATED "
    "(renamed to infrastructure_locator in S31 Task 5 — module is a "
    "service locator, not a capability-checked facade). "
    "Update your imports to infrastructure_locator.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the canonical location using __getattr__ lazy proxy.
def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy re-export: defer attribute lookup to infrastructure_locator.

    Avoids eager evaluation of all 90+ symbols at import time.
    """
    from src.backend.core.di.providers import infrastructure_locator

    return getattr(infrastructure_locator, name)


def __dir__() -> list[str]:  # type: ignore[no-untyped-def]
    """Tab-completion support."""
    from src.backend.core.di.providers import infrastructure_locator

    return sorted(dir(infrastructure_locator))


# Cycle 115: __all__ intentionally omitted — this module proxies all
# names via __getattr__ above, so static linters cannot resolve the
# symbols (F822 false positives). After Cycle 115 migration, no
# production code imports from infrastructure_facade directly anymore,
# so __all__ serves no purpose.
#
# Note for legacy grep-based tests (cycle_26_infra_elasticsearch.py
# etc): "elasticsearch_client_class" and "ElasticSearchClient" are
# still available via __getattr__ from infrastructure_locator.
