"""QuotasService — per-tenant billing/quotas tracking (Sprint 7 K1).

Назначение:
    Учёт потребления per-tenant в скользящих окнах:
        - ``max_rpm`` — requests per minute,
        - ``max_rpd`` — requests per day,
        - ``max_tokens_per_request`` — лимит токенов на один запрос,
        - ``cost_budget_usd`` — суточный бюджет в USD на LLM-cost.

    Реализация поверх Redis (если доступен) с graceful fallback в in-memory
    режим (для unit-тестов / dev_light). Все операции — fail-open: при
    недоступности backend разрешают запрос с warning'ом в лог (поведение
    соответствует ``core/tenancy/quotas.py:QuotaTracker``).

Default-OFF:
    Контролируется feature_flag ``per_tenant_billing_enabled``. При False
    все методы возвращают :class:`QuotaCheckResult` с ``allowed=True`` и
    нулевым потреблением.

Принципы реализации (V15):
    - 80% библиотечно: Redis INCRBY + EXPIRE без custom-логики;
    - не зависит от infrastructure/ напрямую — клиент Redis импортируется
      lazy через try/except;
    - все timestamp — через ``time.time()`` (UTC unix).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

__all__ = ("QuotaCheckResult", "QuotaUsage", "QuotaWindow", "QuotasService")

_logger = logging.getLogger("services.billing.quotas")

# Длительности окон (секунды).
_MINUTE_SECONDS = 60
_DAY_SECONDS = 86_400


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    """Лимиты на одно tenant-окно.

    Attributes:
        max_rpm: Максимум запросов в минуту (0 — без лимита).
        max_rpd: Максимум запросов в сутки (0 — без лимита).
        max_tokens_per_request: Лимит токенов на один запрос (0 — без лимита).
        cost_budget_usd: Суточный USD-бюджет на LLM-cost (0.0 — без лимита).
    """

    max_rpm: int = 0
    max_rpd: int = 0
    max_tokens_per_request: int = 0
    cost_budget_usd: float = 0.0


@dataclass(slots=True)
class QuotaUsage:
    """Снимок текущего потребления одного tenant.

    Attributes:
        tenant_id: Идентификатор арендатора.
        requests_in_minute: Запросов в текущем минутном окне.
        requests_in_day: Запросов в текущем суточном окне.
        cost_in_day_usd: Накопленный USD-cost за текущие сутки.
        reset_minute_at: Unix-timestamp сброса минутного окна.
        reset_day_at: Unix-timestamp сброса суточного окна.
    """

    tenant_id: str
    requests_in_minute: int = 0
    requests_in_day: int = 0
    cost_in_day_usd: float = 0.0
    reset_minute_at: int = 0
    reset_day_at: int = 0


@dataclass(frozen=True, slots=True)
class QuotaCheckResult:
    """Результат одной проверки квоты.

    Attributes:
        allowed: True, если запрос разрешён.
        reason: Текстовое объяснение (пустое при allowed=True).
        usage: Снимок текущего потребления.
    """

    allowed: bool
    reason: str
    usage: QuotaUsage


class QuotasService:
    """Сервис per-tenant billing/quotas.

    Lazy-Redis: клиент берётся при первом обращении; при недоступности —
    in-memory fallback (только текущий процесс, не persistent).

    Args:
        default_window: QuotaWindow по умолчанию (для tenant без overrides).
        redis_prefix: Префикс ключей Redis (``billing:`` по умолчанию).
        per_tenant_windows: Опциональный mapping tenant_id → QuotaWindow.
    """

    def __init__(
        self,
        *,
        default_window: QuotaWindow | None = None,
        redis_prefix: str = "billing:",
        per_tenant_windows: dict[str, QuotaWindow] | None = None,
    ) -> None:
        """Инициализирует сервис с дефолтным окном и опциональными overrides."""
        self.default_window = default_window or QuotaWindow()
        self.redis_prefix = redis_prefix
        self._per_tenant: dict[str, QuotaWindow] = dict(per_tenant_windows or {})
        # In-memory fallback (используется только если Redis недоступен).
        self._memory_counts: dict[str, dict[str, float]] = {}

    # ── Public API ─────────────────────────────────────────────────────

    def window_for(self, tenant_id: str) -> QuotaWindow:
        """Возвращает QuotaWindow для tenant (override или default).

        Args:
            tenant_id: Идентификатор арендатора.

        Returns:
            Совпадает с per-tenant override; иначе default_window.
        """
        return self._per_tenant.get(tenant_id, self.default_window)

    async def consume_request(self, tenant_id: str) -> QuotaCheckResult:
        """Регистрирует один запрос и проверяет лимиты rpm/rpd.

        При выключенном feature_flag ``per_tenant_billing_enabled`` — no-op
        (allowed=True).

        Args:
            tenant_id: Идентификатор арендатора.

        Returns:
            QuotaCheckResult с пометкой allowed/denied.
        """
        if not self._enabled():
            return self._allow_no_op(tenant_id)
        window = self.window_for(tenant_id)
        now = int(time.time())
        minute_count = await self._incr_window(
            tenant_id, "rpm", now, _MINUTE_SECONDS, 1
        )
        day_count = await self._incr_window(tenant_id, "rpd", now, _DAY_SECONDS, 1)
        usage = QuotaUsage(
            tenant_id=tenant_id,
            requests_in_minute=int(minute_count),
            requests_in_day=int(day_count),
            cost_in_day_usd=0.0,
            reset_minute_at=now - (now % _MINUTE_SECONDS) + _MINUTE_SECONDS,
            reset_day_at=now - (now % _DAY_SECONDS) + _DAY_SECONDS,
        )
        if window.max_rpm > 0 and minute_count > window.max_rpm:
            return QuotaCheckResult(
                allowed=False,
                reason=f"rpm exceeded: {int(minute_count)}/{window.max_rpm}",
                usage=usage,
            )
        if window.max_rpd > 0 and day_count > window.max_rpd:
            return QuotaCheckResult(
                allowed=False,
                reason=f"rpd exceeded: {int(day_count)}/{window.max_rpd}",
                usage=usage,
            )
        return QuotaCheckResult(allowed=True, reason="", usage=usage)

    async def check_tokens(self, tenant_id: str, tokens: int) -> QuotaCheckResult:
        """Проверяет лимит токенов на один запрос (без инкремента).

        Args:
            tenant_id: Идентификатор арендатора.
            tokens: Количество токенов в текущем запросе.

        Returns:
            QuotaCheckResult с пометкой allowed/denied.
        """
        if not self._enabled():
            return self._allow_no_op(tenant_id)
        window = self.window_for(tenant_id)
        usage = QuotaUsage(tenant_id=tenant_id)
        if window.max_tokens_per_request > 0 and tokens > window.max_tokens_per_request:
            return QuotaCheckResult(
                allowed=False,
                reason=(
                    f"tokens_per_request exceeded: "
                    f"{tokens}/{window.max_tokens_per_request}"
                ),
                usage=usage,
            )
        return QuotaCheckResult(allowed=True, reason="", usage=usage)

    async def consume_cost(self, tenant_id: str, cost_usd: float) -> QuotaCheckResult:
        """Регистрирует USD-cost и проверяет суточный бюджет.

        Args:
            tenant_id: Идентификатор арендатора.
            cost_usd: Стоимость текущего LLM-запроса в USD.

        Returns:
            QuotaCheckResult с пометкой allowed/denied.
        """
        if not self._enabled():
            return self._allow_no_op(tenant_id)
        window = self.window_for(tenant_id)
        now = int(time.time())
        # Cost трекается с точностью до 6 знаков (микро-USD) через
        # умножение на 1_000_000 и хранение как int в INCRBY.
        units = max(0, int(round(cost_usd * 1_000_000)))
        accumulated_micro = await self._incr_window(
            tenant_id, "cost_usd", now, _DAY_SECONDS, units
        )
        cost_in_day = accumulated_micro / 1_000_000.0
        usage = QuotaUsage(
            tenant_id=tenant_id,
            cost_in_day_usd=cost_in_day,
            reset_day_at=now - (now % _DAY_SECONDS) + _DAY_SECONDS,
        )
        if window.cost_budget_usd > 0 and cost_in_day > window.cost_budget_usd:
            return QuotaCheckResult(
                allowed=False,
                reason=(
                    f"cost_budget_usd exceeded: "
                    f"{cost_in_day:.4f}/{window.cost_budget_usd:.4f}"
                ),
                usage=usage,
            )
        return QuotaCheckResult(allowed=True, reason="", usage=usage)

    async def usage_snapshot(self, tenant_id: str) -> QuotaUsage:
        """Возвращает текущий снимок потребления без инкрементов.

        Args:
            tenant_id: Идентификатор арендатора.

        Returns:
            QuotaUsage со всеми накопителями (минута / день / cost).
        """
        now = int(time.time())
        return QuotaUsage(
            tenant_id=tenant_id,
            requests_in_minute=int(
                await self._read_window(tenant_id, "rpm", now, _MINUTE_SECONDS)
            ),
            requests_in_day=int(
                await self._read_window(tenant_id, "rpd", now, _DAY_SECONDS)
            ),
            cost_in_day_usd=(
                await self._read_window(tenant_id, "cost_usd", now, _DAY_SECONDS)
            )
            / 1_000_000.0,
            reset_minute_at=now - (now % _MINUTE_SECONDS) + _MINUTE_SECONDS,
            reset_day_at=now - (now % _DAY_SECONDS) + _DAY_SECONDS,
        )

    # ── Internal ───────────────────────────────────────────────────────

    @staticmethod
    def _enabled() -> bool:
        """True, если feature_flag ``per_tenant_billing_enabled`` включён."""
        try:
            from src.backend.core.config.features import feature_flags  # noqa: PLC0415

            return bool(getattr(feature_flags, "per_tenant_billing_enabled", False))
        except Exception:  # noqa: BLE001 — fallback default-OFF
            return False

    @staticmethod
    def _allow_no_op(tenant_id: str) -> QuotaCheckResult:
        """Результат no-op (feature_flag выключен) — allowed=True."""
        return QuotaCheckResult(
            allowed=True, reason="", usage=QuotaUsage(tenant_id=tenant_id)
        )

    def _window_key(self, tenant_id: str, resource: str, window_start: int) -> str:
        """Собирает Redis-ключ для одного tenant/resource/window."""
        return f"{self.redis_prefix}{tenant_id}:{resource}:{window_start}"

    async def _get_redis(self) -> Any | None:
        """Lazy-возврат Redis-клиента (raw) или None при недоступности.

        Fail-open: при любой ошибке импорта/инициализации (например, в
        unit-тестах без DB-настроек) возвращает None — сервис работает
        через in-memory fallback.

        Duck-type проверка: возвращаем клиента только если у него есть
        ``incrby`` / ``expire`` / ``get`` (raw ``redis.asyncio.Redis``).
        Высокоуровневые обёртки без этих методов трактуются как
        отсутствие Redis — активирует in-memory fallback.
        """
        try:
            from src.backend.infrastructure.clients.storage.redis import (  # noqa: PLC0415
                redis_client,
            )
        except Exception:  # noqa: BLE001 — fail-open для unit-тестов / dev_light
            return None
        candidate = getattr(redis_client, "_raw_client", None) or redis_client
        if not all(
            callable(getattr(candidate, m, None)) for m in ("incrby", "expire", "get")
        ):
            return None
        return candidate

    async def _incr_window(
        self, tenant_id: str, resource: str, now: int, period_seconds: int, units: int
    ) -> float:
        """Инкрементирует счётчик в текущем окне и возвращает новое значение.

        Fail-open: при отсутствии Redis использует in-memory dict.
        """
        window_start = now - (now % period_seconds)
        key = self._window_key(tenant_id, resource, window_start)
        raw = await self._get_redis()
        if raw is None:
            current = self._memory_counts.setdefault(key, {"v": 0.0})
            current["v"] = float(current.get("v", 0.0)) + units
            return float(current["v"])
        try:
            value = await raw.incrby(key, units)
            await raw.expire(key, period_seconds)
            return float(value)
        except Exception as exc:  # noqa: BLE001 — fail-open
            _logger.warning("Redis quota incr failed (fail-open): %s", exc)
            return float(units)

    async def _read_window(
        self, tenant_id: str, resource: str, now: int, period_seconds: int
    ) -> float:
        """Читает текущее значение счётчика без инкремента."""
        window_start = now - (now % period_seconds)
        key = self._window_key(tenant_id, resource, window_start)
        raw = await self._get_redis()
        if raw is None:
            return float(self._memory_counts.get(key, {"v": 0.0}).get("v", 0.0))
        try:
            value = await raw.get(key)
            if value is None:
                return 0.0
            return float(value)
        except Exception as exc:  # noqa: BLE001 — fail-open
            _logger.warning("Redis quota read failed (fail-open): %s", exc)
            return 0.0
