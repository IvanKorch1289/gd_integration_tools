"""
Multi-region routing infrastructure (S36 w3).

Provides:
- ``Region`` — dataclass defining a region/datacenter
- ``RegionRouter`` — selects target region for a request based on tenant context
- ``RegionHealthChecker`` — monitors region health and marks regions degraded
- ``get_current_region()`` — returns the region handling the current request
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)


class RegionStatus(str, Enum):
    """Region availability state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"  # operating at reduced capacity
    UNHEALTHY = "unhealthy"  # no traffic — failover triggered
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Region:
    """
    A geographic region / datacenter.

    Attributes
    ----------
    code : str
        Unique identifier, e.g. ``"ru-1"``, ``"en-1"``.
    primary_url : str
        Base URL of the region's API entrypoint.
    fallback_urls : tuple[str, ...]
        Ordered list of fallback URLs within the same region
        (e.g. availability zones).
    status : RegionStatus
        Current health status (updated by ``RegionHealthChecker``).
    weight : int
        Traffic weight for weighted routing. Higher = more traffic.
        Defaults to 100.
    """

    code: str
    primary_url: str
    fallback_urls: tuple[str, ...] = ()
    status: RegionStatus = RegionStatus.UNKNOWN
    weight: int = 100

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("Region.code must be non-empty")
        if self.weight < 0:
            raise ValueError("Region.weight must be non-negative")


# ---------------------------------------------------------------------------
# Global region registry
# ---------------------------------------------------------------------------

_REGION_REGISTRY: dict[str, Region] = {}
_REGION_HEALTH: dict[str, RegionStatus] = {}
_active_region_code: str | None = None


def register_region(region: Region) -> None:
    """Register a region. Overwrites any existing region with the same ``code``."""
    _REGION_REGISTRY[region.code] = region
    _REGION_HEALTH[region.code] = region.status
    logger.info(
        "Region registered", extra={"region": region.code, "url": region.primary_url}
    )


def get_region(code: str) -> Region | None:
    """Return region by code, or None if not registered."""
    return _REGION_REGISTRY.get(code)


def list_regions() -> list[Region]:
    """All registered regions, sorted by code."""
    return sorted(_REGION_REGISTRY.values(), key=lambda r: r.code)


def get_region_status(code: str) -> RegionStatus:
    """Current health status of a region."""
    return _REGION_HEALTH.get(code, RegionStatus.UNKNOWN)


def set_region_status(code: str, status: RegionStatus) -> None:
    """Update region health status."""
    _REGION_HEALTH[code] = status
    if code in _REGION_REGISTRY:
        # Replace with updated status (frozen dataclass — create new instance)
        original = _REGION_REGISTRY[code]
        _REGION_REGISTRY[code] = Region(
            code=original.code,
            primary_url=original.primary_url,
            fallback_urls=original.fallback_urls,
            status=status,
            weight=original.weight,
        )
    logger.info("Region status updated", extra={"region": code, "status": status.value})


def get_active_region() -> str | None:
    """Region code handling the current request (thread-local or context-var)."""
    return _active_region_code


def set_active_region(code: str) -> None:
    """Set the active region for the current request context."""
    global _active_region_code
    _active_region_code = code


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from src.backend.core.tenancy import TenantContext


