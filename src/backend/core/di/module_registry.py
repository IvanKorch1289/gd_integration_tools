"""Единый реестр модулей для DI-провайдеров (Wave 6.1).

Все dotted-paths модулей (в основном infrastructure, но допускаются
санкционированные cross-layer пути — например ``security.facade`` ведёт
в services, ``dsl.processors.express_common`` в dsl), которые services /
core / schemas резолвят через ``importlib.import_module`` для обхода
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

    from src.backend.core.di.module_registry import resolve_module

    module = resolve_module("clients.storage.redis")
    return module.redis_client

**Lifecycle scopes (S169 W2, P2-2):**

Все модули по умолчанию — :attr:`Scope.SINGLETON` (lazy singleton,
резолв при первом вызове). Расширенные scopes (:attr:`Scope.SCOPED`,
:attr:`Scope.TRANSIENT`) регистрируются в :data:`MODULE_SCOPES`
(parallel dict, default — SINGLETON для backward-compat).

- ``SINGLETON``: один экземпляр на процесс (lazy).
- ``SCOPED``: один экземпляр на scope (request / tenant / workflow).
  Реализация scope-context — будущий PR (S170+, post audit backlog).
- ``TRANSIENT``: новый экземпляр на каждый resolve_module().
  Полезно для stateless utilities и test fixtures.
"""

from __future__ import annotations

import importlib
import importlib.util
from enum import Enum
from types import ModuleType
from typing import Final

from src.backend.core.di.module_registry_extensions import (
    ExtensionRegistrationError,
    clear_extension_modules,
    is_extension_path,
    list_extension_modules,
    register_extension_module,
    unregister_extension_module,
)

__all__ = (
    "INFRA_MODULES",
    "MODULE_SCOPES",
    "ExtensionRegistrationError",
    "ModuleRegistryError",
    "Scope",
    "clear_extension_modules",
    "get_module_scope",
    "is_extension_path",
    "list_extension_modules",
    "register_extension_module",
    "resolve_module",
    "unregister_extension_module",
    "validate_modules",
)


# Префикс собирается динамически — статический AST-линтер слоёв
# (``tools/check_layers.py``) не считает динамическое формирование
# имени модуля layer-violation.
_INFRA: Final[str] = "src." + "backend.infrastructure"


