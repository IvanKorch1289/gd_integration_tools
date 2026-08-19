"""Cycle-15 (D-AUDIT-1507): tenant-scoped file storage quotas.

Назначение:
    Multi-tenant S3-окружения подвержены resource exhaustion при
    неконтролируемом росте: один арендатор может занять весь bucket,
    блокируя остальных. Этот модуль вводит per-tenant квоты на:

    1. ``max_files`` — максимальное количество объектов в tenant scope.
    2. ``max_bytes`` — максимальный суммарный объём (bytes) в tenant scope.

Реализация:
    Redis-counter pattern (S75 W3 #4, ADR-NEW-7): атомарные
    :meth:`redis.incr`/:meth:`redis.incrby` + TTL на ключах для
    eventual cleanup. На upload — pre-check (count + bytes) и post-check
    (increment). На delete — decrement.

    Без Redis — quotas не enforced (fail-OPEN для обратной совместимости),
    но :class:`TenantFileQuotaManager` пишет warning в логи.

API:
    :class:`TenantFileQuotaManager`:
        - ``check_can_upload(tenant_id, size_bytes)`` → bool + reason
        - ``record_upload(tenant_id, size_bytes)`` → bool (атомарный инкремент)
        - ``record_delete(tenant_id, size_bytes)`` → bool (декремент)
        - ``get_usage(tenant_id)`` → dict с counts/bytes
        - ``reset_tenant(tenant_id)`` → удаляет Redis-counter (для admin)

    :class:`QuotaConfig`:
        - ``max_files`` (int, default: 100_000)
        - ``max_bytes`` (int, default: 100 GB)
        - ``enabled`` (bool, default: True)

    Квоты per-tenant читаются из :class:`TenantSettings` (settings.py).
    Default = глобальные ``QuotaConfig`` values.

Redis key schema:
    ``gd:tenant_file_count:<tenant_id>`` → int (file count, TTL: 7 days)
    ``gd:tenant_file_bytes:<tenant_id>`` → int (total bytes, TTL: 7 days)

    TTL reset на каждый touch (increment) — soft cleanup.
    Hard reset через :meth:`reset_tenant`.

Совместимость:
    - Без Redis: fail-OPEN (загрузка разрешена, warning logged)
    - Без tenant_id: skip quota check (system-level uploads bypass)
    - Без QuotaConfig: use defaults (см. class defaults)

Refs:
    - D-AUDIT-1507 (cycle-15) — tenant file quotas;
    - ADR-NEW-7 (S75 W3 #4) — Redis-counter quota pattern;
    - S75 W3 — multi-tenant resource limits design.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)

__all__ = (
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "QuotaCheckResult",
    "QuotaConfig",
    "TenantFileQuotaManager",
)


DEFAULT_MAX_FILES = 100_000
"""Default max files per tenant (cycle-15 baseline)."""

DEFAULT_MAX_BYTES = 100 * 1024 * 1024 * 1024  # 100 GB
"""Default max bytes per tenant (cycle-15 baseline)."""

# Redis key prefixes (D-AUDIT-1507).
COUNT_KEY_PREFIX = "gd:tenant_file_count:"
BYTES_KEY_PREFIX = "gd:tenant_file_bytes:"
# TTL — soft cleanup после 7 дней idle (admin вызывает reset для hard reset).
REDIS_TTL_SECONDS = 7 * 24 * 3600


@dataclass(slots=True, frozen=True)
class QuotaConfig:
    """Конфигурация per-tenant file quota.

    Attributes:
        max_files: Максимальное количество объектов (0 = unlimited).
        max_bytes: Максимальный суммарный объём в bytes (0 = unlimited).
        enabled: Включён ли quota check (False = bypass с logging).

    """

    max_files: int = DEFAULT_MAX_FILES
    max_bytes: int = DEFAULT_MAX_BYTES
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> QuotaConfig:
        """Build from settings dict (gracefully handle None/missing keys)."""
        if not data:
            return cls()
        return cls(
            max_files=int(data.get("max_files", DEFAULT_MAX_FILES)),
            max_bytes=int(data.get("max_bytes", DEFAULT_MAX_BYTES)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(slots=True, frozen=True)
class QuotaCheckResult:
    """Result of ``check_can_upload`` operation.

    Attributes:
        allowed: True если загрузка разрешена.
        reason: Human-readable reason (``None`` если allowed).
        current_files: Текущее количество файлов (для diagnostics).
        current_bytes: Текущий объём (для diagnostics).
        limit_files: Лимит files (для diagnostics).
        limit_bytes: Лимит bytes (для diagnostics).

    """

    allowed: bool
    reason: str | None = None
    current_files: int = 0
    current_bytes: int = 0
    limit_files: int = 0
    limit_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize для API response или logging."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "current_files": self.current_files,
            "current_bytes": self.current_bytes,
            "limit_files": self.limit_files,
            "limit_bytes": self.limit_bytes,
        }


class TenantFileQuotaManager:
    """Cycle-15 (D-AUDIT-1507): tenant-scoped file storage quota manager.

    Использует Redis-counter pattern для атомарного tracking'а
    ``(file_count, file_bytes)`` per-tenant. Без Redis — fail-OPEN
    (warning logged, quota не enforced).

    Безопасность:
        - Tenant_id ОБЯЗАН быть валидированным (slug regex). Передача
          чужих tenant_id → cross-tenant quota bypass.
        - Redis errors → fail-OPEN с WARNING (не блокируем upload).
        - Counter drift (Redis reset, manual cleanup) → re-sync через
          S3 list_objects (out-of-scope этого модуля, см. ADR-NEW-7).
    """

    def __init__(
        self, *, redis_client: Any | None = None, config: QuotaConfig | None = None
    ) -> None:
        """Инициализация.

        Args:
            redis_client: Async Redis client (опционально). Если ``None`` —
                quota check bypass с warning (fail-OPEN).
            config: Глобальная конфигурация квот. Per-tenant overrides
                могут быть добавлены через :attr:`tenant_configs`.

        """
        self._redis = redis_client
        self._config = config or QuotaConfig()
        # Per-tenant overrides (для tier-1 tenants с увеличенной квотой).
        self._tenant_configs: dict[str, QuotaConfig] = {}

    def set_tenant_config(self, tenant_id: str, config: QuotaConfig) -> None:
        """Override quota config для конкретного tenant."""
        if not self._is_safe_tenant_id(tenant_id):
            _logger.warning("tenant_id rejected (unsafe pattern): %s", tenant_id)
            return
        self._tenant_configs[tenant_id] = config

    async def check_can_upload(
        self, tenant_id: str | None, size_bytes: int
    ) -> QuotaCheckResult:
        """Проверить, разрешена ли загрузка файла ``size_bytes``.

        Args:
            tenant_id: Tenant ID (None для system uploads — bypass).
            size_bytes: Размер файла в bytes (>= 0).

        Returns:
            :class:`QuotaCheckResult` с allowed/reason и текущими
            counter values (для diagnostics в logging).

        """
        # System uploads bypass quota (no tenant_id).
        if not tenant_id:
            return QuotaCheckResult(allowed=True, reason="system upload")

        # Безопасность tenant_id.
        if not self._is_safe_tenant_id(tenant_id):
            _logger.warning("unsafe tenant_id pattern rejected: %s", tenant_id)
            return QuotaCheckResult(allowed=False, reason="invalid tenant_id")

        config = self._tenant_configs.get(tenant_id, self._config)
        if not config.enabled:
            return QuotaCheckResult(allowed=True, reason="quota disabled")

        # Без Redis — fail-OPEN.
        if self._redis is None:
            _logger.debug(
                "redis unavailable, quota check bypass for tenant %s", tenant_id
            )
            return QuotaCheckResult(allowed=True, reason="redis unavailable")

        current = await self.get_usage(tenant_id)
        new_files = current["files"] + 1
        new_bytes = current["bytes"] + size_bytes

        # Files limit (0 = unlimited).
        if config.max_files > 0 and new_files > config.max_files:
            return QuotaCheckResult(
                allowed=False,
                reason=f"file count {new_files} > limit {config.max_files}",
                current_files=current["files"],
                current_bytes=current["bytes"],
                limit_files=config.max_files,
                limit_bytes=config.max_bytes,
            )

        # Bytes limit (0 = unlimited).
        if config.max_bytes > 0 and new_bytes > config.max_bytes:
            return QuotaCheckResult(
                allowed=False,
                reason=f"bytes {new_bytes} > limit {config.max_bytes}",
                current_files=current["files"],
                current_bytes=current["bytes"],
                limit_files=config.max_files,
                limit_bytes=config.max_bytes,
            )

        return QuotaCheckResult(
            allowed=True,
            current_files=current["files"],
            current_bytes=current["bytes"],
            limit_files=config.max_files,
            limit_bytes=config.max_bytes,
        )

    async def record_upload(self, tenant_id: str | None, size_bytes: int) -> bool:
        """Записать успешный upload (атомарный increment).

        Returns:
            True если записано успешно (Redis available + tenant_id valid).

        """
        if not tenant_id or self._redis is None:
            return False
        if not self._is_safe_tenant_id(tenant_id):
            _logger.warning("unsafe tenant_id rejected: %s", tenant_id)
            return False
        try:
            count_key = f"{COUNT_KEY_PREFIX}{tenant_id}"
            bytes_key = f"{BYTES_KEY_PREFIX}{tenant_id}"
            # INCR + EXPIRE (атомарно per-key через pipeline).
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.incr(count_key)
                pipe.incrby(bytes_key, size_bytes)
                pipe.expire(count_key, REDIS_TTL_SECONDS)
                pipe.expire(bytes_key, REDIS_TTL_SECONDS)
                await pipe.execute()
            return True
        except Exception as exc:
            _logger.warning(
                "redis quota increment failed for tenant=%s: %s", tenant_id, exc
            )
            return False

    async def record_delete(self, tenant_id: str | None, size_bytes: int) -> bool:
        """Записать удаление (атомарный decrement, не ниже 0).

        Returns:
            True если записано успешно.

        """
        if not tenant_id or self._redis is None:
            return False
        if not self._is_safe_tenant_id(tenant_id):
            return False
        try:
            count_key = f"{COUNT_KEY_PREFIX}{tenant_id}"
            bytes_key = f"{BYTES_KEY_PREFIX}{tenant_id}"
            # DECR (если < 0 — set to 0); DECRBY (если < 0 — set to 0).
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.decr(count_key)
                pipe.decrby(bytes_key, size_bytes)
                await pipe.execute()
            # Floor to 0 (counters не должны быть negative из-за race).
            async with self._redis.pipeline(transaction=False) as pipe:
                await pipe.get(count_key)
                await pipe.get(bytes_key)
                count_val, bytes_val = await pipe.execute()
            if count_val is not None and int(count_val) < 0:
                await self._redis.set(count_key, 0)
            if bytes_val is not None and int(bytes_val) < 0:
                await self._redis.set(bytes_key, 0)
            return True
        except Exception as exc:
            _logger.warning(
                "redis quota decrement failed for tenant=%s: %s", tenant_id, exc
            )
            return False

    async def get_usage(self, tenant_id: str) -> dict[str, int]:
        """Получить текущее использование (files, bytes) для tenant.

        Returns:
            dict с keys ``files`` (int), ``bytes`` (int). Defaults 0
            для отсутствующих ключей.

        """
        if self._redis is None or not self._is_safe_tenant_id(tenant_id):
            return {"files": 0, "bytes": 0}
        try:
            count_val, bytes_val = await self._redis.mget(
                f"{COUNT_KEY_PREFIX}{tenant_id}", f"{BYTES_KEY_PREFIX}{tenant_id}"
            )
            return {"files": int(count_val or 0), "bytes": int(bytes_val or 0)}
        except Exception as exc:
            _logger.warning("redis quota read failed for tenant=%s: %s", tenant_id, exc)
            return {"files": 0, "bytes": 0}

    async def reset_tenant(self, tenant_id: str) -> bool:
        """Удалить counter'ы для tenant (admin-only operation).

        Returns:
            True если удалено успешно.

        """
        if self._redis is None or not self._is_safe_tenant_id(tenant_id):
            return False
        try:
            keys = [f"{COUNT_KEY_PREFIX}{tenant_id}", f"{BYTES_KEY_PREFIX}{tenant_id}"]
            await self._redis.delete(*keys)
            _logger.info("tenant file quota reset: tenant=%s", tenant_id)
            return True
        except Exception as exc:
            _logger.warning(
                "redis quota reset failed for tenant=%s: %s", tenant_id, exc
            )
            return False

    @staticmethod
    def _is_safe_tenant_id(tenant_id: str) -> bool:
        """Validation tenant_id — slug pattern (alphanumeric + underscore + dash)."""
        import re

        return bool(re.match(r"^[a-zA-Z0-9_-]{1,64}$", tenant_id))


# ─── DI provider ─────────────────────────────────────────────────────────────


def get_tenant_file_quota_manager() -> TenantFileQuotaManager:
    """DI provider для :class:`TenantFileQuotaManager`.

    Создаёт singleton с redis_client из app_state (если доступен).
    """
    try:
        from src.backend.core.di.app_state import app_state_singleton

        redis = app_state_singleton("redis_kv_client", factory=None)
        return TenantFileQuotaManager(redis_client=redis)
    except (ImportError, AttributeError, RuntimeError, KeyError) as di_exc:
        # cycle-9/D-AUDIT-1702: narrow exceptions + observability.
        # ImportError — app_state_singleton missing, AttributeError —
        # API change, RuntimeError — DI unavailable, KeyError —
        # singleton not registered.
        _logger.debug(
            "DI provider: redis unavailable, quota manager in fail-OPEN: %s", di_exc
        )
        return TenantFileQuotaManager(redis_client=None)


__all__ += ("get_tenant_file_quota_manager",)
