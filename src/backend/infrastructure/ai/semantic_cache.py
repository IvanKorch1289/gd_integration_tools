"""Semantic cache + 3-tier router для AI-ответов (Sprint 3 W1 К4).

Модуль покрывает два связанных сценария:

* :class:`SemanticCache` — exact-match KV-кэш над Redis (по хэшу запроса).
  При появлении Qdrant-backend будет реализован настоящий semantic lookup
  по embedding-similarity (cosine ≥ threshold).
* :class:`TierRouter` — координатор L1 (in-proc LRU) → L2 (Redis exact) →
  L3 (semantic). Поддерживает write-through promotion: hit в нижнем tier
  поднимает запись во все верхние.

Метрики hit/miss/set публикуются через ``prometheus_client`` с labels
``{tier, op}`` (no-op fallback при отсутствии библиотеки).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.backend.infrastructure.cache.lru_cache import LruMemoryCache
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("SemanticCache", "TierRouter")

logger = get_logger("ai.semantic_cache")


# ---------------------------------------------------------------------------
# Метрики per-tier (lazy-init prometheus_client + plain dict snapshot).
# ---------------------------------------------------------------------------

_tier_counter: Any = None
_tier_initialized = False
_tier_snapshot: dict[str, dict[str, int]] = {
    "l1": {"hit": 0, "miss": 0, "set": 0},
    "l2": {"hit": 0, "miss": 0, "set": 0},
    "l3": {"hit": 0, "miss": 0, "set": 0},
}


def _ensure_tier_metrics() -> None:
    """Ленивая инициализация Prometheus Counter с labels (tier, op).

    Cardinality budget: 3 tier × 3 op = 9 уникальных серий. API
    ``cardinality_budget`` (К2-10) пока не merged — в этой версии
    используется placeholder noop fallback.
    """
    global _tier_counter, _tier_initialized
    if _tier_initialized:
        return
    try:
        from src.backend.infrastructure.observability.metrics_registry import (
            metrics_registry,
        )

        _tier_counter = metrics_registry.counter(
            "ai_tier_router_ops_total",
            "Операции TierRouter с labels (tier, op)",
            labels=("tier", "op"),
        )
    except ImportError:
        logger.debug("MetricsRegistry недоступен — TierRouter в no-op metrics")
    finally:
        _tier_initialized = True


def _record(tier: str, op: str) -> None:
    """Регистрирует операцию в Prometheus + локальном snapshot."""
    _ensure_tier_metrics()
    _tier_snapshot.setdefault(tier, {"hit": 0, "miss": 0, "set": 0})
    _tier_snapshot[tier][op] = _tier_snapshot[tier].get(op, 0) + 1
    if _tier_counter is not None:
        _tier_counter.labels(tier=tier, op=op).inc()


def get_tier_router_metrics() -> dict[str, dict[str, int]]:
    """Снимок счётчиков TierRouter (для admin-endpoint и тестов)."""
    return {tier: dict(ops) for tier, ops in _tier_snapshot.items()}


# ---------------------------------------------------------------------------
# Legacy SemanticCache — exact-match KV над Redis (готовится под Qdrant).
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SemanticCache:
    """Простая обёртка над Redis KV (строгий exact-match по хешу)
    с расчётом на будущий Qdrant-semantic-lookup.

    Attrs:
        threshold: порог similarity (cosine) для вторичного semantic-
            lookup; 1.0 = exact-match, 0.85 = similar.
        ttl_seconds: TTL entry в кеше.
    """

    prefix: str = "ai-cache:"
    threshold: float = 0.95
    ttl_seconds: int = 3600

    async def get(self, query: str) -> Any | None:
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )
        except ImportError:
            return None
        key = self._exact_key(query)
        raw = getattr(redis_client, "_raw_client", None) or redis_client
        try:
            v = await raw.get(key)
            return v
        except Exception as exc:
            logger.debug("SemanticCache get fail: %s", exc)
            return None

    async def set(self, query: str, value: str) -> None:
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )
        except ImportError:
            return
        key = self._exact_key(query)
        raw = getattr(redis_client, "_raw_client", None) or redis_client
        try:
            await raw.set(key, value, ex=self.ttl_seconds)
        except Exception as exc:
            logger.debug("SemanticCache set fail: %s", exc)

    def _exact_key(self, query: str) -> str:
        h = hashlib.sha256(query.encode("utf-8")).hexdigest()
        return f"{self.prefix}{h}"


# ---------------------------------------------------------------------------
# TierRouter — главный артефакт W1 К4 Шаг 2.
# ---------------------------------------------------------------------------


class TierRouter:
    """3-tier cache router с write-through promotion.

    Args:
        l1: In-process LRU кэш (обязателен). По умолчанию — пустой
            :class:`LruMemoryCache` с дефолтным TTL/max_size.
        l2: Redis-кэш (произвольный объект с async ``get``/``set``);
            обычно :class:`SemanticCache` или wrapper над redis_client.
            ``None`` → tier выключен.
        l3: Semantic кэш (тот же тип, что и L2, либо специализированный
            backend). Пишется только при наличии ``semantic_key`` в
            :meth:`set`. ``None`` → tier выключен.

    Принципы:
        * :meth:`get` — пытается L1 → L2 → L3. На hit в нижнем tier
          происходит promotion: запись копируется во все верхние tier.
        * :meth:`set` — пишет в L1 и L2 (если включён). L3 заполняется
          только при явном аргументе ``semantic_key``, иначе semantic-
          tier остаётся управляемым отдельным embed-pipeline.
        * Per-tier метрики ``(tier, op)`` — для расчёта hit-rate и
          диагностики "холодных" tier'ов.
    """

    def __init__(
        self,
        *,
        l1: LruMemoryCache | None = None,
        l2: Any | None = None,
        l3: Any | None = None,
    ) -> None:
        self._l1 = l1 or LruMemoryCache(scope="l1-tier-router")
        self._l2 = l2
        self._l3 = l3

    @property
    def l1(self) -> LruMemoryCache:
        """L1 (in-proc LRU) — read-only доступ для тестов и admin-endpoint."""
        return self._l1

    @property
    def l2(self) -> Any | None:
        """L2 (Redis) backend; ``None`` если tier выключен."""
        return self._l2

    @property
    def l3(self) -> Any | None:
        """L3 (semantic) backend; ``None`` если tier выключен."""
        return self._l3

    async def get(self, key: str) -> Any | None:
        """Возвращает значение, спускаясь по tier'ам сверху вниз.

        При hit в L2 — write-through в L1. При hit в L3 — write-through
        в L1 и L2. Метрики ``hit``/``miss`` инкрементируются для каждого
        проверенного tier.

        Args:
            key: Логический ключ записи (обычно SHA256 от запроса).

        Returns:
            Сохранённое значение либо ``None`` если miss во всех tier'ах.
        """
        # L1
        value = await self._l1.get(key)
        if value is not None:
            _record("l1", "hit")
            return value
        _record("l1", "miss")

        # L2
        if self._l2 is not None:
            value = await self._l2.get(key)
            if value is not None:
                _record("l2", "hit")
                # Promotion в L1.
                await self._l1.set(key, value)
                return value
            _record("l2", "miss")

        # L3
        if self._l3 is not None:
            value = await self._l3.get(key)
            if value is not None:
                _record("l3", "hit")
                # Promotion в L1 + L2 (если L2 включён).
                await self._l1.set(key, value)
                if self._l2 is not None:
                    await self._l2.set(key, value)
                return value
            _record("l3", "miss")

        return None

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl: int | None = None,
        semantic_key: str | None = None,
    ) -> None:
        """Сохраняет значение в L1 + L2 (всегда), в L3 — только при
        явном ``semantic_key``.

        Args:
            key: Логический ключ для L1/L2 (exact-match).
            value: Значение для записи (любой serialisable объект).
            ttl: Опциональный TTL override; для L1 игнорируется
                (использует TTL кэша из конструктора).
            semantic_key: Если задан — параллельно пишется в L3 как
                semantic-index (обычно сырая query, чтобы L3 мог
                считать embedding и хранить vector).
        """
        await self._l1.set(key, value, ttl=ttl)
        _record("l1", "set")
        if self._l2 is not None:
            await self._l2.set(key, value)
            _record("l2", "set")
        if self._l3 is not None and semantic_key is not None:
            await self._l3.set(semantic_key, value)
            _record("l3", "set")

    async def invalidate(self, *keys: str) -> None:
        """Удаляет ключ(и) во всех tier'ах (best-effort)."""
        if not keys:
            return
        await self._l1.invalidate(*keys)
        for backend in (self._l2, self._l3):
            if backend is None:
                continue
            delete = getattr(backend, "delete", None) or getattr(
                backend, "invalidate", None
            )
            if delete is None:
                continue
            try:
                await delete(*keys)
            except Exception as exc:
                logger.debug("TierRouter invalidate backend fail: %s", exc)

    @staticmethod
    def stats() -> dict[str, dict[str, int]]:
        """Снимок hit/miss/set-счётчиков (read-only)."""
        return get_tier_router_metrics()
