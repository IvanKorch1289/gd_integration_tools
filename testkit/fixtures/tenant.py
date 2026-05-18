"""Pytest-фикстуры для multi-tenancy сценариев.

Поднимает :class:`TenantContext` с предсказуемым ``tenant_id`` —
полезно для admin-эндпоинтов, RLS и SLO-тестов.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

__all__ = ("default_tenant_id", "tenant_context")


@pytest.fixture(scope="session")
def default_tenant_id() -> str:
    """Стабильный ``tenant_id`` для тестов."""
    return "tenant-test-default"


@pytest.fixture(scope="function")
def tenant_context(default_tenant_id: str) -> Iterator[Any]:
    """Поднимает scope :class:`TenantContext` для текущего теста."""
    try:
        from src.backend.core.tenancy import (  # noqa: PLC0415
            TenantContext,
            tenant_scope,
        )
    except ImportError:
        pytest.skip("core.tenancy unavailable")

    ctx = TenantContext(tenant_id=default_tenant_id)
    with tenant_scope(ctx) as scoped:
        yield scoped
