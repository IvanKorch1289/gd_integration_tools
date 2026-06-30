"""Per-tenant LLM token budget (Sprint 9 K4 W1).

Контракт :class:`TokenBudget`:

* ``soft_limit`` — при превышении логируется warning + Grafana-alert;
* ``hard_limit`` — при превышении вызывается ``BudgetExceeded`` и
  LLM-gateway возвращает 429 (см. K4 W2 integration).

Сам счётчик — Redis ``INCRBY`` с прецизионным TTL (``EXPIRE`` на reset-окно).
Reset-окно по умолчанию — ``daily`` (UTC midnight), но настраивается через
``period``.

Контракт :class:`TokenBudgetBackend` — Protocol, реализации:

* :class:`RedisTokenBudgetBackend` — production (Redis ``INCRBY`` + ``EXPIRE``);
* :class:`InMemoryTokenBudgetBackend` — для unit-тестов и dev_light.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "BudgetEnforcementError",
    "BudgetExceeded",
    "BudgetPeriod",
    "BudgetSnapshot",
    "InMemoryTokenBudgetBackend",
    "TokenBudget",
    "TokenBudgetBackend",
)


class BudgetExceeded(Exception):
    """Hard-limit превышен → caller получает 429."""

    def __init__(
        self, *, tenant_id: str, used: int, hard_limit: int, period: str
    ) -> None:
        super().__init__(
            f"Token budget exceeded for tenant={tenant_id}: "
            f"used={used} >= hard_limit={hard_limit} ({period})"
        )
        self.tenant_id = tenant_id
        self.used = used
        self.hard_limit = hard_limit
        self.period = period


class BudgetEnforcementError(Exception):
    """Поднимается endpoint-слою для маппинга в 429.

    ARC-005: этот класс — canonical home в ``core/tenancy/`` (рядом с
    :class:`BudgetExceeded`). Бывший импорт из
    ``src.backend.services.ai.gateway.budget_facade`` нарушал layer
    policy (core → services). S172 M6 re-home.

    Attributes:
        body: JSON-ready payload (см. :func:`render_429` в
        ``core.tenancy.budget_enforcer``).
    """

    def __init__(self, *, body: dict[str, Any]) -> None:
        super().__init__(body.get("message", "token_budget_exceeded"))
        self.body = body


class BudgetPeriod:
    """Константы reset-окна."""

    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"

    _TTL_SECONDS = {HOURLY: 3600, DAILY: 86400, MONTHLY: 30 * 86400}

    @classmethod
    def ttl_seconds(cls, period: str) -> int:
        """TTL для Redis-ключа в зависимости от периода."""
        ttl = cls._TTL_SECONDS.get(period)
        if ttl is None:
            raise ValueError(f"Unknown budget period: {period!r}")
        return ttl


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Срез состояния бюджета для UI / API.

    Attributes:
        tenant_id: ID tenant'а.
        period: reset-окно (hourly/daily/monthly).
        used: токенов потрачено за текущее окно.
        soft_limit: warning threshold.
        hard_limit: hard threshold (429 после превышения).
        remaining: hard_limit - used (>=0).
        soft_breached: used >= soft_limit.
        hard_breached: used >= hard_limit.
    """

    tenant_id: str
    period: str
    used: int
    soft_limit: int
    hard_limit: int

    @property
    def remaining(self) -> int:
        """Сколько токенов ещё доступно в рамках hard limit.

        Returns:
            ``max(0, hard_limit - used)`` — не уходит в минус при over-usage.
        """
        return max(0, self.hard_limit - self.used)

    @property
    def soft_breached(self) -> bool:
        """Превышен ли soft limit (рекомендация к throttling'у).

        Returns:
            ``True`` если ``used >= soft_limit`` (тенант близок к исчерпанию).
        """
        return self.used >= self.soft_limit

    @property
    def hard_breached(self) -> bool:
        """Превышен ли hard limit (требуется reject).

        Returns:
            ``True`` если ``used >= hard_limit`` (запросы должны быть отвергнуты).
        """
        return self.used >= self.hard_limit


@runtime_checkable
class TokenBudgetBackend(Protocol):
    """Контракт счётчика токенов (Redis / in-memory)."""

    async def increment(self, *, key: str, amount: int, ttl_seconds: int) -> int:
        """Атомарно увеличить счётчик; вернуть новое значение."""
        ...

    async def get(self, *, key: str) -> int:
        """Текущее значение (0 если нет)."""
        ...

    async def reset(self, *, key: str) -> None:
        """Сбросить счётчик (для admin-action)."""
        ...


