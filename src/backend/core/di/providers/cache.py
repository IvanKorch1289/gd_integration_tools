"""Cache domain providers — invalidation, response/RAG/redis caches.

W9 P2-13 Phase 2 (cycle 153, MINIMAX plan): сокращён с 868 LOC (89 funcs в 26
concerns) до ~370 LOC (8 cache concerns + back-compat re-exports для
перемещённых functions).

History:
- Wave 6.2 (pre-split): один файл ``providers.py`` с 114 функциями.
- S38 P1.2c: ``_impl.py`` → 6 domain files (cache.py 20 funcs, db, http,
  ai, auth, workflow).
- S36-W23: + ``storage.py``.
- M2-#11 batch 7-19: providers добавлялись в cache.py вместо proper domain
  files → drift до 89 funcs в 26 concerns (god-module anti-pattern).
- **W9 P2-13 Phase 2**: misattributed providers перенесены в proper domains
  (``observability``, ``security``, ``db``, ``ai``, ``workflow``); cache.py
  стал thin back-compat shim. См. ADR-0321.

Back-compat: ``from src.backend.core.di.providers.cache import get_X_provider``
продолжает работать через:
1. Inline definitions для cache-only functions (canonical implementation,
   общий ``_overrides`` с cache domain).
2. Re-exports для перемещённых functions — вызов делегируется в canonical
   domain module (там же его ``_overrides``).

**Дубликаты** (4 пары с разной логикой): object_storage, ai_sanitizer,
smtp_client, stream_client — требуют factory-vs-instance API fix перед
merge canonical implementations (отложено в Phase 2B, см. ADR-0321).

Singleton cache ``_overrides`` is per-domain (NOT shared) — каждый domain
имеет свой override-словарь для изоляции тестов.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

# Back-compat re-exports (W9 split; impl в ai/http/storage) — import-surface прежний
from src.backend.core.di.providers.ai import (  # noqa: E402
    get_ai_sanitizer_provider as get_ai_sanitizer_provider,
)
from src.backend.core.di.providers.http import (  # noqa: E402
    get_smtp_client_provider as get_smtp_client_provider,
)
from src.backend.core.di.providers.http import (
    get_stream_client_provider as get_stream_client_provider,
)
from src.backend.core.di.providers.storage import (  # noqa: E402
    get_object_storage_provider as get_object_storage_provider,
)

get_s3_storage_client_provider = (
    get_object_storage_provider  # S3/MinIO/LocalFS singleton
)
from src.backend.core.di.providers.ai import (
    get_token_registry_provider as get_token_registry_provider,
)
from src.backend.core.di.providers.ai import (
    get_vector_store_provider as get_vector_store_provider,
)
from src.backend.core.di.providers.ai import (
    set_token_registry_provider as set_token_registry_provider,
)
from src.backend.core.di.providers.ai import (
    set_vector_store_provider as set_vector_store_provider,
)
from src.backend.core.di.providers.db import (
    get_db_manager_provider as get_db_manager_provider,
)
from src.backend.core.di.providers.db import (
    set_db_manager_provider as set_db_manager_provider,
)
from src.backend.core.di.providers.http import (
    get_http_client_dependency_provider as get_http_client_dependency_provider,
)
from src.backend.core.di.providers.http import (
    get_http_client_typed_provider as get_http_client_typed_provider,
)
from src.backend.core.di.providers.http import (
    get_httpx_client_provider as get_httpx_client_provider,
)
from src.backend.core.di.providers.http import (
    get_stream_provider as get_stream_provider,
)
from src.backend.core.di.providers.http import (
    set_http_client_dependency_provider as set_http_client_dependency_provider,
)
from src.backend.core.di.providers.http import (
    set_http_client_typed_provider as set_http_client_typed_provider,
)
from src.backend.core.di.providers.http import (
    set_httpx_client_provider as set_httpx_client_provider,
)
from src.backend.core.di.providers.http import (
    set_stream_provider as set_stream_provider,
)
from src.backend.core.di.providers.messaging import (
    get_express_bot_module_provider as get_express_bot_module_provider,
)
from src.backend.core.di.providers.messaging import (
    get_express_dialogs_mongo_provider as get_express_dialogs_mongo_provider,
)
from src.backend.core.di.providers.messaging import (
    get_telegram_bot_provider as get_telegram_bot_provider,
)
from src.backend.core.di.providers.messaging import (
    set_express_bot_module_provider as set_express_bot_module_provider,
)
from src.backend.core.di.providers.messaging import (
    set_express_dialogs_mongo_provider as set_express_dialogs_mongo_provider,
)
from src.backend.core.di.providers.messaging import (
    set_telegram_bot_provider as set_telegram_bot_provider,
)
from src.backend.core.di.providers.observability import (
    get_health_aggregator_provider as get_health_aggregator_provider,
)
from src.backend.core.di.providers.observability import (
    get_immutable_audit_store_class_provider as get_immutable_audit_store_class_provider,
)
from src.backend.core.di.providers.observability import (
    get_record_antivirus_scan_provider as get_record_antivirus_scan_provider,
)
from src.backend.core.di.providers.observability import (
    get_record_express_message_sent_provider as get_record_express_message_sent_provider,
)
from src.backend.core.di.providers.observability import (
    get_slo_tracker_provider as get_slo_tracker_provider,
)
from src.backend.core.di.providers.observability import (
    set_health_aggregator_provider as set_health_aggregator_provider,
)
from src.backend.core.di.providers.observability import (
    set_immutable_audit_store_class_provider as set_immutable_audit_store_class_provider,
)
from src.backend.core.di.providers.observability import (
    set_record_antivirus_scan_provider as set_record_antivirus_scan_provider,
)
from src.backend.core.di.providers.observability import (
    set_record_express_message_sent_provider as set_record_express_message_sent_provider,
)
from src.backend.core.di.providers.observability import (
    set_slo_tracker_provider as set_slo_tracker_provider,
)
from src.backend.core.di.providers.security import (
    get_antivirus_backend_factory_provider as get_antivirus_backend_factory_provider,
)
from src.backend.core.di.providers.security import (
    get_signature_builder_provider as get_signature_builder_provider,
)
from src.backend.core.di.providers.security import (
    get_vault_backend_class_provider as get_vault_backend_class_provider,
)
from src.backend.core.di.providers.security import (
    get_vault_config_class_provider as get_vault_config_class_provider,
)
from src.backend.core.di.providers.security import (
    set_antivirus_backend_factory_provider as set_antivirus_backend_factory_provider,
)
from src.backend.core.di.providers.security import (
    set_signature_builder_provider as set_signature_builder_provider,
)
from src.backend.core.di.providers.security import (
    set_vault_backend_class_provider as set_vault_backend_class_provider,
)
from src.backend.core.di.providers.security import (
    set_vault_config_class_provider as set_vault_config_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_di_bridge_dlq_module_provider as get_di_bridge_dlq_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_dlq_envelope_class_provider as get_dlq_envelope_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_dlq_memory_writer_module_provider as get_dlq_memory_writer_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_grpc_sink_class_provider as get_grpc_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_mq_sink_class_provider as get_mq_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_notifications_module_provider as get_notifications_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_reply_channel_class_provider as get_reply_channel_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_sink_factory_provider as get_sink_factory_provider,
)
from src.backend.core.di.providers.workflow import (
    get_soap_sink_class_provider as get_soap_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_factory_module_provider as get_workflow_factory_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_ws_sink_class_provider as get_ws_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_di_bridge_dlq_module_provider as set_di_bridge_dlq_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_dlq_envelope_class_provider as set_dlq_envelope_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_dlq_memory_writer_module_provider as set_dlq_memory_writer_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_grpc_sink_class_provider as set_grpc_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_mq_sink_class_provider as set_mq_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_notifications_module_provider as set_notifications_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_reply_channel_class_provider as set_reply_channel_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_sink_factory_provider as set_sink_factory_provider,
)
from src.backend.core.di.providers.workflow import (
    set_soap_sink_class_provider as set_soap_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_factory_module_provider as set_workflow_factory_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_ws_sink_class_provider as set_ws_sink_class_provider,
)

_overrides: dict[str, Any] = {}


# ─────────────── Cache invalidator (canonical, stays in cache.py) ───────────────


def get_cache_invalidator_provider() -> Any:
    """Возвращает глобальный CacheInvalidator (см. ``core.interfaces.admin_cache``)."""
    if "cache_invalidator" in _overrides:
        return _overrides["cache_invalidator"]
    module = resolve_module("cache")
    return module.get_cache_invalidator()


def set_cache_invalidator_provider(invalidator: Any) -> None:
    """Установить override для ``cache_invalidator`` provider (test-инжекция)."""
    _overrides["cache_invalidator"] = invalidator


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
    """Установить override для ``response_cache`` provider (test-инжекция)."""
    _overrides["response_cache"] = decorator


# ─────────────── Wave S32 W4: ThreeTierRagCache provider ───────────────


def get_rag_cache_provider() -> Any:
    """Возвращает ``ThreeTierRagCache`` (3-tier RAG cache).

    Tiers: L1 (in-process LRU) → L2 (Redis) → L3 (Qdrant collection).
    """
    if "rag_cache" in _overrides:
        return _overrides["rag_cache"]
    module = resolve_module("cache.rag.three_tier")
    return module.ThreeTierRagCache


def set_rag_cache_provider(impl: Any) -> None:
    """Установить override для ``rag_cache`` provider (test-инжекция)."""
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
    """Test-override для Redis KV client."""
    _overrides["redis_kv_client"] = client


# ─────────────── S60 M2-#11: high-level redis_client provider ───────────────


def get_redis_client_provider() -> Any:
    """Возвращает high-level Redis client (singleton facade)."""
    if "redis_client" in _overrides:
        return _overrides["redis_client"]
    module = resolve_module("clients.storage.redis")
    return module.redis_client  # lazy module attr (back-compat, 2026-09-23)


def set_redis_client_provider(client: Any) -> None:
    """Test-override для Redis client (S60+)."""
    _overrides["redis_client"] = client


def get_redis_stream_client_provider() -> Any:
    """Возвращает Redis streams client (singleton)."""
    if "redis_stream_client" in _overrides:
        return _overrides["redis_stream_client"]
    module = resolve_module("clients.storage.redis_streams")
    return module.redis_stream_client


def set_redis_stream_client_provider(client: Any) -> None:
    """Test-override для Redis streams client."""
    _overrides["redis_stream_client"] = client


# ─── S76 M2-#11 batch 11: RedisLock class provider ──────────────


def get_redis_lock_class_provider() -> Any:
    r"""Возвращает :class:\`RedisLock\` (distributed lock guard).

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


__all__ = (
    # ── Cache canonical (inline implementations) ──
    "get_admin_cache_storage_provider",
    "get_cache_facade",
    "get_cache_invalidator_provider",
    "get_rag_cache_provider",
    "get_redis_client_provider",
    "get_redis_kv_client_provider",
    "get_redis_lock_class_provider",
    "get_redis_stream_client_provider",
    "get_response_cache_provider",
    "set_admin_cache_storage_provider",
    "set_cache_invalidator_provider",
    "set_rag_cache_provider",
    "set_redis_client_provider",
    "set_redis_kv_client_provider",
    "set_redis_lock_class_provider",
    "set_redis_stream_client_provider",
    "set_response_cache_provider",
    # ── Observability re-exports (W9 P2-13 Phase 2) ──
    "get_health_aggregator_provider",
    "get_immutable_audit_store_class_provider",
    "get_record_antivirus_scan_provider",
    "get_record_express_message_sent_provider",
    "get_slo_tracker_provider",
    "set_health_aggregator_provider",
    "set_immutable_audit_store_class_provider",
    "set_record_antivirus_scan_provider",
    "set_record_express_message_sent_provider",
    "set_slo_tracker_provider",
    # ── Security re-exports (W9 P2-13 Phase 2) ──
    "get_antivirus_backend_factory_provider",
    "get_signature_builder_provider",
    "get_vault_backend_class_provider",
    "get_vault_config_class_provider",
    "set_antivirus_backend_factory_provider",
    "set_signature_builder_provider",
    "set_vault_backend_class_provider",
    "set_vault_config_class_provider",
    # ── DB re-export (W9 P2-13 Phase 2) ──
    "get_db_manager_provider",
    "set_db_manager_provider",
    # ── HTTP re-exports (W9 P2-13 Phase 2) ──
    "get_http_client_dependency_provider",
    "get_http_client_typed_provider",
    "get_httpx_client_provider",
    "get_stream_provider",
    "set_http_client_dependency_provider",
    "set_http_client_typed_provider",
    "set_httpx_client_provider",
    "set_stream_provider",
    # ── AI re-exports (W9 P2-13 Phase 2) ──
    "get_token_registry_provider",
    "get_vector_store_provider",
    "set_token_registry_provider",
    "set_vector_store_provider",
    # ── Messaging re-exports (W9 P2-13 Phase 2) ──
    "get_express_bot_module_provider",
    "get_express_dialogs_mongo_provider",
    "get_telegram_bot_provider",
    "set_express_bot_module_provider",
    "set_express_dialogs_mongo_provider",
    "set_telegram_bot_provider",
    # ── Workflow re-exports (W9 P2-13 Phase 2: workflow_factory, notifications,
    #    sinks, reply_channel, DLQ) ──
    "get_di_bridge_dlq_module_provider",
    "get_dlq_envelope_class_provider",
    "get_dlq_memory_writer_module_provider",
    "get_grpc_sink_class_provider",
    "get_mq_sink_class_provider",
    "get_notifications_module_provider",
    "get_reply_channel_class_provider",
    "get_sink_factory_provider",
    "get_soap_sink_class_provider",
    "get_workflow_factory_module_provider",
    "get_ws_sink_class_provider",
    "set_di_bridge_dlq_module_provider",
    "set_dlq_envelope_class_provider",
    "set_dlq_memory_writer_module_provider",
    "set_grpc_sink_class_provider",
    "set_mq_sink_class_provider",
    "set_notifications_module_provider",
    "set_reply_channel_class_provider",
    "set_sink_factory_provider",
    "set_soap_sink_class_provider",
    "set_workflow_factory_module_provider",
    "set_ws_sink_class_provider",
)
