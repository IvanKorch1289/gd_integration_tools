"""Service-registry rule-engine ruleset'ов с in-memory кэшем.

Wave: ``[wave:s8/k3-rule-engine-finale]``. Один экземпляр на процесс
(регистрируется в DI). Загружает ruleset'ы из
:class:`RuleEngineRepository`, парсит YAML и кэширует. Опциональная
periodic-инвалидация контролируется feature flag
``rule_engine_hot_reload`` (default-OFF).

Поток данных:
    DSL ``evaluate_rules(ruleset="credit_scoring")``
        → :meth:`RuleEngineRegistry.get_active`
        → cache hit → return parsed dict
        → cache miss / TTL expired → repo.get → yaml.safe_load → cache → return.

Hot-reload (`rule_engine_hot_reload=True`):
    при каждом ``get_active`` проверяется ``_last_load[name]``;
    если прошло более :attr:`HOT_RELOAD_TTL_SECONDS` секунд — entry
    инвалидируется и перечитывается. Это lightweight-альтернатива
    подписке на pub/sub: без внешних зависимостей и threads.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from src.backend.core.config.features import FeatureFlags
    from src.backend.core.interfaces.rule_engine import RuleEngineRepository

__all__ = ("RuleEngineRegistry", "RulesetCacheEntry")

_logger = get_logger(__name__)

# Период hot-reload опроса; держим коротким (60с) — для credit-scoring
# ruleset'ов изменения должны разъезжаться по подам быстро.
HOT_RELOAD_TTL_SECONDS: float = 60.0


@dataclass
class RulesetCacheEntry:
    """Запись в in-memory кэше registry."""

    name: str
    version: str
    tenant_id: str | None
    parsed: dict[str, Any]
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class RuleEngineRegistry:
    """In-memory кэш ruleset'ов rule-engine с опциональным hot-reload.

    Args:
        repo: Реализация :class:`RuleEngineRepository`.
        feature_flags: Реестр feature flag'ов проекта.
        clock: Опц. callable, возвращающий ``datetime`` (для тестов
            детерминистично заменяет ``datetime.now(UTC)``).
    """

    def __init__(
        self,
        repo: RuleEngineRepository,
        feature_flags: FeatureFlags,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repo
        self._flags = feature_flags
        self._clock = clock or (lambda: datetime.now(UTC))
        # Ключ кэша: ``f"{name}|{tenant_id or '-'}"``.
        self._cache: dict[str, RulesetCacheEntry] = {}

    @staticmethod
    def _key(name: str, tenant_id: str | None) -> str:
        """Составной ключ кэша."""
        return f"{name}|{tenant_id or '-'}"

    def _is_stale(self, entry: RulesetCacheEntry) -> bool:
        """Проверяет, истёк ли TTL hot-reload."""
        if not self._flags.rule_engine_hot_reload:
            return False
        age = (self._clock() - entry.loaded_at).total_seconds()
        return age >= HOT_RELOAD_TTL_SECONDS

    async def get_active(
        self, name: str, *, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """Возвращает распарсенный ruleset по имени.

        Args:
            name: Имя ruleset'а (соответствует ``ruleset_name`` в YAML
                step ``evaluate_rules``).
            tenant_id: Опц. tenant scope.

        Returns:
            Распарсенный YAML-dict или ``None``, если запись не найдена /
            disabled.
        """
        key = self._key(name, tenant_id)
        cached = self._cache.get(key)
        if cached is not None and not self._is_stale(cached):
            return cached.parsed

        doc = await self._repo.get(name, tenant_id=tenant_id)
        if doc is None:
            # Инвалидируем устаревший cache, чтобы не возвращать stale
            # данные после удаления записи.
            self._cache.pop(key, None)
            return None

        parsed = yaml.safe_load(doc.yaml_body) or {}
        if not isinstance(parsed, dict):
            _logger.warning(
                "rule_engine ruleset %s/%s: YAML root не dict (%s) — игнорируется",
                name,
                doc.version,
                type(parsed).__name__,
            )
            return None

        entry = RulesetCacheEntry(
            name=name,
            version=doc.version,
            tenant_id=tenant_id,
            parsed=parsed,
            loaded_at=self._clock(),
        )
        self._cache[key] = entry
        return parsed

    def invalidate(self, name: str | None = None) -> int:
        """Очистить кэш по имени или полностью.

        Returns:
            Количество удалённых записей.
        """
        if name is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        prefix = f"{name}|"
        keys = [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            self._cache.pop(k, None)
        return len(keys)

    def cache_size(self) -> int:
        """Текущий размер кэша (для метрик / диагностики)."""
        return len(self._cache)
