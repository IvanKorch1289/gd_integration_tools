"""TemporalClientFactory + WorkerPool + ActivityHeartbeatMonitor (Sprint 9 K3 W9).

GAP-WF-4.1: единый source-of-truth для Temporal client/worker lifecycle.

Контракт:

* :class:`TemporalClientFactory` — singleton, ``get_client(namespace)``
  кэширует client per-namespace; reconnect on stale.
* :class:`TemporalWorkerPool` — управляет несколькими workers по
  task_queue; graceful shutdown.
* :class:`ActivityHeartbeatMonitor` — фоновый task, который ловит
  long-running activities без heartbeat'а; emit метрику для алертов.

Lazy-import temporalio SDK (~15-20MB) — отсутствие пакета не должно
ломать import composition root.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

__all__ = (
    "ActivityHeartbeatMonitor",
    "ActivityHeartbeatStats",
    "TemporalClientFactory",
    "TemporalWorkerPool",
)

_logger = logging.getLogger("workflow.temporal_client")


@dataclass(slots=True)
class _ClientCacheEntry:
    """Запись в кэше per-namespace client'ов."""

    client: Any
    created_at: float
    last_used_at: float


class TemporalClientFactory:
    """Singleton-фабрика Temporal client'ов с per-namespace кэшем.

    Args:
        target_host: ``host:port`` Temporal frontend (default ``localhost:7233``).
        tls: dict с TLS config (cert/key/ca) или None.
        recycle_seconds: TTL client'а; после превышения — reconnect.
    """

    def __init__(
        self,
        *,
        target_host: str = "localhost:7233",
        tls: dict[str, Any] | None = None,
        recycle_seconds: float = 3600.0,
        pki_backend: str = "file",
        pki_role: str = "temporal-worker",
        pki_common_name: str = "temporal-worker",
        pki_ttl: str = "24h",
    ) -> None:
        self._target = target_host
        self._tls = tls
        self._recycle = recycle_seconds
        self._pki_backend = pki_backend
        self._pki_role = pki_role
        self._pki_common_name = pki_common_name
        self._pki_ttl = pki_ttl
        self._cache: dict[str, _ClientCacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, namespace: str) -> Any:
        """Возвращает Temporal client для namespace (с TTL-recycling).

        Raises:
            ImportError: если temporalio не установлен.
        """
        now = time.monotonic()
        async with self._lock:
            entry = self._cache.get(namespace)
            if entry is not None and (now - entry.created_at) < self._recycle:
                entry.last_used_at = now
                return entry.client

            # Recycle или fresh connect
            client = await self._build_client(namespace)
            self._cache[namespace] = _ClientCacheEntry(
                client=client, created_at=now, last_used_at=now
            )
            return client

    async def _build_client(self, namespace: str) -> Any:
        from temporalio.client import Client
        from temporalio.service import TLSConfig

        from src.backend.infrastructure.workflow.temporal_backend import (
            build_temporal_data_converter,
        )

        tls: bool | TLSConfig = False
        tls_dict = self._tls
        if self._pki_backend == "vault":
            tls_dict = await self._load_certs_from_vault()
        if tls_dict is not None:
            tls = TLSConfig(
                server_root_ca_cert=self._encode_pem(tls_dict.get("ca")),
                client_cert=self._encode_pem(tls_dict.get("cert")),
                client_private_key=self._encode_pem(tls_dict.get("key")),
            )

        _logger.info(
            "temporal.client.connecting",
            extra={"namespace": namespace, "target": self._target},
        )
        return await Client.connect(
            self._target,
            namespace=namespace,
            tls=tls,
            data_converter=build_temporal_data_converter(),
        )

    async def aclose(self) -> None:
        """Graceful cleanup всех cached clients (idempotent)."""
        async with self._lock:
            for entry in self._cache.values():
                close = getattr(entry.client, "close", None)
                if asyncio.iscoroutinefunction(close):
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass
            self._cache.clear()

    @staticmethod
    def _encode_pem(value: Any) -> bytes | None:
        """PEM-строку либо bytes → bytes; ``None`` остаётся ``None``."""
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return None

    async def _load_certs_from_vault(self) -> dict[str, str] | None:
        """Sprint 12 K1 W2 — issue/refresh cert через Vault PKI engine."""
        try:
            from src.backend.infrastructure.secrets.vault_pki import VaultPkiClient

            pki = VaultPkiClient()
            bundle = pki.issue_cert(
                role=self._pki_role,
                common_name=self._pki_common_name,
                ttl=self._pki_ttl,
            )
            return {
                "ca": bundle.ca_chain,
                "cert": bundle.certificate,
                "key": bundle.private_key,
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Vault PKI cert issue failed (%s); fallback to file backend", exc
            )
            return self._tls

    def stats(self) -> dict[str, Any]:
        """Текущий снимок кэша (для health endpoint)."""
        now = time.monotonic()
        return {
            "namespaces": list(self._cache.keys()),
            "size": len(self._cache),
            "entries": {
                ns: {
                    "age_seconds": now - entry.created_at,
                    "idle_seconds": now - entry.last_used_at,
                }
                for ns, entry in self._cache.items()
            },
        }


