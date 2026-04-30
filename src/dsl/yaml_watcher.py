"""W25.1 — watchdog-наблюдатель за DSL-маршрутами в YAML.

Заменяет legacy ``DSLHotReloader`` (watchfiles). Поднимает
``watchdog.observers.Observer`` в отдельном потоке и async-consumer,
который дебаунсит file-event'ы и атомарно перезагружает маршруты в
``RouteRegistry``.

Гарантии:

* ``Observer`` живёт в отдельном threading-потоке (watchdog API);
  события публикуются в ``asyncio.Queue`` через
  ``loop.call_soon_threadsafe`` — никаких прямых cross-thread мутаций
  registry.
* Между первым event'ом и reload'ом проходит окно ``debounce_ms``.
  За это окно агрегируются последующие события (типичный сценарий —
  редактор пишет tmp-файл и переименовывает его).
* Reload **атомарен**: перед изменениями делается ``snapshot_state``;
  при ошибке — ``restore_state`` + событие пишется в лог. Реестр никогда
  не остаётся в полу-применённом виде.
* При удалении YAML-файла соответствующий маршрут удаляется из реестра
  через ``RouteRegistry.unregister`` (трекинг ``path -> route_id``).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from src.dsl.commands.registry import RouteRegistry
    from src.dsl.engine.pipeline import Pipeline

__all__ = ("DSLYamlWatcher", "PipelineLoader")

logger = logging.getLogger("dsl.yaml_watcher")

PipelineLoader = Callable[[Path], "Pipeline"]
"""Функция загрузки YAML-файла в Pipeline. Default: load_pipeline_from_file."""

_YAML_SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".dsl.yaml")


class _DSLEventHandler(FileSystemEventHandler):
    """watchdog event-handler — публикует пути в asyncio-очередь.

    Все методы запускаются в потоке Observer'а (не в asyncio loop'е).
    Поэтому используется ``loop.call_soon_threadsafe`` для безопасной
    передачи событий потребителю.
    """

    def __init__(
        self, queue: asyncio.Queue[tuple[str, str]], loop: asyncio.AbstractEventLoop
    ) -> None:
        self._queue = queue
        self._loop = loop

    def _push(self, kind: str, path: str) -> None:
        if not _is_yaml_path(path):
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (kind, path))
        except RuntimeError:
            # Loop закрыт — игнорируем, watcher уже останавливается.
            pass

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._push("created", str(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._push("modified", str(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._push("deleted", str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # rename = delete(src) + create(dest)
        self._push("deleted", str(event.src_path))
        self._push("created", str(getattr(event, "dest_path", event.src_path)))


def _is_yaml_path(path: str) -> bool:
    """Проверяет, что путь похож на DSL-YAML.

    Принимаются ``.yaml``, ``.yml``, ``.dsl.yaml``.
    """
    return any(path.endswith(suffix) for suffix in _YAML_SUFFIXES)


class DSLYamlWatcher:
    """watchdog-based hot-reload для DSL-маршрутов из YAML.

    Args:
        routes_dir: Каталог с DSL-файлами.
        route_registry: Реестр маршрутов для регистрации/обновления.
        loader: Функция загрузки одного YAML в Pipeline. По умолчанию —
            :func:`src.dsl.yaml_loader.load_pipeline_from_file`.
        debounce_ms: Окно агрегирования file-event'ов (мс).
    """

    def __init__(
        self,
        routes_dir: str | Path,
        route_registry: "RouteRegistry",
        loader: PipelineLoader | None = None,
        *,
        debounce_ms: int = 500,
    ) -> None:
        self._dir = Path(routes_dir)
        self._registry = route_registry
        self._loader: PipelineLoader = loader or _default_loader
        self._debounce_s = max(debounce_ms, 0) / 1000.0

        self._observer: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[tuple[str, str]] | None = None
        self._yaml_route_ids: dict[Path, str] = {}
        self._lock = threading.Lock()

    async def start(self) -> None:
        """Поднимает Observer + async-consumer.

        Идемпотентно: повторный вызов на работающем watcher'е — no-op.
        """
        if self._task is not None and not self._task.done():
            return

        self._dir.mkdir(parents=True, exist_ok=True)
        self._initial_load()

        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        observer = Observer()
        handler = _DSLEventHandler(self._queue, loop)
        observer.schedule(handler, str(self._dir), recursive=True)
        observer.start()
        self._observer = observer
        self._task = asyncio.create_task(self._consume_loop(), name="dsl-yaml-watcher")
        logger.info(
            "DSLYamlWatcher started: dir=%s, debounce=%dms, initial_routes=%d",
            self._dir,
            int(self._debounce_s * 1000),
            len(self._yaml_route_ids),
        )

    async def stop(self) -> None:
        """Останавливает Observer и async-consumer.

        Идемпотентно: повторный вызов на остановленном watcher'е — no-op.
        """
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._queue = None
        logger.info("DSLYamlWatcher stopped: dir=%s", self._dir)

    async def reload_all(self) -> dict[str, Any]:
        """Принудительный full reload без watchdog (для CLI).

        Возвращает отчёт ``{loaded, errors}``.
        """
        return await asyncio.to_thread(self._sync_reload_all)

    def _sync_reload_all(self) -> dict[str, Any]:
        snapshot = self._registry.snapshot_state()
        old_yaml_ids = dict(self._yaml_route_ids)
        try:
            new_yaml_ids = self._collect_and_apply()
            self._yaml_route_ids = new_yaml_ids
            return {"loaded": len(new_yaml_ids), "errors": []}
        except Exception as exc:
            self._registry.restore_state(snapshot)
            self._yaml_route_ids = old_yaml_ids
            logger.error("DSLYamlWatcher.reload_all failed: %s", exc)
            return {"loaded": 0, "errors": [str(exc)]}

    def _initial_load(self) -> None:
        """Однократная загрузка всех YAML при старте.

        Ошибки логируются, но не останавливают startup — watcher всё ещё
        полезен для последующих изменений.
        """
        if not self._dir.exists():
            return
        loaded: dict[Path, str] = {}
        for path in sorted(self._iter_yaml_files()):
            try:
                pipeline = self._loader(path)
                self._registry.register(pipeline)
                loaded[path] = pipeline.route_id
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "DSLYamlWatcher: initial load failed for %s: %s", path, exc
                )
        self._yaml_route_ids = loaded

    async def _consume_loop(self) -> None:
        """Цикл потребления file-event'ов с дебаунсом и atomic reload."""
        if self._queue is None:
            raise RuntimeError("DSLYamlWatcher: очередь событий не инициализирована")
        try:
            while True:
                _first_event = await self._queue.get()
                # Дебаунс: ждём окно тишины перед reload.
                await self._drain_debounce()
                # Полный rescan каталога — гарантирует консистентность
                # при удалениях, переименованиях и параллельных правках.
                await asyncio.to_thread(self._sync_reload_all)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("DSLYamlWatcher consume_loop crashed: %s", exc, exc_info=True)
            raise

    async def _drain_debounce(self) -> None:
        """Поглощает события до окна тишины ``_debounce_s``.

        Возвращается, когда между двумя событиями прошло больше окна.
        """
        if self._queue is None:
            raise RuntimeError("DSLYamlWatcher: очередь событий не инициализирована")
        if self._debounce_s == 0:
            return
        while True:
            try:
                await asyncio.wait_for(self._queue.get(), timeout=self._debounce_s)
            except asyncio.TimeoutError:
                return

    def _collect_and_apply(self) -> dict[Path, str]:
        """Полный rescan + atomic apply.

        - грузит все валидные YAML-файлы;
        - удаляет из registry route_id'ы, которых больше нет;
        - регистрирует/обновляет загруженные.

        Returns:
            dict[Path, str]: новый ``path -> route_id`` mapping.

        Raises:
            Exception: При ошибке загрузки любого файла — поднимается
            наверх, ``_sync_reload_all`` откатит снапшот.
        """
        with self._lock:
            current_files = sorted(self._iter_yaml_files())
            new_yaml_ids: dict[Path, str] = {}
            new_pipelines: list[Pipeline] = []
            for path in current_files:
                pipeline = self._loader(path)
                new_yaml_ids[path] = pipeline.route_id
                new_pipelines.append(pipeline)

            still_owned = set(new_yaml_ids.values())
            for old_path, old_rid in self._yaml_route_ids.items():
                if old_rid not in still_owned and old_path not in new_yaml_ids:
                    self._registry.unregister(old_rid)

            for pipeline in new_pipelines:
                self._registry.register(pipeline)

            return new_yaml_ids

    def _iter_yaml_files(self) -> list[Path]:
        if not self._dir.exists():
            return []
        seen: set[Path] = set()
        for suffix in _YAML_SUFFIXES:
            for path in self._dir.glob(f"**/*{suffix}"):
                if path.is_file():
                    seen.add(path)
        return sorted(seen)


def _default_loader(path: Path) -> Pipeline:
    """Default-loader: использует ``load_pipeline_from_file`` из yaml_loader."""
    from src.dsl.yaml_loader import load_pipeline_from_file

    return load_pipeline_from_file(path)
