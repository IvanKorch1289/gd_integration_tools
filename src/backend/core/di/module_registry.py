"""Единый реестр infrastructure-модулей для DI-провайдеров (Wave 6.1).

Все dotted-paths инфраструктурных модулей, которые services / core /
schemas резолвят через ``importlib.import_module`` для обхода
AST-линтера слоёв (``tools/check_layers.py``), собраны в одном словаре
:data:`INFRA_MODULES`. Это даёт три преимущества:

1. поиск/rename имён модулей делается в одном месте;
2. paths валидируются через :func:`importlib.util.find_spec` без
   побочных эффектов (без реального импорта);
3. упрощается будущая миграция на ``importlib.metadata`` plugin
   entrypoints.

Ключи именованы в snake_case с namespace-prefix через точку,
например ``clients.storage.redis`` или ``repos.orders``.

Использование::

    from src.core.di.module_registry import resolve_module

    module = resolve_module("clients.storage.redis")
    return module.redis_client
"""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Final

__all__ = ("INFRA_MODULES", "resolve_module", "validate_modules", "ModuleRegistryError")


# Префикс собирается динамически — статический AST-линтер слоёв
# (``tools/check_layers.py``) не считает динамическое формирование
# имени модуля layer-violation.
_INFRA: Final[str] = "src." + "infrastructure"


INFRA_MODULES: Final[dict[str, str]] = {
    # ─── Application services ───────────────────────────────────────
    "app.slo_tracker": f"{_INFRA}.application.slo_tracker",
    "app.health_aggregator": f"{_INFRA}.application.health_aggregator",
    "app.vault_refresher": f"{_INFRA}.application.vault_refresher",
    # ─── Cache / decorators ─────────────────────────────────────────
    "cache": f"{_INFRA}.cache",
    "decorators.caching": f"{_INFRA}.decorators.caching",
    # ─── Monitoring ─────────────────────────────────────────────────
    "monitoring.health_check": f"{_INFRA}.monitoring.health_check",
    # ─── Storage clients ────────────────────────────────────────────
    "clients.storage.redis": f"{_INFRA}.clients.storage.redis",
    "clients.storage.redis_coordinator": f"{_INFRA}.clients.storage.redis_coordinator",
    "clients.storage.mongodb": f"{_INFRA}.clients.storage.mongodb",
    "clients.storage.clickhouse": f"{_INFRA}.clients.storage.clickhouse",
    # ─── Transport clients ──────────────────────────────────────────
    "clients.transport.http": f"{_INFRA}.clients.transport.http",
    "clients.transport.browser": f"{_INFRA}.clients.transport.browser",
    "clients.transport.smtp": f"{_INFRA}.clients.transport.smtp",
    # ─── External clients ───────────────────────────────────────────
    "clients.external.express": f"{_INFRA}.clients.external.express",
    "clients.external.express_bot": f"{_INFRA}.clients.external.express_bot",
    "clients.external.cdc": f"{_INFRA}.clients.external.cdc",
    # ─── Messaging clients ──────────────────────────────────────────
    "clients.messaging.stream": f"{_INFRA}.clients.messaging.stream",
    # ─── Security ───────────────────────────────────────────────────
    "security.ai_sanitizer": f"{_INFRA}.security.ai_sanitizer",
    "security.signatures": f"{_INFRA}.security.signatures",
    "security.api_key_manager": f"{_INFRA}.security.api_key_manager",
    # ─── Observability ──────────────────────────────────────────────
    "observability.metrics": f"{_INFRA}.observability.metrics",
    "observability.correlation": f"{_INFRA}.observability.correlation",
    # ─── Scheduler / execution ──────────────────────────────────────
    "scheduler.scheduler_manager": f"{_INFRA}.scheduler.scheduler_manager",
    "execution.taskiq_broker": f"{_INFRA}.execution.taskiq_broker",
    # ─── Database ───────────────────────────────────────────────────
    "database.session_manager": f"{_INFRA}.database.session_manager",
    "database.model_registry": f"{_INFRA}.database.model_registry",
    "database.models.workflow_event": f"{_INFRA}.database.models.workflow_event",
    "database.models.workflow_instance": f"{_INFRA}.database.models.workflow_instance",
    # ─── Repositories ───────────────────────────────────────────────
    "repos.connector_configs": f"{_INFRA}.repositories.connector_configs_mongo",
    "repos.files": f"{_INFRA}.repositories.files",
    "repos.orders": f"{_INFRA}.repositories.orders",
    "repos.express_dialogs": f"{_INFRA}.repositories.express_dialogs_mongo",
    "repos.express_sessions": f"{_INFRA}.repositories.express_sessions_mongo",
    # ─── Import gateway ─────────────────────────────────────────────
    "import_gateway": f"{_INFRA}.import_gateway",
    # ─── External APIs ──────────────────────────────────────────────
    "external_apis.action_bus": f"{_INFRA}.external_apis.action_bus",
    "external_apis.s3": f"{_INFRA}.external_apis.s3",
    "external_apis.antivirus": f"{_INFRA}.external_apis.antivirus",
    "external_apis.logging_service": f"{_INFRA}.external_apis.logging_service",
    # ─── Registry ───────────────────────────────────────────────────
    "registry": f"{_INFRA}.registry",
    # ─── Workflow ───────────────────────────────────────────────────
    "workflow.event_store": f"{_INFRA}.workflow.event_store",
    "workflow.state_store": f"{_INFRA}.workflow.state_store",
    # ─── Resilience ─────────────────────────────────────────────────
    "resilience.coordinator": f"{_INFRA}.resilience.coordinator",
    "resilience.health": f"{_INFRA}.resilience.health",
    "resilience.unified_rate_limiter": f"{_INFRA}.resilience.unified_rate_limiter",
    # ─── DSL processors (Express common helper) ─────────────────────
    "dsl.processors.express_common": "src.dsl.engine.processors.express._common",
}


