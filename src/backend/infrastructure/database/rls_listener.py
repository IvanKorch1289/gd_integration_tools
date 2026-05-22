"""RLS tenant SET LOCAL listener для AsyncSession (Sprint 21 W1).

Назначение:
    На каждое begin-transaction вызывает ``SET LOCAL app.tenant_id`` из
    :func:`current_tenant` ContextVar. PostgreSQL RLS-policy на tenant-aware
    таблицах (``workflow_instances`` и др.) использует
    ``current_setting('app.tenant_id', true)`` для tenant isolation.

Безопасность:
    * При отсутствии tenant в ContextVar listener НЕ вызывает SET — defensive
      default: ``current_setting(..., true)`` вернёт ``NULL``, policy
      ``USING (tenant_id = NULL)`` будет FALSE → 0 строк.
    * Использует ``set_config(...)`` (PG built-in), а не raw ``SET LOCAL`` —
      параметризация защищает от SQL injection через tenant_id.

Условия активации:
    * Feature-flag ``feature_flags.rls_postgres_enforce`` (Sprint 21 W0).
    * Dialect — только PostgreSQL.

См. также:
    * :mod:`src.backend.core.tenancy.__init__` — ContextVar provider.
    * ADR-NEW-12 — RLS Strategy.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from src.backend.core.config.features import feature_flags
from src.backend.core.tenancy import current_tenant
from src.backend.infrastructure.external_apis.logging_service import db_logger

__all__ = ("install_rls_tenant_listener",)


_INSTALLED_ENGINES: set[int] = set()


def install_rls_tenant_listener(async_engine: AsyncEngine) -> None:
    """Регистрирует ``after_begin`` listener для SET LOCAL app.tenant_id.

    Идемпотентен: повторный вызов для того же engine — no-op (защищён через
    ``_INSTALLED_ENGINES``). При выключенном feature-flag listener не
    регистрируется. При не-PG диалекте — listener no-op (proverka внутри).

    Args:
        async_engine: AsyncEngine, к sync_engine которого будет привязан
            listener. Для других engines listener не активируется.
    """
    if not feature_flags.rls_postgres_enforce:
        return

    sync_engine = async_engine.sync_engine
    if sync_engine.dialect.name != "postgresql":
        return

    engine_id = id(sync_engine)
    if engine_id in _INSTALLED_ENGINES:
        return
    _INSTALLED_ENGINES.add(engine_id)

    @event.listens_for(Session, "after_begin")
    def _set_tenant_on_begin(
        session: Session, transaction: Any, connection: Any
    ) -> None:
        """Set tenant scope на каждое begin transaction (RLS policy bind)."""
        if connection.dialect.name != "postgresql":
            return
        try:
            tenant = current_tenant()
        except Exception:
            return
        if tenant is None:
            return
        tenant_id = getattr(tenant, "tenant_id", None)
        if not tenant_id:
            return
        try:
            connection.exec_driver_sql(
                "SELECT set_config('app.tenant_id', %s, true)",
                (str(tenant_id),),
            )
        except Exception as exc:  # noqa: BLE001
            db_logger.warning(
                "RLS SET LOCAL app.tenant_id не применён: %s", exc, exc_info=True
            )
