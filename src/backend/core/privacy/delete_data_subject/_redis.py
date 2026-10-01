"""Redis ErasureAdapter — SCAN + UNLINK для subject-related cache keys.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Реальная имплементация: SCAN match по tenant-scoped паттернам
``tenant:<tenant_id>:<prefix><subject_id>`` и UNLINK найденных ключей.

Tenant-изоляция (fail-closed)
-----------------------------
До 2026-09-30 адаптер строил список префиксов как
``(*DEFAULT_PREFIXES, "tenant:<id>:")`` — tenant-префикс **добавлялся** к
глобальным, а не заменял их. Глобальные паттерны ``*user:<subject_id>*``
оставались активными, поэтому не-tenant-квалифицированный ``subject_id``
(например ``"42"``, ровно такой пример документирован в
``_orchestrator.execute``) матчил ключи ЧУЖИХ tenant'ов, и UNLINK их удалял:
cross-tenant data loss в GDPR erasure path (воспроизведено, см.
``tests/unit/core/privacy/test_redis_erasure_tenant_isolation.py``).

Теперь при разрешённом tenant сканируются **исключительно** tenant-scoped
паттерны. Глобальный скан (legacy-ключи без tenant-префикса) доступен только
через явный opt-in ``allow_global_scan=True`` на адаптере; без tenant и без
opt-in адаптер fail-closed возвращает ``FAILED`` и ничего не удаляет.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``RedisErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import time
from typing import Any

from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


class RedisErasureAdapter:
    """Redis adapter — SCAN + UNLINK для subject-related cache keys."""

    name = "redis"

    # Cache key prefixes для SCAN.
    DEFAULT_PREFIXES = (
        "user:",
        "session:",
        "tenant:",
        "auth:",
        "cache:user:",
        "cache:session:",
    )

    def __init__(
        self,
        redis_client: Any = None,
        key_prefixes: tuple[str, ...] | None = None,
        *,
        allow_global_scan: bool = False,
    ) -> None:
        """Инициализация.

        Args:
            redis_client: async redis client (redis.asyncio.Redis).
            key_prefixes: префиксы для SCAN match. None → DEFAULT_PREFIXES.
            allow_global_scan: явный opt-in на скан ключей **вне** tenant-scope
                (legacy-ключи вида ``user:42:profile``, без ``tenant:<id>:``).
                По умолчанию ``False`` — fail-closed. Включать только если
                вызывающая сторона доказуемо работает с плоско-legacy схемой
                ключей и приняла риск удаления одноимённых ключей других
                tenant'ов.
        """
        self._redis = redis_client
        self._prefixes = key_prefixes or self.DEFAULT_PREFIXES
        self._allow_global_scan = allow_global_scan

    def _build_scan_patterns(
        self, subject_id: str, effective_tenant: str | None
    ) -> list[str]:
        """Построить список SCAN-паттернов для erasure.

        Args:
            subject_id: идентификатор субъекта данных.
            effective_tenant: разрешённый tenant либо ``None``.

        Returns:
            Список glob-паттернов без дублей с сохранением порядка. При
            разрешённом tenant — только tenant-scoped паттерны
            (``tenant:<id>:<prefix><subject_id>``), плюс глобальные, если
            ``allow_global_scan`` включён. Без tenant — только глобальные.

        """
        patterns: list[str] = []
        if effective_tenant:
            tenant_root = f"tenant:{effective_tenant}:"
            # Ключ без вложенного префикса: tenant:<id>:<subject_id>
            patterns.append(f"*{tenant_root}{subject_id}*")
            # Ключ с вложенным префиксом: tenant:<id>:<prefix><subject_id>
            patterns.extend(f"*{tenant_root}{p}{subject_id}*" for p in self._prefixes)

        if not effective_tenant or self._allow_global_scan:
            # Глобальные паттерны допустимы только явным opt-in (или когда
            # tenant не разрешён и opt-in выставлен вызывающей стороной).
            patterns.extend(f"*{p}{subject_id}*" for p in self._prefixes)

        seen: set[str] = set()
        unique: list[str] = []
        for pattern in patterns:
            if pattern not in seen:
                seen.add(pattern)
                unique.append(pattern)
        return unique

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> AdapterResult:
        """Execute cache invalidation через SCAN + UNLINK.

        Per ADR-0345/v5 prompt Option A: tenant-awareness, fail-closed.

        - Если ``tenant_id`` передан **или** ``get_tenant_id()`` из
          TenantContext вернул значение → сканируются ТОЛЬКО ключи этого
          tenant'а. Ключи других tenant'ов не попадают в UNLINK ни при каких
          значениях ``subject_id``.
        - Если tenant разрешить не удалось → адаптер fail-closed: возвращает
          ``FAILED`` и НИЧЕГО не удаляет, если вызывающая сторона явно не
          запросила ``allow_global_scan=True`` при построении адаптера.

        Args:
            subject_id: идентификатор субъекта данных.
            subject_type: тип субъекта (для трассировки).
            strategy: стратегия erasure.
            correlation_id: идентификатор корреляции.
            tenant_id: явный tenant. ``None`` → резолвится из TenantContext.

        Returns:
            ``AdapterResult``. ``FAILED`` — если tenant не разрешён и глобальный
            скан не разрешён явно; ничего не удалено.

        """
        from src.backend.core.tenancy import get_tenant_id

        start = time.monotonic()
        try:
            redis = self._redis
            if redis is None:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="redis_client not configured",
                )

            # Per ADR-0345: resolve effective_tenant_id.
            resolved = tenant_id if tenant_id is not None else get_tenant_id()
            effective_tenant = resolved or None

            # Fail-closed: без tenant глобальный скан стирал бы ключи всех
            # tenant'ов сразу. Требуется явный opt-in от вызывающей стороны.
            if effective_tenant is None and not self._allow_global_scan:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.FAILED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error=(
                        "tenant scope unresolved and allow_global_scan=False — "
                        "refusing to scan globally (fail-closed, ADR-0345). "
                        "Pass tenant_id, set TenantContext, or construct the "
                        "adapter with allow_global_scan=True if legacy "
                        "non-tenant-prefixed keys must be erased."
                    ),
                )

            patterns = self._build_scan_patterns(subject_id, effective_tenant)

            keys_to_delete: set[bytes | str] = set()
            for pattern in patterns:
                # SCAN cursor-based iteration (non-blocking).
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor=cursor, match=pattern, count=100
                    )
                    keys_to_delete.update(keys)
                    if cursor == 0:
                        break

            deleted = 0
            if keys_to_delete:
                # UNLINK — async, не блокирует Redis.
                deleted = await redis.unlink(*keys_to_delete)

            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=deleted,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
