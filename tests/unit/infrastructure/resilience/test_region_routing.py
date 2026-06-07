"""Unit tests for region_routing module."""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.tenancy import TenantContext

# Load region_routing directly to avoid pulling heavy deps via package __init__.py.
_region_routing_path = (
    pathlib.Path(__file__).resolve().parents[4]
    / "src"
    / "backend"
    / "infrastructure"
    / "resilience"
    / "region_routing.py"
)
_spec = importlib.util.spec_from_file_location("region_routing", _region_routing_path)
_rr = importlib.util.module_from_spec(_spec)
# Dataclasses require the module to be present in sys.modules during exec.
sys.modules.setdefault("region_routing", _rr)
_spec.loader.exec_module(_rr)

Region = _rr.Region
RegionHealthChecker = _rr.RegionHealthChecker
RegionRouter = _rr.RegionRouter
RegionStatus = _rr.RegionStatus
get_active_region = _rr.get_active_region
get_region = _rr.get_region
get_region_status = _rr.get_region_status
list_regions = _rr.list_regions
register_region = _rr.register_region
set_active_region = _rr.set_active_region
set_region_status = _rr.set_region_status


@pytest.fixture(autouse=True)
def _clear_regions() -> None:
    """Clear global region registry before and after each test."""
    _rr._REGION_REGISTRY.clear()
    _rr._REGION_HEALTH.clear()
    _rr._active_region_code = None
    yield
    _rr._REGION_REGISTRY.clear()
    _rr._REGION_HEALTH.clear()
    _rr._active_region_code = None


class TestRegionStatus:
    @pytest.mark.unit
    def test_members(self) -> None:
        """RegionStatus contains expected members."""
        assert RegionStatus.HEALTHY.value == "healthy"
        assert RegionStatus.DEGRADED.value == "degraded"
        assert RegionStatus.UNHEALTHY.value == "unhealthy"
        assert RegionStatus.UNKNOWN.value == "unknown"


class TestRegion:
    @pytest.mark.unit
    def test_create_with_defaults(self) -> None:
        """Region uses correct defaults for optional fields."""
        region = Region(code="ru-1", primary_url="https://ru-1.example.com")
        assert region.code == "ru-1"
        assert region.primary_url == "https://ru-1.example.com"
        assert region.fallback_urls == ()
        assert region.status is RegionStatus.UNKNOWN
        assert region.weight == 100

    @pytest.mark.unit
    def test_create_full(self) -> None:
        """Region accepts all fields explicitly."""
        region = Region(
            code="eu-1",
            primary_url="https://eu-1.example.com",
            fallback_urls=("https://eu-1b.example.com",),
            status=RegionStatus.HEALTHY,
            weight=200,
        )
        assert region.fallback_urls == ("https://eu-1b.example.com",)
        assert region.status is RegionStatus.HEALTHY
        assert region.weight == 200

    @pytest.mark.unit
    def test_empty_code_raises(self) -> None:
        """Empty region code raises ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            Region(code="", primary_url="https://example.com")

    @pytest.mark.unit
    def test_negative_weight_raises(self) -> None:
        """Negative weight raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            Region(code="ru-1", primary_url="https://example.com", weight=-1)


class TestRegionRegistry:
    @pytest.mark.unit
    def test_register_and_get_region(self) -> None:
        """register_region stores region; get_region retrieves it."""
        region = Region(code="ru-1", primary_url="https://ru-1.example.com")
        register_region(region)
        assert get_region("ru-1") == region

    @pytest.mark.unit
    def test_register_overwrites(self) -> None:
        """Registering with same code overwrites previous region."""
        r1 = Region(code="ru-1", primary_url="https://a.example.com")
        r2 = Region(code="ru-1", primary_url="https://b.example.com")
        register_region(r1)
        register_region(r2)
        assert get_region("ru-1") == r2

    @pytest.mark.unit
    def test_list_regions_sorted(self) -> None:
        """list_regions returns regions sorted by code."""
        register_region(Region(code="zz", primary_url="https://zz.example.com"))
        register_region(Region(code="aa", primary_url="https://aa.example.com"))
        register_region(Region(code="mm", primary_url="https://mm.example.com"))
        codes = [r.code for r in list_regions()]
        assert codes == ["aa", "mm", "zz"]

    @pytest.mark.unit
    def test_get_region_none(self) -> None:
        """get_region returns None for unregistered code."""
        assert get_region("nonexistent") is None

    @pytest.mark.unit
    def test_get_region_status_registered(self) -> None:
        """Status of registered region reflects its initial status."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        assert get_region_status("ru-1") is RegionStatus.HEALTHY

    @pytest.mark.unit
    def test_get_region_status_unknown(self) -> None:
        """Status of unregistered region is UNKNOWN."""
        assert get_region_status("missing") is RegionStatus.UNKNOWN

    @pytest.mark.unit
    def test_set_region_status_updates_health_and_registry(self) -> None:
        """set_region_status updates both _REGION_HEALTH and the registry entry."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        set_region_status("ru-1", RegionStatus.DEGRADED)
        assert get_region_status("ru-1") is RegionStatus.DEGRADED
        reg = get_region("ru-1")
        assert reg is not None
        assert reg.status is RegionStatus.DEGRADED


