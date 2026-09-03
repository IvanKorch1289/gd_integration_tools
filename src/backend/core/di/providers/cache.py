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
    в ``setup_ai_stack.py`` при ``rag_cache_settings`` (default-OFF).
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
    """Установить override для ``redis_kv_client`` provider (test-инжекция)."""
    _overrides["redis_kv_client"] = client


# ─────────────── S60 M2-#11: high-level redis_client provider ───────────────


def get_redis_client_provider() -> Any:
    """Возвращает high-level :class:`RedisClient` wrapper.

    S60 M2-#11 (Sprint 48 swarm backlog): inline
    ``from src.backend.infrastructure.clients.storage.redis import redis_client``
    в DSL processors нарушает layer rule (DSL → infrastructure напрямую).
    Провайдер скрывает infrastructure layer от DSL.

    Использует lazy resolve_module — НЕ тянет redis при module import.
    """
    if "redis_client" in _overrides:
        return _overrides["redis_client"]
    module = resolve_module("clients.storage.redis")
    return module.redis_client


def set_redis_client_provider(client: Any) -> None:
    """Test-override для high-level redis_client wrapper (S60 M2-#11)."""
    _overrides["redis_client"] = client


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
    """Установить override для ``redis_stream_client`` provider (test-инжекция)."""
    _overrides["redis_stream_client"] = client


# ─────────────── HMAC signature builder ───────────────


def get_signature_builder_provider() -> Any:
    """Возвращает callable ``build_signature_headers`` (HMAC headers)."""
    if "signature_builder" in _overrides:
        return _overrides["signature_builder"]
    module = resolve_module("security.signatures")
    return module.build_signature_headers


def set_signature_builder_provider(builder: Any) -> None:
    """Установить override для ``signature_builder`` provider (test-инжекция)."""
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


# ─────────────── S165 W1: UnifiedCacheFacade (Rule 1, Rule 6) ───────────────


def get_cache_facade(enable_fallback: bool = True) -> Any:
    """Build UnifiedCacheFacade per active profile (Rule 1 single-entry).

    S165 W1: dev_light -> MemoryCacheFacade. prod -> Redis + fallback
    (deferred to S165 W2 when CB+pool for Redis wired).

    Pattern #18 (TTL+tag invalidation + fallback chain).
    """
    try:
        from src.backend.core.cache.facade import FallbackCacheFacade, MemoryCacheFacade
    except ImportError:
        return None

    memory = MemoryCacheFacade()
    if not enable_fallback:
        return memory
    return FallbackCacheFacade(primary=memory, fallback=memory)


# ─── S72 M2-#11 batch 7: HTTP transport (httpx) provider ───────────


def get_httpx_client_provider() -> Any:
    """Возвращает singleton :func:\`get_httpx_client\` (HTTP transport).

    S72 M2-#11 batch 7: lazy resolve для dsl/processors/graphql_query.py.
    Был inline: ``from src.backend.infrastructure.clients.transport.
    http_httpx import get_httpx_client`` (lazy inside method body).

    Использует lazy resolve_module — НЕ тянет httpx при module import.
    """
    if "httpx_client" in _overrides:
        return _overrides["httpx_client"]
    module = resolve_module("clients.transport.http_httpx")
    return module.get_httpx_client


def set_httpx_client_provider(client: Any) -> None:
    """Test-override для httpx client (Sprint 72+)."""
    _overrides["httpx_client"] = client


# ─── S73 M2-#11 batch 8: ReplyChannel (messaging) provider ───────────


def get_reply_channel_class_provider() -> Any:
    """Возвращает :class:\`ReplyChannel\` class (singleton via \`instance()\`).

    S73 M2-#11 batch 8: lazy resolve для dsl/processors/request_reply.py.
    ReplyChannel — class с classmethod \`instance()\` (singleton).
    Caller делает \`ReplyChannel.instance()\` для получения singleton.

    Использует lazy resolve_module — НЕ тянет messaging при module import.
    """
    if "reply_channel_class" in _overrides:
        return _overrides["reply_channel_class"]
    module = resolve_module("clients.messaging.reply_channel")
    return module.ReplyChannel


