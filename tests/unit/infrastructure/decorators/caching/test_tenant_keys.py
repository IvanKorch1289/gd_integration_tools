"""Wave 18 (ADR-0391): tenant-изоляция ключей кэш-декоратора.

Регрессия (дефект 3, high): ``response_cache_key`` строил ключ
``cache:{owner}:{func}:{sha256(args[1:])}`` — tenant в ключ НЕ входил.
БД фильтруется по ContextVar-tenant'у, кэш — нет: два tenant'а получали
ОДИН И ТОТ ЖЕ ключ → cross-tenant коллизия (проба аудита: ключ tenant_A
совпадал с ключом tenant_B).

Тот же дефект касался S3 metadata/existence-кэшей (``s3:metadata:*``,
``s3:exists:*``) — они тоже строились без tenant-сегмента.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.infrastructure.decorators.caching import (
    existence_cache_key,
    metadata_cache_key,
    response_cache_key,
)


class _Owner:
    """Владелец декорируемого метода."""


async def _func(self: Any, x: int) -> None:
    """Заглушка декорируемой функции."""


@pytest.mark.unit
def test_response_cache_key_differs_between_tenants() -> None:
    """Ключи разных tenant'ов НЕ совпадают."""
    owner = _Owner()

    with tenant_scope(TenantContext(tenant_id="tenant_a")):
        key_a = response_cache_key(_func, (owner, 1), {})
    with tenant_scope(TenantContext(tenant_id="tenant_b")):
        key_b = response_cache_key(_func, (owner, 1), {})

    assert key_a != key_b
    assert "tenant_a" in key_a
    assert "tenant_b" in key_b


@pytest.mark.unit
def test_response_cache_key_is_stable_inside_one_tenant() -> None:
    """Внутри одного tenant'а ключ детерминирован."""
    owner = _Owner()

    with tenant_scope(TenantContext(tenant_id="tenant_a")):
        key_1 = response_cache_key(_func, (owner, 1), {})
        key_2 = response_cache_key(_func, (owner, 1), {})

    assert key_1 == key_2


@pytest.mark.unit
def test_response_cache_key_without_tenant_is_unscoped() -> None:
    """Без tenant-контекста — отдельный unscoped-сегмент."""
    owner = _Owner()

    key = response_cache_key(_func, (owner, 1), {})

    assert "_unscoped_" in key


@pytest.mark.unit
def test_metadata_cache_key_differs_between_tenants() -> None:
    """S3 metadata-кэш тоже tenant-scoped."""
    with tenant_scope(TenantContext(tenant_id="tenant_a")):
        key_a = metadata_cache_key(_func, (), {"key": "obj"})
    with tenant_scope(TenantContext(tenant_id="tenant_b")):
        key_b = metadata_cache_key(_func, (), {"key": "obj"})

    assert key_a != key_b
    assert "tenant_a" in key_a


@pytest.mark.unit
def test_existence_cache_key_differs_between_tenants() -> None:
    """S3 existence-кэш тоже tenant-scoped."""
    with tenant_scope(TenantContext(tenant_id="tenant_a")):
        key_a = existence_cache_key(_func, (), {"key": "obj"})
    with tenant_scope(TenantContext(tenant_id="tenant_b")):
        key_b = existence_cache_key(_func, (), {"key": "obj"})

    assert key_a != key_b
    assert "tenant_a" in key_a