class TestActiveRegion:
    @pytest.mark.unit
    def test_get_active_region_default_none(self) -> None:
        """Active region is None by default."""
        assert get_active_region() is None

    @pytest.mark.unit
    def test_set_active_region(self) -> None:
        """set_active_region changes the active region code."""
        set_active_region("eu-1")
        assert get_active_region() == "eu-1"


class TestRegionRouter:
    @pytest.mark.unit
    def test_route_url_no_regions_raises(self) -> None:
        """route_url raises RuntimeError when no regions are registered."""
        router = RegionRouter(default_region="ru-1")
        with pytest.raises(RuntimeError, match="No regions registered"):
            router.route_url()

    @pytest.mark.unit
    def test_route_url_selects_preferred_region(self) -> None:
        """Preferred region from tenant_ctx is selected when healthy."""
        register_region(Region(code="ru-1", primary_url="https://ru-1.example.com"))
        register_region(
            Region(
                code="eu-1",
                primary_url="https://eu-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        router = RegionRouter()
        ctx = TenantContext(tenant_id="t1", region="eu-1")
        url = router.route_url(ctx)
        assert url == "https://eu-1.example.com"
        assert get_active_region() == "eu-1"

    @pytest.mark.unit
    def test_route_url_skips_unhealthy_preferred(self) -> None:
        """If preferred region is unhealthy, fallback to next healthy region."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        register_region(
            Region(
                code="eu-1",
                primary_url="https://eu-1.example.com",
                status=RegionStatus.UNHEALTHY,
            )
        )
        router = RegionRouter()
        ctx = TenantContext(tenant_id="t1", region="eu-1")
        url = router.route_url(ctx)
        assert url == "https://ru-1.example.com"
        assert get_active_region() == "ru-1"

    @pytest.mark.unit
    def test_route_url_weighted_fallback(self) -> None:
        """Without preferred region, selects healthy region with highest weight."""
        register_region(
            Region(
                code="aa",
                primary_url="https://aa.example.com",
                weight=10,
                status=RegionStatus.HEALTHY,
            )
        )
        register_region(
            Region(
                code="bb",
                primary_url="https://bb.example.com",
                weight=50,
                status=RegionStatus.HEALTHY,
            )
        )
        router = RegionRouter()
        url = router.route_url()
        assert url == "https://bb.example.com"
        assert get_active_region() == "bb"

    @pytest.mark.unit
    def test_route_url_degraded_accepted(self) -> None:
        """Degraded region is accepted as viable target."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.DEGRADED,
            )
        )
        router = RegionRouter()
        url = router.route_url()
        assert url == "https://ru-1.example.com"
        assert get_active_region() == "ru-1"

    @pytest.mark.unit
    def test_route_url_unknown_region_fallback(self) -> None:
        """Unknown-status region is not chosen as healthy; falls back to first registered."""
        register_region(
            Region(
                code="aa",
                primary_url="https://aa.example.com",
                status=RegionStatus.UNKNOWN,
            )
        )
        router = RegionRouter()
        url = router.route_url()
        # Fallback to first registered regardless of status
        assert url == "https://aa.example.com"
        assert get_active_region() == "aa"

    @pytest.mark.unit
    def test_route_url_fallback_to_first_registered(self) -> None:
        """If no healthy regions exist, fallback to first registered region."""
        register_region(
            Region(
                code="bb",
                primary_url="https://bb.example.com",
                status=RegionStatus.UNHEALTHY,
            )
        )
        register_region(
            Region(
                code="aa",
                primary_url="https://aa.example.com",
                status=RegionStatus.UNHEALTHY,
            )
        )
        router = RegionRouter()
        url = router.route_url()
        # list_regions sorts by code, so "aa" is first
        assert url == "https://aa.example.com"
        assert get_active_region() == "aa"

    @pytest.mark.unit
    def test_is_healthy(self) -> None:
        """is_healthy returns True for healthy/degraded/unknown and False for unhealthy."""
        register_region(
            Region(
                code="h",
                primary_url="https://h.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        register_region(
            Region(
                code="d",
                primary_url="https://d.example.com",
                status=RegionStatus.DEGRADED,
            )
        )
        register_region(
            Region(
                code="u",
                primary_url="https://u.example.com",
                status=RegionStatus.UNHEALTHY,
            )
        )
        register_region(
            Region(
                code="n",
                primary_url="https://n.example.com",
                status=RegionStatus.UNKNOWN,
            )
        )
        router = RegionRouter()
        assert router.is_healthy("h") is True
        assert router.is_healthy("d") is True
        assert router.is_healthy("u") is False
        assert router.is_healthy("n") is True
        assert router.is_healthy("missing") is True  # UNKNOWN for unregistered

    @pytest.mark.unit
    def test_build_candidate_list(self) -> None:
        """_build_candidate_list orders: tenant preference first, then by weight desc."""
        register_region(
            Region(code="low", primary_url="https://low.example.com", weight=1)
        )
        register_region(
            Region(code="high", primary_url="https://high.example.com", weight=100)
        )
        router = RegionRouter()
        ctx = TenantContext(tenant_id="t1", region="low")
        candidates = router._build_candidate_list(ctx)
        assert candidates[0] == "low"
        assert candidates[1] == "high"


class TestRegionHealthChecker:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_probe_success(self) -> None:
        """probe returns True on successful TCP connect."""
        checker = RegionHealthChecker()
        region = Region(code="ru-1", primary_url="https://ru-1.example.com")
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock()
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        writer_mock = MagicMock()
        writer_mock.wait_closed = AsyncMock()
        with patch("asyncio.timeout", return_value=mock_cm):
            with patch(
                "asyncio.open_connection",
                new_callable=AsyncMock,
                return_value=(MagicMock(), writer_mock),
            ):
                result = await checker.probe(region)
        assert result is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_probe_failure(self) -> None:
        """probe returns False when connection raises."""
        checker = RegionHealthChecker()
        region = Region(code="ru-1", primary_url="https://ru-1.example.com")
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock()
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        with patch("asyncio.timeout", return_value=mock_cm):
            with patch("asyncio.open_connection", side_effect=OSError("fail")):
                result = await checker.probe(region)
        assert result is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_record_ok_sets_healthy(self) -> None:
        """_record with ok=True sets region to HEALTHY."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.UNKNOWN,
            )
        )
        checker = RegionHealthChecker()
        await checker._record("ru-1", ok=True)
        assert get_region_status("ru-1") is RegionStatus.HEALTHY
        assert checker._failure_counts["ru-1"] == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_record_failure_degraded_then_unhealthy(self) -> None:
        """Consecutive failures transition region to DEGRADED then UNHEALTHY."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        checker = RegionHealthChecker(unhealth_threshold=3)
        await checker._record("ru-1", ok=False)
        assert get_region_status("ru-1") is RegionStatus.DEGRADED
        await checker._record("ru-1", ok=False)
        assert get_region_status("ru-1") is RegionStatus.DEGRADED
        await checker._record("ru-1", ok=False)
        assert get_region_status("ru-1") is RegionStatus.UNHEALTHY

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_record_no_change_when_status_same(self) -> None:
        """Repeated ok=True when already HEALTHY does not trigger extra updates."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        checker = RegionHealthChecker()
        with patch("region_routing.set_region_status") as mock_set:
            await checker._record("ru-1", ok=True)
            await checker._record("ru-1", ok=True)
        # set_region_status should be called once (initial transition from HEALTHY to HEALTHY? wait)
        # Actually _record checks `if new_status != current`, so if current is HEALTHY and new is HEALTHY, it won't call.
        # But after first register_region status is HEALTHY, _record sees new_status HEALTHY == current HEALTHY -> no call.
        mock_set.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_check_all_calls_probe_for_all_regions(self) -> None:
        """check_all probes every registered region."""
        register_region(Region(code="a", primary_url="https://a.example.com"))
        register_region(Region(code="b", primary_url="https://b.example.com"))
        checker = RegionHealthChecker()
        with patch.object(
            checker, "probe", new=AsyncMock(return_value=True)
        ) as mock_probe:
            await checker.check_all()
        assert mock_probe.call_count == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_status_change_callback(self) -> None:
        """on_status_change callback is invoked when status transitions."""
        register_region(
            Region(
                code="ru-1",
                primary_url="https://ru-1.example.com",
                status=RegionStatus.HEALTHY,
            )
        )
        checker = RegionHealthChecker(unhealth_threshold=1)
        callback = MagicMock()
        checker.on_status_change = callback
        await checker._record("ru-1", ok=False)
        callback.assert_called_once_with(
            "ru-1", RegionStatus.HEALTHY, RegionStatus.UNHEALTHY
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        """start runs check_all periodically; stop terminates the loop."""
        checker = RegionHealthChecker()
        with patch.object(
            checker, "check_all", new_callable=AsyncMock
        ) as mock_check_all:
            task = asyncio.create_task(checker.start(interval=0.01))
            await asyncio.sleep(0.05)
            checker.stop()
            await asyncio.wait_for(task, timeout=1.0)
        assert mock_check_all.call_count >= 1