class RegionRouter:
    """
    Routes requests to the appropriate region based on tenant context.

    Routing strategy (fallback chain):
      1. Tenant's preferred region (from ``TenantContext.region``)
      2. Tenant's preferred region if healthy
      3. Next healthy region by weight
      4. Any healthy region
      5. Default region (first registered)

    Does **not** automatically failover mid-request — only at request
    boundary. For per-request failover, call ``route_request()`` at the
    start of each handler.
    """

    def __init__(self, default_region: str = "ru-1") -> None:
        self._default = default_region

    def route_url(self, tenant_ctx: TenantContext | None = None) -> str:
        """
        Return the primary URL for the best available region.

        Parameters
        ----------
        tenant_ctx
            Tenant context containing ``region`` preference.

        Returns
        -------
        str
            Primary URL of the selected region.

        Raises
        ------
        RuntimeError
            If no regions are registered.
        """
        regions = list_regions()
        if not regions:
            raise RuntimeError("No regions registered — call register_region() first")

        candidate_codes = self._build_candidate_list(tenant_ctx)

        for code in candidate_codes:
            region = get_region(code)
            if region is None:
                continue
            status = get_region_status(code)
            if status in (RegionStatus.HEALTHY, RegionStatus.DEGRADED):
                set_active_region(code)
                return region.primary_url

        # Fallback: first registered region regardless of status
        fallback = regions[0].primary_url
        set_active_region(regions[0].code)
        logger.warning(
            "No healthy regions found, using fallback",
            extra={"fallback": regions[0].code},
        )
        return fallback

    def _build_candidate_list(self, tenant_ctx: TenantContext | None) -> list[str]:
        """Build ordered list of region codes to try."""
        candidates: list[str] = []

        # 1. Tenant's preferred region
        if tenant_ctx is not None and tenant_ctx.region:
            candidates.append(tenant_ctx.region)

        # 2. Remaining regions sorted by weight (highest first)
        weighted = sorted(list_regions(), key=lambda r: r.weight, reverse=True)
        for r in weighted:
            if r.code not in candidates:
                candidates.append(r.code)

        return candidates

    def is_healthy(self, region_code: str) -> bool:
        """True if region is registered and not UNHEALTHY."""
        status = get_region_status(region_code)
        return status in (
            RegionStatus.HEALTHY,
            RegionStatus.DEGRADED,
            RegionStatus.UNKNOWN,
        )


# ---------------------------------------------------------------------------
# Health checking
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    pass


class RegionHealthChecker:
    """
    Monitors region health via synthetic requests.

    Usage::

        checker = RegionHealthChecker()
        asyncio.create_task(checker.start(interval=30))

    On status change, logs and updates region status. Integrate with
    alerting (PagerDuty/Slack) via the ``on_status_change`` callback.
    """

    def __init__(self, timeout: float = 5.0, unhealth_threshold: int = 3) -> None:
        """
        Parameters
        ----------
        timeout
            Seconds to wait for a region health probe response.
        unhealth_threshold
            Consecutive failures before marking a region UNHEALTHY.
        """
        self._timeout = timeout
        self._threshold = unhealth_threshold
        self._failure_counts: dict[str, int] = {}
        self._running = False
        self.on_status_change: (
            Callable[[str, RegionStatus, RegionStatus], None] | None
        ) = None

    async def probe(self, region: Region) -> bool:
        """
        Send a synthetic health check to a region.

        Returns True if the region responds within ``self._timeout``.
        Override this method to implement custom probe logic (e.g. HTTP GET).
        """
        import asyncio as _asyncio

        try:
            async with _asyncio.timeout(self._timeout):
                # Default probe: TCP connect to primary_url host
                from urllib.parse import urlparse

                parsed = urlparse(region.primary_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                sock = _asyncio.open_connection(host, port)
                reader, writer = await sock
                writer.close()
                await writer.wait_closed()
                return True
        except Exception:
            return False

    async def check_all(self) -> None:
        """Run one health check round across all registered regions."""

        regions = list_regions()
        checks = [(r.code, await self.probe(r)) for r in regions]
        for code, ok in checks:
            await self._record(code, ok)

    async def _record(self, code: str, ok: bool) -> None:
        """Update failure count and possibly transition region status."""
        if ok:
            self._failure_counts[code] = 0
            new_status = RegionStatus.HEALTHY
        else:
            count = self._failure_counts.get(code, 0) + 1
            self._failure_counts[code] = count
            new_status = (
                RegionStatus.UNHEALTHY
                if count >= self._threshold
                else RegionStatus.DEGRADED
            )

        current = get_region_status(code)
        if new_status != current:
            set_region_status(code, new_status)
            logger.warning(
                "Region status transition",
                extra={"region": code, "from": current.value, "to": new_status.value},
            )
            if self.on_status_change:
                self.on_status_change(code, current, new_status)

    async def start(self, interval: float = 30.0) -> None:
        """
        Continuously check region health every ``interval`` seconds.

        Cancel with ``checker.stop()``.
        """
        import asyncio as _asyncio

        self._running = True
        while self._running:
            await self.check_all()
            await _asyncio.sleep(interval)

    def stop(self) -> None:
        """Stop the health-check loop."""
        self._running = False