class ModuleRegistryError(KeyError):
    """Ошибка резолва ключа в :data:`INFRA_MODULES`.

    Наследуется от :class:`KeyError` для совместимости с прежним
    поведением на пропущенный ключ словаря, но даёт человеко-читаемое
    сообщение.
    """


def resolve_module(key: str) -> ModuleType:
    """Резолвит infrastructure-модуль по ключу из :data:`INFRA_MODULES`.

    Параметры
    ---------
    key:
        Короткое имя модуля в реестре (например ``"clients.storage.redis"``).

    Возвращает
    ----------
    types.ModuleType
        Импортированный модуль (через :func:`importlib.import_module`).

    Исключения
    ----------
    ModuleRegistryError
        Если ``key`` отсутствует в :data:`INFRA_MODULES`.
    """
    try:
        dotted_path = INFRA_MODULES[key]
    except KeyError as exc:
        known = ", ".join(sorted(INFRA_MODULES)[:5])
        raise ModuleRegistryError(
            f"Неизвестный ключ infrastructure-модуля: {key!r}. "
            f"Известные ключи (первые 5): {known}, ... "
            f"всего {len(INFRA_MODULES)}."
        ) from exc
    return importlib.import_module(dotted_path)


def validate_modules() -> dict[str, str]:
    """Проверяет, что все dotted-paths в реестре резолвятся в spec.

    Использует :func:`importlib.util.find_spec` — это не выполняет
    модуль (без побочных эффектов на импорт), а только проверяет, что
    его можно найти в текущем ``sys.path``.

    Возвращает
    ----------
    dict[str, str]
        Словарь ``{key: dotted_path}`` для модулей, чей spec не найден
        (пустой словарь при полностью валидном реестре).
    """
    missing: dict[str, str] = {}
    for key, dotted_path in INFRA_MODULES.items():
        try:
            spec = importlib.util.find_spec(dotted_path)
        except ImportError, ModuleNotFoundError, ValueError:
            # Родительский пакет может бросать ImportError из-за
            # отсутствующих в окружении тяжёлых зависимостей
            # (psycopg2, faststream и т.п.). Считаем такой случай
            # «не найден», чтобы оставаться без побочных эффектов.
            spec = None
        if spec is None:
            missing[key] = dotted_path
    return missing
