"""Регистрация 11 компонентов W26 в ``ResilienceCoordinator``.

* Для трёх компонентов первой волны (W26.3) — реальные wiring'и:
  ``clickhouse`` / ``clamav`` / ``kafka``;
* Для остальных восьми (W26.4) — wiring'и через ``components/`` модули;
* При неудачном wiring'е компонент НЕ остаётся со stub'ом, а пропускается
  с warning'ом (mode='off' через явное отсутствие primary). Это
  соответствует требованию «без техдолга»: stub-уровень устранён.

Канонический список компонентов: ``RESILIENCE_COMPONENTS``.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from src.core.config.services.resilience import ResilienceSettings
from src.infrastructure.resilience.coordinator import ResilienceCoordinator

__all__ = ("RESILIENCE_COMPONENTS", "register_all_components")

logger = logging.getLogger(__name__)


#: Канонический список 11 компонентов W26. Совпадает с ключами
#: ``resilience.breakers`` / ``resilience.fallbacks`` в ``base.yml``.
RESILIENCE_COMPONENTS: Final[tuple[str, ...]] = (
    "db_main",
    "redis",
    "minio",
    "vault",
    "clickhouse",
    "mongodb",
    "elasticsearch",
    "kafka",
    "clamav",
    "smtp",
    "express",
)


def _register_clickhouse(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.audit_chain import (
        build_audit_fallbacks,
        build_audit_primary,
    )

    coordinator.register_from_settings(
        component="clickhouse",
        primary=build_audit_primary(),
        fallbacks=build_audit_fallbacks(),
        settings=settings,
    )


def _register_clamav(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.antivirus_chain import (
        build_antivirus_fallbacks,
        build_antivirus_primary,
    )

    coordinator.register_from_settings(
        component="clamav",
        primary=build_antivirus_primary(),
        fallbacks=build_antivirus_fallbacks(),
        settings=settings,
    )


def _register_kafka(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.mq_chain import (
        build_mq_fallbacks,
        build_mq_primary,
    )

    coordinator.register_from_settings(
        component="kafka",
        primary=build_mq_primary(),
        fallbacks=build_mq_fallbacks(),
        settings=settings,
    )


def _register_db_main(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.database_chain import (
        build_database_fallbacks,
        build_database_primary,
    )

    coordinator.register_from_settings(
        component="db_main",
        primary=build_database_primary(),
        fallbacks=build_database_fallbacks(),
        settings=settings,
    )


def _register_redis(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.cache_chain import (
        build_cache_fallbacks,
        build_cache_primary,
    )

    coordinator.register_from_settings(
        component="redis",
        primary=build_cache_primary(),
        fallbacks=build_cache_fallbacks(),
        settings=settings,
    )


def _register_minio(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.object_storage_chain import (
        build_object_storage_fallbacks,
        build_object_storage_primary,
    )

    coordinator.register_from_settings(
        component="minio",
        primary=build_object_storage_primary(),
        fallbacks=build_object_storage_fallbacks(),
        settings=settings,
    )


def _register_vault(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.secrets_chain import (
        build_secrets_fallbacks,
        build_secrets_primary,
    )

    coordinator.register_from_settings(
        component="vault",
        primary=build_secrets_primary(),
        fallbacks=build_secrets_fallbacks(),
        settings=settings,
    )


def _register_mongodb(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.mongo_chain import (
        build_mongo_fallbacks,
        build_mongo_primary,
    )

    coordinator.register_from_settings(
        component="mongodb",
        primary=build_mongo_primary(),
        fallbacks=build_mongo_fallbacks(),
        settings=settings,
    )


def _register_elasticsearch(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.search_chain import (
        build_search_fallbacks,
        build_search_primary,
    )

    coordinator.register_from_settings(
        component="elasticsearch",
        primary=build_search_primary(),
        fallbacks=build_search_fallbacks(),
        settings=settings,
    )


def _register_smtp(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.smtp_chain import (
        build_smtp_fallbacks,
        build_smtp_primary,
    )

    coordinator.register_from_settings(
        component="smtp",
        primary=build_smtp_primary(),
        fallbacks=build_smtp_fallbacks(),
        settings=settings,
    )


def _register_express(coordinator: ResilienceCoordinator, settings: ResilienceSettings) -> None:
    from src.infrastructure.resilience.components.express_chain import (
        build_express_fallbacks,
        build_express_primary,
    )

    coordinator.register_from_settings(
        component="express",
        primary=build_express_primary(),
        fallbacks=build_express_fallbacks(),
        settings=settings,
    )


_REGISTRARS: Final[dict[str, Any]] = {
    "clickhouse": _register_clickhouse,
    "clamav": _register_clamav,
    "kafka": _register_kafka,
    "db_main": _register_db_main,
    "redis": _register_redis,
    "minio": _register_minio,
    "vault": _register_vault,
    "mongodb": _register_mongodb,
    "elasticsearch": _register_elasticsearch,
    "smtp": _register_smtp,
    "express": _register_express,
}


def register_all_components(
    coordinator: ResilienceCoordinator, settings: ResilienceSettings
) -> None:
    """Регистрирует все 11 компонентов W26 в ``coordinator``.

    Каждый компонент wire'ится через свой модуль ``components/<x>_chain``.
    При import-error или wiring-failure (например, оптeля dep не
    установлена) компонент пропускается с warning'ом — это безопасно для
    dev_light и тестов. В production ошибки wiring'а — фатальные:
    проверять через ``make readiness-check``.
    """
    registered = 0
    for component in RESILIENCE_COMPONENTS:
        registrar = _REGISTRARS.get(component)
        if registrar is None:
            logger.warning(
                "Resilience: для компонента '%s' не задан registrar — пропускаю",
                component,
            )
            continue
        try:
            registrar(coordinator, settings)
            registered += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Resilience: wiring компонента '%s' пропущен (%s: %s)",
                component,
                type(exc).__name__,
                exc,
            )

    logger.info(
        "Resilience: зарегистрировано %d из %d компонентов",
        registered,
        len(RESILIENCE_COMPONENTS),
    )
