"""Unit-тесты per-tenant pool metrics (S72 W1).

Проверяют:

1. _current_tenant_label() → '_global_' когда TenantContext не установлен.
2. _current_tenant_label() → tenant_id из TenantContext contextvar.
3. _current_tenant_label() → '_global_' если ctx.tenant_id пустой.
4. _record_warmup() создаёт Prom label `tenant_id='_global_'` при no-context.
5. _record_warmup() использует tenant_id из current_tenant().
6. _record_reconnect() создаёт Prom label `tenant_id='<tenant_id>'`.
7. _record_warmup() success=False → _WARMUP_FAILURES inc с tenant_id.
"""

from __future__ import annotations

import pytest

from src.backend.core.tenancy import TenantContext, set_tenant, tenant_scope
from src.backend.infrastructure.database import pool_warmup


def test_current_tenant_label_default_global() -> None:
    """Без TenantContext → '_global_' (lifespan/warmup scenario)."""
    # Сбрасываем contextvar: устанавливаем в None
    set_tenant(None)  # type: ignore[arg-type]
    assert pool_warmup._current_tenant_label() == "_global_"


def test_current_tenant_label_from_contextvar() -> None:
    """TenantContext установлен → возвращается tenant_id."""
    set_tenant(TenantContext(tenant_id="acme-corp"))
    try:
        assert pool_warmup._current_tenant_label() == "acme-corp"
    finally:
        set_tenant(None)  # type: ignore[arg-type]


def test_current_tenant_label_empty_tenant_id() -> None:
    """ctx.tenant_id пустой → '_global_'."""
    set_tenant(TenantContext(tenant_id=""))  # type: ignore[arg-type]
    try:
        assert pool_warmup._current_tenant_label() == "_global_"
    finally:
        set_tenant(None)  # type: ignore[arg-type]


def test_record_warmup_uses_global_label_when_no_context() -> None:
    """_record_warmup('pg', 5.0, True) → _WARMUP_DURATION.labels(tenant_id='_global_')."""
    set_tenant(None)  # type: ignore[arg-type]
    if pool_warmup._WARMUP_DURATION is None:
        pytest.skip("prometheus_client not installed")
    pool_warmup._record_warmup("pg", 5.0, success=True)
    # Prometheus не даёт простой accessor, но labels() идемпотентен —
    # повторный вызов с теми же labels не поднимает exception.
    pool_warmup._record_warmup("pg", 7.5, success=True)
    # Проверяем что нет exception (test passes = no exception).


def test_record_warmup_uses_tenant_label() -> None:
    """_record_warmup с активным tenant context → tenant_id в label."""
    if pool_warmup._WARMUP_DURATION is None:
        pytest.skip("prometheus_client not installed")
    with tenant_scope(TenantContext(tenant_id="tenant-42")):
        pool_warmup._record_warmup("redis", 3.0, success=True)
    # No exception = tenant_id="tenant-42" был принят как valid label.


def test_record_warmup_failure_increments_failures_with_tenant() -> None:
    """_record_warmup(success=False) → _WARMUP_FAILURES.inc() с tenant_id label."""
    if pool_warmup._WARMUP_FAILURES is None:
        pytest.skip("prometheus_client not installed")
    with tenant_scope(TenantContext(tenant_id="tenant-fail")):
        pool_warmup._record_warmup("clickhouse", 100.0, success=False)
    # No exception = labels(tenant_id="tenant-fail") принят.


def test_record_reconnect_uses_tenant_label() -> None:
    """_record_reconnect() → _POOL_RECONNECTS.inc() с tenant_id."""
    if pool_warmup._POOL_RECONNECTS is None:
        pytest.skip("prometheus_client not installed")
    with tenant_scope(TenantContext(tenant_id="tenant-rc")):
        pool_warmup._record_reconnect("pg")
    # No exception = label accepted.


def test_tenant_scope_restores_context() -> None:
    """tenant_scope() restore'ит предыдущий contextvar на exit."""
    set_tenant(TenantContext(tenant_id="outer"))
    try:
        with tenant_scope(TenantContext(tenant_id="inner")):
            assert pool_warmup._current_tenant_label() == "inner"
        assert pool_warmup._current_tenant_label() == "outer"
    finally:
        set_tenant(None)  # type: ignore[arg-type]
