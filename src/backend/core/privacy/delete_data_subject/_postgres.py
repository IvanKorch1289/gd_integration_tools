"""PostgreSQL ErasureAdapter — DELETE/anonymize в основной БД.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

ADR-0347 — исправление несуществующей схемы
--------------------------------------------
Раньше адаптер импортировал ``PiiErasureRecord`` из
``core.domain.models.privacy_models`` — этого модуля НЕ существует и никогда
не существовало. Воспроизведено:

    PostgresErasureAdapter.execute(...) ->
        ErasureResultStatus.FAILED,
        error="ModuleNotFoundError: No module named '...privacy_models'"

То есть erasure по основной БД (первичный backend!) не работал никогда, при
этом privacy gate отчитывался о нём как "✅ covered" — потому что gate
искал в исходнике строки-маркеры ("DELETE", "tenant_id").

Теперь используется КАНОНИЧЕСКИЙ путь, тот же что и DSL-процессор
``dsl/engine/processors/security/pii_erase.py``:
таблица ``{entity_type}_pii``, колонка ``entity_id``, whitelist
entity_type через ``[A-Za-z_][A-Za-z0-9_]*``, значения биндятся параметрами.
Два разных механизма erasure в одном проекте больше не существует
(«One canonical implementation per capability»).

Tenant-scoping: если в таблице есть колонка ``tenant_id`` — DELETE
дополнительно ограничивается тенантом (ADR-0345 Option A). Если колонки нет,
это фиксируется в evidence: канонический путь тоже её не требует.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``PostgresErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)
from src.backend.core.privacy.pii_table import (
    build_anonymize_sql,
    build_delete_sql,
    pii_table_for_subject,
)

logger = logging.getLogger(__name__)


class PostgresErasureAdapter:
    """PostgreSQL adapter — DELETE/anonymize в ``{entity_type}_pii``.

    Per ADR-0345 Option A: tenant-aware per-call enforcement, если таблица
    содержит ``tenant_id``.
    """

    name = "postgresql"

    def __init__(self, session_factory: Callable | None = None) -> None:
        """Инициализация.

        Args:
            session_factory: async session factory. None → SKIPPED.
        """
        self._session_factory = session_factory

    async def _has_tenant_column(self, session: object, table: str) -> bool:
        """Определить наличие ``tenant_id`` в PII-таблице (tenant-scoping).

        Используется SQLAlchemy reflection (``inspect``), а не сырой
        ``information_schema``: запрос к ``information_schema`` работает
        только в PostgreSQL и в других СУБД молча падает.

        Fail-CLOSED (ADR-0347): проба НИКОГДА не деградирует в «колонки
        нет». Раньше ``except → return False`` приводил к тому, что при
        любой ошибке интроспекции DELETE выполнялся БЕЗ tenant-фильтра и
        стирал PII другого тенанта (доказано тестом
        ``test_hard_delete_removes_only_matching_tenant``: 2 строки вместо 1).
        Теперь ошибка интроспекции поднимается наверх → ``FAILED`` →
        reconciliation, а не молчаливое расширение области удаления.

        Args:
            session: Активная async-сессия.
            table: Валидированное имя таблицы.

        Returns:
            True если колонка ``tenant_id`` существует.

        Raises:
            Exception: Любая ошибка reflection пробрасывается (fail-closed).

        """
        from sqlalchemy import inspect

        connection = await session.connection()  # type: ignore[attr-defined]

        def _probe(sync_connection: object) -> bool:
            """Синхронная проба внутри run_sync (reflection sync-only)."""
            inspector = inspect(sync_connection)
            if not inspector.has_table(table):
                raise RuntimeError(f"PII table {table!r} does not exist")
            return any(
                col["name"] == "tenant_id" for col in inspector.get_columns(table)
            )

        return bool(await connection.run_sync(_probe))

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> AdapterResult:
        """Execute erasure в PostgreSQL с tenant-awareness.

        Args:
            subject_id: ``"<entity_type>:<entity_id>"`` (например ``"user:42"``).
            subject_type: Тип субъекта (для audit).
            strategy: ``HARD_DELETE`` или ``ANONYMIZE``.
            correlation_id: Correlation ID для audit.
            tenant_id: Тенант; если None — берётся из TenantContext.

        Returns:
            :class:`AdapterResult`; FAILED при любой ошибке БД (fail-closed —
            orchestrator запускает reconciliation, а не «успех»).

        """
        from src.backend.core.tenancy import get_tenant_id

        start = time.monotonic()
        try:
            session_factory = self._session_factory
            if session_factory is None:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="session_factory not configured",
                )

            effective_tenant = tenant_id if tenant_id is not None else get_tenant_id()
            if not effective_tenant:
                # Fail-closed: без тенанта невозможно доказать границы
                # удаления, а DELETE без tenant-фильтра затронет данные
                # других тенантов с тем же entity_id.
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.FAILED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="tenant_id is required: пустой tenant не даёт доступ к данным",
                )
            table = pii_table_for_subject(subject_id)

            async with session_factory() as session:
                from sqlalchemy import text

                tenant_scoped = await self._has_tenant_column(session, table)
                if not tenant_scoped:
                    logger.warning(
                        "pii_table_without_tenant_id table=%s subject_id=%s — "
                        "erase не tenant-scoped (канонический путь тоже: "
                        "в таблице нет tenant_id)",
                        table,
                        subject_id,
                    )
                params: dict[str, object] = {
                    "entity_id": subject_id.split(":", 1)[1],
                    "tenant_id": effective_tenant,
                }
                if tenant_scoped:
                    sql = text(
                        build_anonymize_sql(table, tenant_scoped=True)
                        if strategy is ErasureStrategy.ANONYMIZE
                        else build_delete_sql(table, tenant_scoped=True)
                    )
                else:
                    # table из pii_table_name() (whitelist), значения биндятся.
                    sql = text(
                        build_anonymize_sql(table, tenant_scoped=False)
                        if strategy is ErasureStrategy.ANONYMIZE
                        else build_delete_sql(table, tenant_scoped=False)
                    )

                result = await session.execute(sql, params)
                await session.commit()  # type: ignore[attr-defined]
                records_affected = result.rowcount or 0

            logger.debug(
                "pii_erasure_applied table=%s strategy=%s tenant_scoped=%s rows=%d",
                table,
                strategy.value,
                tenant_scoped,
                records_affected,
            )
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=(time.monotonic() - start) * 1000,
                records_affected=records_affected,
            )
        except Exception as exc:
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
