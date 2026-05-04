"""Wave 7.1 — Dask backend для тяжёлых аналитических вычислений.

Назначение: вынести CPU-bound аналитические job'ы из event loop в
distributed-pool. Используется DSL-процессором ``DaskComputeProcessor``
(см. :mod:`src.dsl.engine.processors.dask_compute`).

Профили:

* ``dev_light`` / ``dev`` — :class:`LocalCluster` (in-process workers).
* ``staging`` / ``prod`` — distributed cluster по адресу
  ``settings.app.dask_scheduler_address`` (если задан) либо LocalCluster.

Контракт singleton: один :class:`DaskBackend` на процесс, ленивая
инициализация при первом ``submit``. На shutdown — graceful close
кластера.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ("DaskBackend", "get_dask_backend", "reset_dask_backend")

_logger = logging.getLogger("infrastructure.execution.dask")


class DaskBackend:
    """Управляет жизненным циклом Dask-кластера + клиента.

    Args:
        scheduler_address: Адрес distributed scheduler (``tcp://host:port``).
            Если ``None`` — поднимается :class:`LocalCluster`.
        n_workers: Число воркеров для LocalCluster (default 4).
        threads_per_worker: Потоков на воркер (default 2).
    """

    def __init__(
        self,
        *,
        scheduler_address: str | None = None,
        n_workers: int = 4,
        threads_per_worker: int = 2,
    ) -> None:
        """Сохраняет конфигурацию; кластер поднимается лениво."""
        self._scheduler_address = scheduler_address
        self._n_workers = n_workers
        self._threads = threads_per_worker
        self._client: Any | None = None
        self._cluster: Any | None = None
        self._lock = threading.Lock()

    @property
    def scheduler_address(self) -> str | None:
        """Адрес активного scheduler'а (после :meth:`ensure_started`)."""
        if self._client is None:
            return None
        return getattr(self._client, "scheduler", None) and str(
            self._client.scheduler.address
        )

    def ensure_started(self) -> Any:
        """Гарантирует, что Dask-клиент существует.

        Returns:
            ``distributed.Client`` готовый к ``submit`` / ``compute``.
        """
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            from dask.distributed import Client, LocalCluster

            if self._scheduler_address:
                _logger.info(
                    "DaskBackend: подключение к distributed scheduler %s",
                    self._scheduler_address,
                )
                self._client = Client(self._scheduler_address)
            else:
                _logger.info(
                    "DaskBackend: запуск LocalCluster n_workers=%d threads=%d",
                    self._n_workers,
                    self._threads,
                )
                self._cluster = LocalCluster(
                    n_workers=self._n_workers,
                    threads_per_worker=self._threads,
                    processes=False,
                    silence_logs=logging.WARNING,
                    dashboard_address=None,
                )
                self._client = Client(self._cluster)
            return self._client

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Отправить job в Dask-cluster, вернуть Future.

        Returns:
            ``distributed.Future`` — caller вызывает ``.result()`` / await.
        """
        client = self.ensure_started()
        return client.submit(fn, *args, **kwargs)

    async def gather(self, futures: Any) -> Any:
        """Собрать результаты futures (async-aware)."""
        import asyncio

        client = self.ensure_started()
        return await asyncio.get_event_loop().run_in_executor(
            None, client.gather, futures
        )

    def compute(self, graph: Any) -> Any:
        """Вычислить dask-graph (delayed / dataframe / bag) синхронно."""
        client = self.ensure_started()
        return client.compute(graph, sync=True)

    def close(self) -> None:
        """Закрыть клиент и LocalCluster (если был поднят)."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    _logger.exception("DaskBackend: close client failed")
                self._client = None
            if self._cluster is not None:
                try:
                    self._cluster.close()
                except Exception:
                    _logger.exception("DaskBackend: close cluster failed")
                self._cluster = None


_backend: DaskBackend | None = None
_backend_lock = threading.Lock()


def get_dask_backend(
    *,
    scheduler_address: str | None = None,
    n_workers: int = 4,
    threads_per_worker: int = 2,
) -> DaskBackend:
    """Singleton-accessor :class:`DaskBackend` (process-wide)."""
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is None:
            _backend = DaskBackend(
                scheduler_address=scheduler_address,
                n_workers=n_workers,
                threads_per_worker=threads_per_worker,
            )
        return _backend


def reset_dask_backend() -> None:
    """Сбросить singleton (для тестов / повторного create_app)."""
    global _backend
    with _backend_lock:
        if _backend is not None:
            _backend.close()
            _backend = None
