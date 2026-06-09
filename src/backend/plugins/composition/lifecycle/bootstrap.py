"""Bootstrap helpers — storage, cache, snapshot, resilience (S82 W2).

Извлечён из ``src/backend/plugins/composition/lifecycle/__init__.py``
(1142→970 LOC after W1). ADR-0105 plan.

Scope (S82 W2):
* ``_register_storage_singletons`` — 48 LOC
* ``_validate_cache_layers`` — 22 LOC
* ``_bootstrap_snapshot_job`` — 40 LOC
* ``_bootstrap_resilience_coordinator`` — 31 LOC
Total: 141 LOC extracted.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.backend.infrastructure.logging.factory import get_logger

app_logger = get_logger("application")

__all__ = (
    "bootstrap_resilience_coordinator",
    "bootstrap_snapshot_job",
    "register_storage_singletons",
    "validate_cache_layers",
)


def register_storage_singletons(app: FastAPI) -> None:
    """Регистрирует Mongo-реализации репозиториев в ``app.state`` (W6).

    Bootstrap-точка для Mongo-backends: services/ai/feedback/repository.py
    и services/notebooks/service.py обращаются к ``app.state.*`` через
    ``app_state_singleton``; конкретный backend ставится здесь.
    """
    try:
        from src.backend.infrastructure.repositories.ai_feedback_mongo import (
            MongoFeedbackRepository,
        )

        app.state.ai_feedback_repository = MongoFeedbackRepository()
    except Exception as exc:
        app_logger.debug("MongoFeedbackRepository registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )
        from src.backend.services.notebooks.service import NotebookService

        app.state.notebook_service = NotebookService(MongoNotebookRepository())
    except Exception as exc:
        app_logger.debug("MongoNotebookRepository registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.clients.storage.vector_store import (
            get_vector_store,
        )
        from src.backend.services.ai.rag_service import RAGService

        cache = getattr(app.state, "three_tier_rag_cache", None)
        app.state.rag_service = RAGService(store=get_vector_store(), cache=cache)
    except Exception as exc:
        app_logger.debug("RAGService registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )
        from src.backend.services.io.search import SearchService

        app.state.search_service = SearchService(client=get_elasticsearch_client())
    except Exception as exc:
        app_logger.debug("SearchService registration skipped: %s", exc)


def validate_cache_layers() -> None:
    """Проверяет отсутствие двойного кэширования (ADR-004) на старте.

    Использует глобальный ``cache_config_registry`` из
    ``src.infrastructure.cache``. Каждый сервис/репозиторий, включающий
    кэш, обязан зарегистрироваться в этом реестре через
    ``cache_config_registry.register(entity=..., layer=..., enabled=True)``.

    При обнаружении конфликта падаем fail-fast с ``CacheDuplicationError``
    — лучше не запустить приложение, чем работать с неконсистентной
    инвалидацией кэша.
    """
    from src.backend.infrastructure.cache import cache_config_registry
    from src.backend.infrastructure.cache.validator import CacheLayerValidator

    CacheLayerValidator().validate(cache_config_registry)
    app_logger.info(
        "Cache layer validation passed (ADR-004). Entries: %d",
        len(cache_config_registry.entries),
    )


def bootstrap_snapshot_job(app: FastAPI) -> None:
    """W26.8 — initial PG → SQLite sync + регистрация interval-job'а.

    Initial sync необходим для холодного старта (snapshot-файл ещё
    отсутствует), interval-job — для последующего регулярного refresh'а.
    Оба шага опциональны: ошибки не блокируют startup (fallback продолжит
    работать на устаревшем файле; alert придёт через метрику
    ``snapshot_age_seconds``).
    """
    try:
        from src.backend.core.config.settings import settings as app_settings

        if not app_settings.snapshot.enabled:
            app_logger.info(
                "Snapshot job отключён (snapshot.enabled=false), пропуск bootstrap"
            )
            return

        from src.backend.infrastructure.resilience.snapshot_job import (
            register_snapshot_job,
            run_snapshot_now,
        )
        from src.backend.infrastructure.scheduler.scheduler_manager import (
            scheduler_manager,
        )

        if app_settings.snapshot.run_on_startup:
            try:
                run_snapshot_now()
            except Exception as exc:
                app_logger.warning(
                    "Initial PG → SQLite snapshot failed (продолжаем с stale-файлом): %s",
                    exc,
                )

        register_snapshot_job(scheduler_manager.scheduler)
    except Exception as exc:
        app_logger.warning("Snapshot job bootstrap skipped: %s", exc)


def bootstrap_resilience_coordinator(app: FastAPI) -> None:
    """W26.1/W26.2 — регистрирует 11 компонентов в ``ResilienceCoordinator``
    и подключает их к ``HealthAggregator``.

    На этапе W26.1 backend'ы — stubs (``NotImplementedError``); цель —
    чтобы health-check matrix (W26.2) сразу видела весь список из 11
    компонентов. Реальные wiring'и подставляются в W26.3/W26.4.
    """
    try:
        from src.backend.core.config.settings import settings as app_settings
        from src.backend.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
        from src.backend.infrastructure.resilience.coordinator import (
            get_resilience_coordinator,
        )
        from src.backend.infrastructure.resilience.health import (
            register_resilience_health_checks,
        )
        from src.backend.infrastructure.resilience.registration import (
            register_all_components,
        )

        coordinator = get_resilience_coordinator()
        register_all_components(coordinator, app_settings.resilience)
        register_resilience_health_checks(get_health_aggregator(), coordinator)
        app.state.resilience_coordinator = coordinator
    except Exception as exc:
        app_logger.warning("ResilienceCoordinator bootstrap skipped: %s", exc)
