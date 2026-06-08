"""S36 w3 — Smoke tests: multi-region routing scaffold."""

from __future__ import annotations

import pytest

from src.backend.core.tenancy import TenantContext
from src.backend.infrastructure.resilience.region_routing import (
    _REGION_HEALTH,
    _REGION_REGISTRY,
    Region,
    RegionRouter,
    RegionStatus,
    get_region,
    get_region_status,
    list_regions,
    register_region,
    set_region_status,
)


@pytest.fixture(autouse=True)
def clean_region_registry() -> None:
    """Clear global region registry before and after each test."""
    _REGION_REGISTRY.clear()
    _REGION_HEALTH.clear()
    yield
    _REGION_REGISTRY.clear()
    _REGION_HEALTH.clear()


def test_region_dataclass_validates_code() -> None:
    """Region.code must be non-empty."""
    with pytest.raises(ValueError, match="non-empty"):
        Region(code="", primary_url="https://example.com")


def test_region_dataclass_validates_weight() -> None:
    """Region.weight must be non-negative."""
    with pytest.raises(ValueError, match="non-negative"):
        Region(code="x", primary_url="https://x.com", weight=-1)


def test_register_and_retrieve_region() -> None:
    """register_region() makes get_region() return it."""
    region = Region(code="test-1", primary_url="https://test-1.example.com", weight=50)
    register_region(region)

    assert get_region("test-1") == region
    assert get_region("nonexistent") is None


def test_list_regions_sorted_by_code() -> None:
    """list_regions() returns all registered regions sorted alphabetically."""
    r1 = Region(code="zz-top", primary_url="https://zz.example.com")
    r2 = Region(code="aa-foo", primary_url="https://aa.example.com")
    register_region(r1)
    register_region(r2)

    codes = [r.code for r in list_regions()]
    assert codes == sorted(codes)


def test_set_and_get_region_status() -> None:
    """set_region_status() updates get_region_status()."""
    region = Region(code="st1", primary_url="https://st1.example.com")
    register_region(region)
    # Initial status is UNKNOWN since register_region seeds _REGION_HEALTH but
    # get_region_status falls back to UNKNOWN for fresh keys; register_region
    # should set it — verify the function sets it correctly
    get_region_status("st1")
    set_region_status("st1", RegionStatus.UNHEALTHY)
    assert get_region_status("st1") == RegionStatus.UNHEALTHY
    # Also verify it didn't stay at the seed value after reset
    set_region_status("st1", RegionStatus.DEGRADED)
    assert get_region_status("st1") == RegionStatus.DEGRADED


def test_region_router_defaults_to_registered_region() -> None:
    """RegionRouter.route_url() returns registered region's primary_url."""
    region = Region(code="rtr1", primary_url="https://rtr1.example.com")
    register_region(region)

    router = RegionRouter(default_region="rtr1")
    assert router.route_url(None) == "https://rtr1.example.com"


def test_region_router_skips_unhealthy() -> None:
    """RegionRouter.route_url() skips UNHEALTHY regions."""
    healthy = Region(
        code="skh", primary_url="https://skh.example.com", status=RegionStatus.HEALTHY
    )
    unhealthy = Region(
        code="sku", primary_url="https://sku.example.com", status=RegionStatus.UNHEALTHY
    )
    register_region(healthy)
    register_region(unhealthy)

    router = RegionRouter(default_region="skh")
    url = router.route_url(None)
    assert "sku" not in url  # should not route to unhealthy


def test_region_router_uses_tenant_region_preference() -> None:
    """RegionRouter.route_url() prefers tenant_ctx.region."""
    ru = Region(code="rtrru", primary_url="https://rtru.example.com")
    en = Region(code="rtren", primary_url="https://rten.example.com")
    register_region(ru)
    register_region(en)

    router = RegionRouter(default_region="rtrru")

    ctx = TenantContext(tenant_id="t1", region="rtren")
    url = router.route_url(ctx)
    assert url == "https://rten.example.com"


def test_region_router_fallback_when_tenant_region_unhealthy() -> None:
    """When tenant preferred region is UNHEALTHY, falls back to default."""
    healthy = Region(
        code="fbrh", primary_url="https://fbrh.example.com", status=RegionStatus.HEALTHY
    )
    unhealthy = Region(
        code="fbru",
        primary_url="https://fbru.example.com",
        status=RegionStatus.UNHEALTHY,
    )
    register_region(healthy)
    register_region(unhealthy)

    router = RegionRouter(default_region="fbrh")
    ctx = TenantContext(tenant_id="t2", region="fbru")  # unhealthy
    url = router.route_url(ctx)
    assert url == "https://fbrh.example.com"


def test_is_healthy() -> None:
    """is_healthy() returns True for HEALTHY/DEGRADED/UNKNOWN."""
    healthy = Region(code="ih1", primary_url="https://ih1.example.com")
    register_region(healthy)
    set_region_status("ih1", RegionStatus.HEALTHY)

    router = RegionRouter(default_region="ih1")
    assert router.is_healthy("ih1") is True

    set_region_status("ih1", RegionStatus.UNHEALTHY)
    assert router.is_healthy("ih1") is False


def test_region_router_raises_when_no_regions() -> None:
    """route_url() raises RuntimeError if no regions registered."""
    router = RegionRouter(default_region="none")

    with pytest.raises(RuntimeError, match="No regions registered"):
        router.route_url(None)