def set_reply_channel_class_provider(channel_class: Any) -> None:
    """Test-override для ReplyChannel class (Sprint 73+)."""
    _overrides["reply_channel_class"] = channel_class


# ─── S76 M2-#11 batch 11: RedisLock class provider ──────────────


def get_redis_lock_class_provider() -> Any:
    """Возвращает :class:\`RedisLock\` (distributed lock guard).

    S76 M2-#11 batch 11: lazy resolve для dsl/processors/redis_lock_processor.py.
    Был inline: ``from src.backend.infrastructure.clients.storage.redis_lock
    import RedisLock`` (lazy inside method body).

    Использует lazy resolve_module — НЕ тянет redis_lock при module import.
    """
    if "redis_lock_class" in _overrides:
        return _overrides["redis_lock_class"]
    module = resolve_module("clients.storage.redis_lock")
    return module.RedisLock


def set_redis_lock_class_provider(lock_class: Any) -> None:
    """Test-override для RedisLock class (Sprint 76+)."""
    _overrides["redis_lock_class"] = lock_class


# ─── S78 M2-#11 batch 13: S3 client provider ────────────────────


def get_s3_client_provider() -> Any:
    """Возвращает singleton S3 client (\`s3_client\`).

    S78 M2-#11 batch 13: lazy resolve для dsl/processors/{ingest,scan}_file.py.
    Был inline: ``from src.backend.infrastructure.clients.storage.s3_pool
    import s3_client`` (lazy inside method body).

    Использует lazy resolve_module — НЕ тянет s3_pool при module import.
    """
    if "s3_client" in _overrides:
        return _overrides["s3_client"]
    module = resolve_module("clients.storage.s3_pool")
    return module.s3_client


def set_s3_client_provider(client: Any) -> None:
    """Test-override для S3 client (Sprint 78+)."""
    _overrides["s3_client"] = client


# ─── S78 M2-#11 batch 13: antivirus + metrics providers ───────────


def get_antivirus_backend_factory_provider() -> Any:
    """Возвращает :func:\`create_antivirus_backend\` factory.

    S78 M2-#11 batch 13: lazy resolve для dsl/processors/scan_file.py.
    """
    if "antivirus_backend_factory" in _overrides:
        return _overrides["antivirus_backend_factory"]
    module = resolve_module("antivirus.factory")
    return module.create_antivirus_backend


def set_antivirus_backend_factory_provider(factory: Any) -> None:
    """Test-override для antivirus backend factory (Sprint 78+)."""
    _overrides["antivirus_backend_factory"] = factory


def get_record_antivirus_scan_provider() -> Any:
    """Возвращает :func:\`record_antivirus_scan\` (metrics emitter).

    S78 M2-#11 batch 13: lazy resolve для dsl/processors/scan_file.py.
    """
    if "record_antivirus_scan" in _overrides:
        return _overrides["record_antivirus_scan"]
    module = resolve_module("observability.metrics")
    return module.record_antivirus_scan


def set_record_antivirus_scan_provider(emitter: Any) -> None:
    """Test-override для record_antivirus_scan (Sprint 78+)."""
    _overrides["record_antivirus_scan"] = emitter


# ─── S79 M2-#11 batch 14: observability providers (ImmutableAuditStore) ──


def get_immutable_audit_store_class_provider() -> Any:
    """Возвращает :class:\`ImmutableAuditStore\` (audit store).

    S79 M2-#11 batch 14: lazy resolve для dsl/processors/audit.py.
    """
    if "immutable_audit_store_class" in _overrides:
        return _overrides["immutable_audit_store_class"]
    module = resolve_module("observability.immutable_audit")
    return module.ImmutableAuditStore


def set_immutable_audit_store_class_provider(aclass: Any) -> None:
    """Test-override для ImmutableAuditStore (Sprint 79+)."""
    _overrides["immutable_audit_store_class"] = aclass
