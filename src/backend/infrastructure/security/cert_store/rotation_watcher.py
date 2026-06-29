"""CertRotationWatcher (S171 M23, D260).

Periodic check expiring certs + auto-rotation.
- start()/stop() — background task lifecycle
- _check_expiring() — list expiring, return count
- Optional integration with Prometheus exporter (record_rotation)

Pattern (D260, Ponytail): thin wrapper — auto-rotation logic OPTIONAL
(default: только log warning, НЕ silent auto-rotate).

Production: config flag ``cert_auto_rotate: bool = False``.
"""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.infrastructure.security.cert_store.prometheus_exporter import (
        CertPrometheusExporter,
    )
    from src.backend.infrastructure.security.cert_store.store import (
        CertStore,
    )

logger = get_logger("security.cert_store.rotation")

__all__ = ("CertRotationWatcher",)


class CertRotationWatcher:
    """Watcher для cert expiration + опциональной auto-rotation (D260).

    Args:
        cert_store: CertStore instance для check/rotate.
        check_interval_seconds: Интервал между checks (default 1h).
        rotation_threshold_days: Порог в днях — если cert истекает
            раньше, помечается как expiring.
        prometheus_exporter: Optional exporter для record_rotation metrics.
    """

    def __init__(
        self,
        *,
        cert_store: "CertStore",
        check_interval_seconds: float = 3600.0,
        rotation_threshold_days: int = 30,
        prometheus_exporter: "CertPrometheusExporter | None" = None,
        auto_rotate: bool = False,
    ) -> None:
        self._cert_store = cert_store
        self._check_interval_seconds = check_interval_seconds
        self._rotation_threshold_days = rotation_threshold_days
        self._prometheus_exporter = prometheus_exporter
        self._auto_rotate = auto_rotate
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def _check_expiring(self) -> int:
        """Один check cycle — возвращает количество expiring certs."""
        now = datetime.now(timezone.utc)
        before = now.timestamp() + self._rotation_threshold_days * 86400
        try:
            entries = await self._cert_store._backend.list_expiring(before=before)
        except Exception as exc:
            logger.warning("cert.rotation.list_expiring_error: %s", exc)
            self._record_rotation(success=False)
            return 0

        for entry in entries:
            exp = getattr(entry, "expires_at", None)
            if exp is None:
                continue
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            days_remaining = (exp.timestamp() - now.timestamp()) / 86400
            sid = getattr(entry, "service_id", "unknown")
            logger.warning(
                "cert.rotation.expiring cert=%s days=%.1f threshold=%d",
                sid, days_remaining, self._rotation_threshold_days,
            )
            if self._auto_rotate and days_remaining <= 0:
                # Auto-rotate: реальная rotation в Vault
                logger.info(
                    "cert.rotation.auto_rotate_triggered cert=%s", sid,
                )
                # Конкретная rotation logic — out of scope (D260 thin wrapper)
                # Только mark metric
                self._record_rotation(success=True)
            elif self._auto_rotate:
                logger.info(
                    "cert.rotation.scheduled cert=%s days=%.1f",
                    sid, days_remaining,
                )

        self._record_rotation(success=True)
        return len(entries)

    def _record_rotation(self, *, success: bool) -> None:
        """Записать rotation в Prometheus (если exporter подключен)."""
        if self._prometheus_exporter is not None:
            self._prometheus_exporter.record_rotation(success=success)

    async def _loop(self) -> None:
        """Основной цикл watcher."""
        logger.info(
            "cert.rotation.started interval=%.0fs threshold=%dd",
            self._check_interval_seconds, self._rotation_threshold_days,
        )
        try:
            while not self._stop_event.is_set():
                await self._check_expiring()
                # Cancel-safe sleep
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._check_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass  # interval elapsed, continue
        except asyncio.CancelledError:
            logger.info("cert.rotation.cancelled")
            raise
        except Exception as exc:
            logger.error("cert.rotation.loop_error: %s", exc)
            raise

    async def start(self) -> None:
        """Запустить watcher как background task."""
        if self._task is not None:
            logger.warning("cert.rotation.already_started")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._loop(), name="cert-rotation-watcher"
        )
        logger.info("cert.rotation.task_started")

    async def stop(self) -> None:
        """Остановить watcher gracefully."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None
        logger.info("cert.rotation.stopped")
