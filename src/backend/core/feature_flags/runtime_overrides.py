"""Runtime overrides для feature flags (Sprint 16 Wave 9, CP-15 / B-6 partial).

Singleton, хранящий **изменённые в runtime значения** feature-flags поверх
статического реестра :mod:`src.backend.core.config.features`. Доступ
через ``RuntimeFeatureFlagOverrides.get(flag, default, tenant_id)`` —
приоритет: per-tenant override > global override > статический реестр.

Зачем
-----
Admin REST endpoint ``POST /admin/feature-flags/{flag}`` (см. wave 9 +
``entrypoints/api/v1/admin/feature_flags.py``) пишет сюда, и каждое
изменение эмитирует ``AuditService.emit("feature.toggled", ...)``.

Multi-replica propagation
-------------------------
В этой wave — **только in-memory singleton** (per-process). Для
multi-replica продакшена в следующей wave подключается Redis pub/sub
channel ``feature-flags:toggle`` (carryover: B-6 finale).

Чистый contract
---------------
Не требует Redis в test/dev. ``InMemoryProvider.resolve_boolean_value``
дополнительно читает из этого singleton'а, чтобы runtime-toggle
немедленно отражался без рестарта.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = (
    "RuntimeFeatureFlagOverrides",
    "FeatureFlagChange",
    "get_runtime_overrides",
    "reset_runtime_overrides",
)

_logger = logging.getLogger("core.feature_flags.runtime_overrides")


@dataclass(frozen=True, slots=True)
class FeatureFlagChange:
    """Описание одного изменения feature-flag (для audit).

    Attributes:
        flag: Имя флага.
        tenant_id: ``None`` для global override, иначе per-tenant.
        old_value: Предыдущее значение (``None`` если не было override).
        new_value: Новое значение.
        actor: Кто изменил (``"user:<id>"`` / ``"system"``).
        timestamp: UTC timestamp изменения.
    """

    flag: str
    tenant_id: str | None
    old_value: Any
    new_value: Any
    actor: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RuntimeFeatureFlagOverrides:
    """Thread-safe in-memory runtime overrides feature-flags.

    Storage:
        * ``_global``: ``{flag: value}`` — глобальные overrides.
        * ``_per_tenant``: ``{tenant_id: {flag: value}}`` — per-tenant overrides.

    Lookup priority:
        per-tenant override > global override > static registry (default).
    """

    __slots__ = ("_global", "_per_tenant", "_lock")

    def __init__(self) -> None:
        self._global: dict[str, Any] = {}
        self._per_tenant: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def get(
        self,
        flag: str,
        default: Any,
        *,
        tenant_id: str | None = None,
    ) -> Any:
        """Резолвит значение flag по приоритету tenant→global→default.

        Args:
            flag: Имя флага.
            default: Значение, возвращаемое если override не установлен.
            tenant_id: Опц. для per-tenant lookup.

        Returns:
            Значение из override или ``default``.
        """
        with self._lock:
            if tenant_id is not None:
                per_tenant = self._per_tenant.get(tenant_id)
                if per_tenant is not None and flag in per_tenant:
                    return per_tenant[flag]
            if flag in self._global:
                return self._global[flag]
        return default

    def has_override(
        self, flag: str, *, tenant_id: str | None = None
    ) -> bool:
        """Возвращает ``True`` если override установлен (global или tenant)."""
        with self._lock:
            if tenant_id is not None:
                per_tenant = self._per_tenant.get(tenant_id)
                if per_tenant is not None and flag in per_tenant:
                    return True
            return flag in self._global

    def set(
        self,
        flag: str,
        value: Any,
        *,
        tenant_id: str | None = None,
        actor: str = "system",
    ) -> FeatureFlagChange:
        """Установить override (global или per-tenant).

        Args:
            flag: Имя флага.
            value: Новое значение (любого типа — backend resolve_* кастит).
            tenant_id: ``None`` — global override; иначе per-tenant.
            actor: Кто инициирует (для audit).

        Returns:
            :class:`FeatureFlagChange` с old/new для audit-event.
        """
        with self._lock:
            if tenant_id is None:
                old = self._global.get(flag)
                self._global[flag] = value
            else:
                per_tenant = self._per_tenant.setdefault(tenant_id, {})
                old = per_tenant.get(flag)
                per_tenant[flag] = value

        change = FeatureFlagChange(
            flag=flag,
            tenant_id=tenant_id,
            old_value=old,
            new_value=value,
            actor=actor,
        )
        _logger.info(
            "feature_flag.override.set",
            extra={
                "flag": flag,
                "tenant_id": tenant_id,
                "old_value": old,
                "new_value": value,
                "actor": actor,
            },
        )
        return change

    def clear(
        self, flag: str, *, tenant_id: str | None = None
    ) -> FeatureFlagChange | None:
        """Снять override (вернуть к static-default).

        Returns:
            :class:`FeatureFlagChange` если override был; ``None`` если
            override не существовал.
        """
        with self._lock:
            if tenant_id is None:
                if flag not in self._global:
                    return None
                old = self._global.pop(flag)
                new = None
            else:
                per_tenant = self._per_tenant.get(tenant_id)
                if per_tenant is None or flag not in per_tenant:
                    return None
                old = per_tenant.pop(flag)
                new = None

        change = FeatureFlagChange(
            flag=flag,
            tenant_id=tenant_id,
            old_value=old,
            new_value=new,
            actor="system",
        )
        _logger.info(
            "feature_flag.override.clear",
            extra={"flag": flag, "tenant_id": tenant_id, "old_value": old},
        )
        return change

    def list_overrides(self) -> dict[str, Any]:
        """Снимок всех overrides — для admin GET endpoint.

        Returns:
            ``{"global": {...}, "per_tenant": {tenant_id: {...}}}``.
        """
        with self._lock:
            return {
                "global": dict(self._global),
                "per_tenant": {
                    tenant: dict(values)
                    for tenant, values in self._per_tenant.items()
                },
            }

    def reset(self) -> None:
        """Полная очистка (для unit-тестов)."""
        with self._lock:
            self._global.clear()
            self._per_tenant.clear()


_singleton: RuntimeFeatureFlagOverrides | None = None
_singleton_lock = threading.RLock()


def get_runtime_overrides() -> RuntimeFeatureFlagOverrides:
    """Singleton-аксессор."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = RuntimeFeatureFlagOverrides()
    return _singleton


def reset_runtime_overrides() -> None:
    """Сбросить singleton (для unit-тестов и lifespan re-init)."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.reset()
        _singleton = None