class InMemoryTokenBudgetBackend:
    """In-memory backend для unit-тестов и dev_light."""

    def __init__(self) -> None:
        self._store: dict[str, int] = {}

    async def increment(self, *, key: str, amount: int, ttl_seconds: int) -> int:
        """Атомарно увеличить счётчик ``key`` на ``amount``.

        Args:
            key: Полный ключ счётчика (например ``budget:tenant42:chat``).
            amount: На сколько увеличить (может быть > 1 для batch-операций).
            ttl_seconds: TTL ключа; in-memory backend игнорирует, Redis
                бэкенд применяет ``EXPIRE``.

        Returns:
            Новое значение счётчика после инкремента.
        """
        del ttl_seconds  # in-memory не поддерживает TTL
        self._store[key] = self._store.get(key, 0) + amount
        return self._store[key]

    async def get(self, *, key: str) -> int:
        """Возвращает текущее значение счётчика для ``key``.

        Args:
            key: Ключ счётчика (например, ``"tenant:42:tokens"``).

        Returns:
            Текущее значение; ``0`` если ключ отсутствует.
        """
        return self._store.get(key, 0)

    async def reset(self, *, key: str) -> None:
        """Сбрасывает счётчик для ``key`` (no-op если отсутствует).

        Args:
            key: Ключ счётчика.
        """
        self._store.pop(key, None)


@dataclass(frozen=True, slots=True)
class TokenBudgetConfig:
    """Конфигурация бюджета для конкретного tenant'а.

    Attributes:
        soft_limit: warning threshold (логирование, alert).
        hard_limit: hard threshold (429 после превышения).
        period: reset-окно (см. :class:`BudgetPeriod`).
        fail_mode: Что делать при Redis-outage:
            ``open`` (default) — пропускать запросы без учёта;
            ``closed`` — блокировать запросы (fail-safe).
    """

    soft_limit: int
    hard_limit: int
    period: str = BudgetPeriod.DAILY
    fail_mode: str = "open"


class TokenBudget:
    """High-level facade: учитывает токены + бросает :class:`BudgetExceeded`.

    Args:
        backend: реализация счётчика.
        configs: per-tenant конфиги (если tenant не найден → fall back на
            ``default_config``).
        default_config: fallback для tenant'ов без явной конфигурации.
    """

    def __init__(
        self,
        *,
        backend: TokenBudgetBackend,
        configs: dict[str, TokenBudgetConfig] | None = None,
        default_config: TokenBudgetConfig,
    ) -> None:
        self._backend = backend
        self._configs = configs or {}
        self._default = default_config

    def _config_for(self, tenant_id: str) -> TokenBudgetConfig:
        return self._configs.get(tenant_id, self._default)

    def _key(self, tenant_id: str, period: str) -> str:
        now = datetime.now(UTC)
        bucket = {
            BudgetPeriod.HOURLY: now.strftime("%Y%m%d-%H"),
            BudgetPeriod.DAILY: now.strftime("%Y%m%d"),
            BudgetPeriod.MONTHLY: now.strftime("%Y%m"),
        }.get(period, now.strftime("%Y%m%d"))
        return f"token-budget:{tenant_id}:{period}:{bucket}"

    async def reserve(self, *, tenant_id: str, tokens: int) -> BudgetSnapshot:
        """Зарезервировать ``tokens`` под предстоящий LLM-вызов.

        Должна вызываться ДО LLM-вызова — иначе hard_limit не работает.

        Raises:
            BudgetExceeded: если used >= hard_limit.
        """
        config = self._config_for(tenant_id)
        key = self._key(tenant_id, config.period)
        ttl = BudgetPeriod.ttl_seconds(config.period)
        try:
            used = await self._backend.increment(
                key=key, amount=tokens, ttl_seconds=ttl
            )
        except Exception as _:
            if config.fail_mode == "closed":
                raise
            # fail-open: пропускаем, бюджет не учитывается
            used = 0
        snapshot = BudgetSnapshot(
            tenant_id=tenant_id,
            period=config.period,
            used=used,
            soft_limit=config.soft_limit,
            hard_limit=config.hard_limit,
        )
        if snapshot.hard_breached:
            raise BudgetExceeded(
                tenant_id=tenant_id,
                used=used,
                hard_limit=config.hard_limit,
                period=config.period,
            )
        return snapshot

    async def snapshot(self, *, tenant_id: str) -> BudgetSnapshot:
        """Получить текущий срез без модификации счётчика."""
        config = self._config_for(tenant_id)
        key = self._key(tenant_id, config.period)
        used = await self._backend.get(key=key)
        return BudgetSnapshot(
            tenant_id=tenant_id,
            period=config.period,
            used=used,
            soft_limit=config.soft_limit,
            hard_limit=config.hard_limit,
        )

    async def reset(self, *, tenant_id: str) -> None:
        """Admin-action: сбросить счётчик текущего периода."""
        config = self._config_for(tenant_id)
        key = self._key(tenant_id, config.period)
        await self._backend.reset(key=key)
