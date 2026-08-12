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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # S3.5: type-only declarations for the top-10 most-used providers
    # (см. tests/unit/core/di/providers/test_top10_providers_typing.py).
    # Runtime-резолв остаётся через ``__getattr__`` (generic re-export shim),
    # но mypy/IDE видят конкретные сигнатуры для самых частых имён.
    from collections.abc import Callable

    from src.backend.core.messaging.eventbus.facade import EventBusFacade

    get_redis_client_factory: Callable[[], Callable[[], Any]]
    get_event_bus_facade_provider: Callable[[], EventBusFacade]
    get_redis_client_class: Callable[[], type[Any]]
    get_correlation_id: Callable[[], str]
    get_unified_rate_limiter_attr: Callable[[str], Any]
    get_dsl_variables_attr: Callable[[str], Any]
    get_clickhouse_client_class: Callable[[], type[Any]]
    get_mongodb_client_class: Callable[[], type[Any]]
    get_elasticsearch_client_class: Callable[[], type[Any]]
    get_object_storage_class: Callable[[], type[Any]]

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
# S3.5: ``Any`` сохранён by design — модуль является generic re-export shim
# для всех 90+ символов ``infrastructure_locator`` (51 import site + monkeypatch
# string paths). Narrowing типа тут лишил бы смысла сам шаблон ленивого
# реэкспорта. Точечные narrowed-объявления для top-10 most-used providers
# вынесены в ``TYPE_CHECKING`` блок выше (IDE/mypy) — runtime semantics не
# изменены.
def __getattr__(name: str) -> Any:
    """Lazy re-export: defer attribute lookup to infrastructure_locator.

    Avoids eager evaluation of all 90+ symbols at import time.

    Returns:
        ``Any``: значение атрибута ``infrastructure_locator.<name>`` или
        raise ``AttributeError`` при его отсутствии. ``Any`` — единственный
        честный тип для generic re-export shim (S3.5).
    """
    from src.backend.core.di.providers import infrastructure_locator

    return getattr(infrastructure_locator, name)


def __dir__() -> list[str]:
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