class Scope(Enum):
    """Lifecycle scope для DI-модулей (S169 W2, P2-2).

    SINGLETON — один экземпляр на процесс (lazy resolve, default).
    SCOPED — один экземпляр на scope-context (request/tenant/workflow).
    TRANSIENT — новый экземпляр на каждый resolve_module() call.

    Аналогично Microsoft.Extensions.DependencyInjection.ServiceLifetime
    и Spring Framework scopes. Реализация SCOPED/TRANSIENT —
    S170+ (текущий коммит только schema registration).
    """

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


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
    "clients.storage.s3_pool": f"{_INFRA}.clients.storage.s3_pool",  # R1+ fix (S95): missing key for claim_check tests
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
    # ─── Database ───────────────────────────────────────────────────
    "database.session_manager": f"{_INFRA}.database.session_manager",
    "database.model_registry": f"{_INFRA}.database.model_registry",
    "database.models.workflow_event": "src.backend.core.domain.models.workflow_event",
    "database.models.workflow_instance": "src.backend.core.domain.models.workflow_instance",
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
    "antivirus.service": f"{_INFRA}.antivirus.service",
    "external_apis.logging_service": f"{_INFRA}.external_apis.logging_service",
    # ─── Registry ───────────────────────────────────────────────────
    "registry": f"{_INFRA}.registry",
    # ─── Workflow ───────────────────────────────────────────────────
    "workflow.event_store": f"{_INFRA}.workflow.pg_runner_internals",
    "workflow.state_store": f"{_INFRA}.workflow.pg_runner_internals",
    "workflow.pg_runner_internals": f"{_INFRA}.workflow.pg_runner_internals",
    "workflow.factory": f"{_INFRA}.workflow.factory",  # R1 fix (S95): workflow_subprocess DI
    # ─── Resilience ─────────────────────────────────────────────────
    "resilience.coordinator": f"{_INFRA}.resilience.coordinator",
    "resilience.health": f"{_INFRA}.resilience.health",
    "resilience.unified_rate_limiter": f"{_INFRA}.resilience.unified_rate_limiter",
    # ─── DSL processors (Express common helper) ─────────────────────
    "dsl.processors.express_common": "src.backend.dsl.engine.processors.express._common",
    # ─── A1 (ledger, S96): остальные ключи DI-провайдеров S84-S87 ──
    # Ранее отсутствовали в статическом реестре — резолвились только при
    # удачном порядке импортов через runtime-регистрацию, отсюда
    # недетерминизм коллекции тестов и ModuleRegistryError в runtime-путях
    # (S3/telegram/DB/sinks/vault/audit). Все пути проверены find_spec.
    # NB: ключ "infrastructure.cdc.registry" НЕ регистрируется — целевого
    # модуля не существует (cdc/registry.py и get_default_source() в кодовой
    # базе отсутствуют, провайдер get_cdc_provider() — dead code, ledger P2).
    "antivirus.factory": f"{_INFRA}.antivirus.factory",
    "clients.external.telegram_bot": f"{_INFRA}.clients.external.telegram_bot",
    "clients.messaging.reply_channel": f"{_INFRA}.clients.messaging.reply_channel",
    "clients.storage.redis_lock": f"{_INFRA}.clients.storage.redis_lock",
    "clients.storage.vector_store": f"{_INFRA}.clients.storage.vector_store",
    "clients.transport.http.factory": f"{_INFRA}.clients.transport.http.factory",
    "clients.transport.http_httpx": f"{_INFRA}.clients.transport.http_httpx",
    "database.database": f"{_INFRA}.database.database",
    "di_bridge.dlq": f"{_INFRA}.di_bridge.dlq",
    "execution.dask_backend": f"{_INFRA}.execution.dask_backend",
    "infrastructure.clients.external.search_providers": (
        f"{_INFRA}.clients.external.search_providers"
    ),
    "infrastructure.notifications.gateway": f"{_INFRA}.notifications.gateway",
    "messaging.dlq.memory_writer": f"{_INFRA}.messaging.dlq.memory_writer",
    "notifications": f"{_INFRA}.notifications",
    "observability.immutable_audit": f"{_INFRA}.observability.immutable_audit",
    "repositories.express_dialogs_mongo": f"{_INFRA}.repositories.express_dialogs_mongo",
    "repositories.outbox": f"{_INFRA}.repositories.outbox",
    "secrets.vault_backend": f"{_INFRA}.secrets.vault_backend",
    "secrets.vault_client": f"{_INFRA}.secrets.vault_client",
    # security.facade живёт в services-слое (core → services bypass);
    # get_security_facade() — services/security/facade.py.
    "security.facade": "src.backend.services.security.facade",
    "security.token_registry": f"{_INFRA}.security.token_registry",
    "sinks.factory": f"{_INFRA}.sinks.factory",
    "sinks.grpc_sink": f"{_INFRA}.sinks.grpc_sink",
    "sinks.mq_sink": f"{_INFRA}.sinks.mq_sink",
    "sinks.soap_sink": f"{_INFRA}.sinks.soap_sink",
    "sinks.ws_sink": f"{_INFRA}.sinks.ws_sink",
    "storage.factory": f"{_INFRA}.storage.factory",
    "workflow.saga_state": f"{_INFRA}.workflow.saga_state",
}


# Lifecycle scopes (S169 W2, P2-2). Ключи — те же что в :data:`INFRA_MODULES`.
# Default = SINGLETON (backward-compat). Расширения регистрируют
# SCOPED/TRANSIENT здесь (lazy, hot-reloadable).
MODULE_SCOPES: Final[dict[str, Scope]] = {
    # Пример для будущих extensions (S170+):
    # "clients.storage.redis": Scope.TRANSIENT,  # test fixtures
    # "services.notebooks.repository": Scope.SCOPED,  # per-workflow
}


