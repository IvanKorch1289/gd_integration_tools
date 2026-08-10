"""infra_cli — CLI утилиты для infrastructure-слоя.

Используется для ручной регистрации legacy-компонентов (sources/sinks/
storage) в :class:`ConnectorRegistry` через :class:`HealthAdapter`,
а также для интеграции с ``/health`` endpoint через
:class:`HealthAggregator`.

Импорт из manage.py или entrypoints::

    from src.backend.infra_cli.register import register_connector  # noqa: F401 — re-export
    from src.backend.infra_cli.register import get_aggregator_with_registry  # noqa: F401 — re-export
"""

from src.backend.infra_cli.register import (
    get_aggregator_with_registry,
    register_connector,
)

__all__ = ("get_aggregator_with_registry", "register_connector")
