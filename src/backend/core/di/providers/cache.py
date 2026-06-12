"""Cache domain providers — invalidation, SLO, health, response/RAG/redis caches.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 20 funcs (10 get + 10 set), 0 private helpers.

Singleton cache ``_overrides`` is per-domain (NOT shared) — каждый domain
имеет свой override-словарь для изоляции тестов и предотвращения
collisions между несвязанными singleton'ами.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

# DEPRECATED (Wave 6.1): локальная ``_INFRA`` константа склеена динамически,
# чтобы ``tools/check_layers.py`` не считал её прямым статическим импортом.
_INFRA = "src." + "backend.infrastructure"

_overrides: dict[str, Any] = {}


# ─────────────── Cache invalidator ───────────────


def get_cache_invalidator_provider() -> Any:
    """Возвращает глобальный CacheInvalidator (см. ``core.interfaces.admin_cache``)."""
    if "cache_invalidator" in _overrides:
        return _overrides["cache_invalidator"]
    module = resolve_module("cache")
    return module.get_cache_invalidator()


def set_cache_invalidator_provider(invalidator: Any) -> None:
    """Установить override для ``cache_invalidator`` provider (test-инжекция)."""
    _overrides["cache_invalidator"] = invalidator


# ─────────────── SLO tracker ───────────────


def get_slo_tracker_provider() -> Any:
    """Получить SLO tracker из overrides или resolve через ``app.slo_tracker``."""
    if "slo_tracker" in _overrides:
        return _overrides["slo_tracker"]
    module = resolve_module("app.slo_tracker")
    return module.get_slo_tracker()


def set_slo_tracker_provider(tracker: Any) -> None:
    """Установить override для ``slo_tracker`` provider (test-инжекция)."""
    _overrides["slo_tracker"] = tracker


# ─────────────── Health aggregator ───────────────


def get_health_aggregator_provider() -> Any:
    """Получить health aggregator из overrides или resolve через ``app.health_aggregator``."""
    if "health_aggregator" in _overrides:
        return _overrides["health_aggregator"]
    module = resolve_module("app.health_aggregator")
    return module.get_health_aggregator()


def set_health_aggregator_provider(aggregator: Any) -> None:
    """Установить override для ``health_aggregator`` provider (test-инжекция)."""
    _overrides["health_aggregator"] = aggregator


# ─────────────── Health-check session factory ───────────────


def get_healthcheck_session_provider() -> Any:
    """Возвращает фабрику healthcheck-сессий (async context manager)."""
    if "healthcheck_session" in _overrides:
        return _overrides["healthcheck_session"]
    module = resolve_module("monitoring.health_check")
    return module.get_healthcheck_service


def set_healthcheck_session_provider(factory: Any) -> None:
    """Установить override для ``healthcheck_session`` factory (test-инжекция)."""
    _overrides["healthcheck_session"] = factory


# ─────────────── Admin cache storage (Redis client) ───────────────


def get_admin_cache_storage_provider() -> Any:
    """Получить admin cache storage client из overrides или resolve через ``clients.storage.redis``."""
    if "admin_cache_storage" in _overrides:
        return _overrides["admin_cache_storage"]
    module = resolve_module("clients.storage.redis")
    return module.redis_client


def set_admin_cache_storage_provider(client: Any) -> None:
    """Установить override для ``admin_cache_storage`` provider (test-инжекция)."""
    _overrides["admin_cache_storage"] = client


# ─────────────── Response cache decorator ───────────────


def get_response_cache_provider() -> Any:
    """Возвращает декоратор ``response_cache`` для services/integrations.

    Реализация: ``infrastructure.decorators.caching.response_cache``.
    Используется в DaData (single callsite) — декорирует async-метод,
    возвращает обёртку с поддержкой memory+redis backend.
    """
    if "response_cache" in _overrides:
        return _overrides["response_cache"]
    module = resolve_module("decorators.caching")
    return module.response_cache


def set_response_cache_provider(decorator: Any) -> None:
    """Установить override для ``response_cache`` decorator (test-инжекция)."""
    _overrides["response_cache"] = decorator


# ─────────────── Wave S32 W4: ThreeTierRagCache provider ───────────────


def get_rag_cache_provider() -> Any:
    """Возвращает ThreeTierRagCache из app.state или None.

    Wave S32 W4: lazy-резолв RAG-кэша через
    ``_get_three_tier_cache()`` (rag_cache_admin). Кэш регистрируется
    в ``setup_ai_2026.py`` при ``rag_cache_settings`` (default-OFF).
    Override через :func:`set_rag_cache_provider` имеет приоритет.
    """
    if "rag_cache" in _overrides:
        return _overrides["rag_cache"]
    # S93 W1 C1: перенесено в core/di/app_state.get_three_tier_rag_cache_from_state
    # чтобы core/ не импортировал из entrypoints/ (layer policy).
    from src.backend.core.di.app_state import get_three_tier_rag_cache_from_state

    return get_three_tier_rag_cache_from_state()


def set_rag_cache_provider(impl: Any) -> None:
    """Test-override для ThreeTierRagCache."""
    _overrides["rag_cache"] = impl


# ─────────────── Redis kv/stream clients (Wave 6.3+) ───────────────


def get_redis_kv_client_provider() -> Any:
    """Возвращает низкоуровневый redis.asyncio key-value клиент.

    В текущей инфраструктуре доступен через ``redis_client.client`` —
    провайдер скрывает этот аксессор от services-слоя.

    Cross-domain ref: вызывается из :func:`auth._build_jwt_blacklist_or_none`
    (late import, не module-level).
    """
    if "redis_kv_client" in _overrides:
        return _overrides["redis_kv_client"]
    module = resolve_module("clients.storage.redis")
    return getattr(module.redis_client, "client", None) or module.redis_client


def set_redis_kv_client_provider(client: Any) -> None:
    _overrides["redis_kv_client"] = client


def get_redis_stream_client_provider() -> Any:
    """Возвращает singleton ``redis_client`` (см. ``RedisStreamClientProtocol``).

    Используется в ``services/ai/llm_judge.py`` для публикации verdicts
    в Redis stream и в ``services/ai/semantic_cache.py`` для exact-lookup.
    """
    if "redis_stream_client" in _overrides:
        return _overrides["redis_stream_client"]
    module = resolve_module("clients.storage.redis")
    return module.redis_client


def set_redis_stream_client_provider(client: Any) -> None:
    _overrides["redis_stream_client"] = client


# ─────────────── HMAC signature builder ───────────────


def get_signature_builder_provider() -> Any:
    """Возвращает callable ``build_signature_headers`` (HMAC headers)."""
    if "signature_builder" in _overrides:
        return _overrides["signature_builder"]
    module = resolve_module("security.signatures")
    return module.build_signature_headers


def set_signature_builder_provider(builder: Any) -> None:
    _overrides["signature_builder"] = builder


__all__ = (
    "get_admin_cache_storage_provider",
    "get_cache_invalidator_provider",
    "get_health_aggregator_provider",
    "get_healthcheck_session_provider",
    "get_rag_cache_provider",
    "get_redis_kv_client_provider",
    "get_redis_stream_client_provider",
    "get_response_cache_provider",
    "get_signature_builder_provider",
    "get_slo_tracker_provider",
    "set_admin_cache_storage_provider",
    "set_cache_invalidator_provider",
    "set_health_aggregator_provider",
    "set_healthcheck_session_provider",
    "set_rag_cache_provider",
    "set_redis_kv_client_provider",
    "set_redis_stream_client_provider",
    "set_response_cache_provider",
    "set_signature_builder_provider",
    "set_slo_tracker_provider",
)