class TemporalWorkerPool:
    """Управляет несколькими Temporal workers по task_queue.

    Workers создаются через ``client.create_worker(task_queue, workflows, activities)``.

    Args:
        factory: :class:`TemporalClientFactory`.
        namespace: namespace, в котором живут все workers пула.
    """

    def __init__(self, *, factory: TemporalClientFactory, namespace: str) -> None:
        self._factory = factory
        self._namespace = namespace
        self._workers: dict[str, Any] = {}  # task_queue → worker
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def register_worker(
        self, *, task_queue: str, workflows: list[Any], activities: list[Any]
    ) -> None:
        """Создать и запустить worker для конкретного task_queue."""
        from temporalio.worker import Worker

        client = await self._factory.get_client(self._namespace)
        async with self._lock:
            if task_queue in self._workers:
                _logger.warning(
                    "temporal.worker.already_registered",
                    extra={"task_queue": task_queue},
                )
                return
            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=workflows,
                activities=activities,
            )
            self._workers[task_queue] = worker
            from src.backend.core.utils.task_registry import (
                get_task_registry,  # noqa: PLC0415
            )

            self._tasks[task_queue] = get_task_registry().create_task(
                worker.run(), name=f"temporal-worker-{task_queue}"
            )

    async def shutdown(self) -> None:
        """Graceful shutdown — все workers останавливаются параллельно."""
        async with self._lock:
            for tq, worker in list(self._workers.items()):
                try:
                    await worker.shutdown()
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "temporal.worker.shutdown_failed", extra={"task_queue": tq}
                    )
            self._workers.clear()
            for task in self._tasks.values():
                if not task.done():
                    task.cancel()
            self._tasks.clear()

    def list_workers(self) -> list[str]:
        """Список зарегистрированных task_queue."""
        return sorted(self._workers.keys())


@dataclass(slots=True)
class ActivityHeartbeatStats:
    """Метрики monitor'а для Prometheus exporter.

    Attributes:
        tracked: число активностей под наблюдением.
        missed_heartbeats: накопленное число missed beats.
        stale_activities: число активностей в текущий момент с stale beat.
    """

    tracked: int = 0
    missed_heartbeats: int = 0
    stale_activities: int = 0
    last_check_at: float | None = None


class ActivityHeartbeatMonitor:
    """Фоновый monitor для long-running activities.

    Periodically iterates list of tracked activities и проверяет, что
    last_heartbeat был not older than ``stale_threshold_seconds``. Emit'ит
    метрику ``temporal_activity_stale_count`` для алертов.

    Args:
        check_interval_seconds: период проверки (default 30s).
        stale_threshold_seconds: после какого idle отметить stale (default 120s).
    """

    def __init__(
        self,
        *,
        check_interval_seconds: float = 30.0,
        stale_threshold_seconds: float = 120.0,
    ) -> None:
        self._check_interval = check_interval_seconds
        self._stale_threshold = stale_threshold_seconds
        self._beats: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.stats = ActivityHeartbeatStats()

    async def heartbeat(self, activity_id: str) -> None:
        """Регистрирует heartbeat для активности."""
        async with self._lock:
            self._beats[activity_id] = time.monotonic()

    async def forget(self, activity_id: str) -> None:
        """Снимает активность с monitoring (после completion)."""
        async with self._lock:
            self._beats.pop(activity_id, None)

    async def start(self) -> None:
        """Запустить background-проверку (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        from src.backend.core.utils.task_registry import (
            get_task_registry,  # noqa: PLC0415
        )

        self._task = get_task_registry().create_task(
            self._run(), name="temporal-heartbeat-monitor"
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._check_interval)
            except asyncio.TimeoutError:
                pass  # timer-triggered
            await self._check_once()

    async def _check_once(self) -> int:
        """Single check; возвращает число stale активностей."""
        now = time.monotonic()
        stale: list[str] = []
        async with self._lock:
            for aid, last_beat in self._beats.items():
                if (now - last_beat) > self._stale_threshold:
                    stale.append(aid)
        self.stats.tracked = len(self._beats)
        self.stats.stale_activities = len(stale)
        self.stats.last_check_at = now
        if stale:
            self.stats.missed_heartbeats += len(stale)
            _logger.warning(
                "temporal.activity.stale_heartbeat",
                extra={
                    "count": len(stale),
                    "threshold_s": self._stale_threshold,
                    "sample": stale[:5],
                },
            )
        return len(stale)