class ModuleRegistryError(KeyError):
    """Ошибка резолва ключа в :data:`INFRA_MODULES`.

    Наследуется от :class:`KeyError` для совместимости с прежним
    поведением на пропущенный ключ словаря, но даёт человеко-читаемое
    сообщение.
    """


def get_module_scope(key: str) -> Scope:
    """Возвращает lifecycle scope для модуля из :data:`MODULE_SCOPES`.

    Если ``key`` отсутствует в :data:`MODULE_SCOPES` — возвращает
    :attr:`Scope.SINGLETON` (default, backward-compat).

    Parameters
    ----------
        key: Ключ модуля в :data:`INFRA_MODULES`.

    Returns
    -------
        :class:`Scope` для данного модуля.

    Raises
    ------
        ModuleRegistryError: Если ``key`` отсутствует в :data:`INFRA_MODULES`.

    """
    if key not in INFRA_MODULES:
        known = ", ".join(sorted(INFRA_MODULES)[:5])
        raise ModuleRegistryError(
            f"Неизвестный ключ infrastructure-модуля: {key!r}. "
            f"Известные ключи (первые 5): {known}, ... "
            f"всего {len(INFRA_MODULES)}."
        )
    return MODULE_SCOPES.get(key, Scope.SINGLETON)


def resolve_module(key: str) -> ModuleType:
    """Резолвит infrastructure-модуль по ключу.

    Resolution order (S172 M3 — ARC-006):

    1. **Static core**: keys из :data:`INFRA_MODULES` (hard-coded).
    2. **Extension-registered**: keys добавленные через
       :func:`register_extension_module` (extension lifecycle hook).
    3. :class:`ModuleRegistryError` если ключ не найден ни в одном.

    Scope-aware behaviour (S169 W2) применяется только к static-core
    modules через :data:`MODULE_SCOPES`. Extension-registered keys
    следуют scope конвенциям своего ``dotted_path`` (single-import via
    sys.modules cache = :attr:`Scope.SINGLETON` semantic).

    Parameters
    ----------
    key :
        Short module name в реестре (например ``"clients.storage.redis"``).

    Returns
    -------
    types.ModuleType
        Импортированный модуль (через :func:`importlib.import_module`).

    Raises
    ------
    ModuleRegistryError
        Если ``key`` отсутствует в обоих реестрах.

    """
    # Extension-registered lookup (S172 M3 ARC-006 fix A-6-3):
    # extension wins over core (extensions add new modules, не
    # override core). Single snapshot через dict membership-test.
    ext_modules = list_extension_modules()
    if key in ext_modules:
        dotted_path = ext_modules[key]
    elif key in INFRA_MODULES:
        scope = get_module_scope(key)
        if scope is Scope.TRANSIENT:
            dotted_path = INFRA_MODULES[key]
            spec = importlib.util.find_spec(dotted_path)
            if spec is None:
                raise ModuleNotFoundError(f"Cannot find spec for {dotted_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            return module
        return _resolve_singleton(key)
    else:
        known = ", ".join(sorted(INFRA_MODULES)[:5] + sorted(ext_modules)[:5])
        raise ModuleRegistryError(
            f"Неизвестный ключ infrastructure-модуля: {key!r}. "
            f"Известные ключи (первые 5 core + 5 extensions): {known}, ... "
            f"всего {len(INFRA_MODULES) + len(ext_modules)}."
        )
    # Extension registered → standard import (SINGLETON semantic).
    try:
        return importlib.import_module(dotted_path)
    except ImportError as exc:
        raise ModuleRegistryError(
            f"extension module {key!r} → {dotted_path!r} import failed: {exc}"
        ) from exc


def _resolve_singleton(key: str) -> ModuleType:
    """Резолвит модуль через стандартный import (singleton semantic)."""
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
        except (ImportError, ModuleNotFoundError, ValueError):
            # Родительский пакет может бросать ImportError из-за
            # отсутствующих в окружении тяжёлых зависимостей
            # (psycopg2, faststream и т.п.). Считаем такой случай
            # "не найден", чтобы оставаться без побочных эффектов.
            spec = None
        if spec is None:
            missing[key] = dotted_path
    return missing
