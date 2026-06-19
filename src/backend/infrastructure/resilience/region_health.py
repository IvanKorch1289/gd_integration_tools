"""Region health checker (S168 W11 P2-6).

Extracted from region_routing.py per master prompt v8 P2-6:
"split region_router.py into region_router.py + region_health.py +
region_selector.py per Strategy pattern".

Per Ponytail minimum: extract ONE class (RegionHealthChecker) into
its own file (region_health.py). Other 3 classes (RegionStatus,
Region, RegionRouter) остаются в region_routing.py для backward-compat.

Full split (4 files) — separate WIP.
"""

from __future__ import annotations

import logging
from typing import Callable

from src.backend.infrastructure.resilience.region_routing import (
    Region,
    RegionStatus,
    get_region_status,
    set_region_status,
)

logger = logging.getLogger(__name__)


class RegionHealthChecker:
    """S168 W11 P2-6: extracted from region_routing.py.

    Monitors region health via synthetic requests (default: TCP connect
    to region.primary_url).

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
        from src.backend.infrastructure.resilience.region_routing import (
            list_regions,
        )

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


__all__ = ("RegionHealthChecker",)
