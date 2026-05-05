"""Wave B — DSL hot-reload поверх ``watchfiles``.

Заменяет watchdog-based реализацию (W25.1). Использует rust-based
``watchfiles.awatch`` — единый FS-watcher для всего проекта (см.
ADR-041 ``fs-watcher-unification``).

Гарантии (сохранены от watchdog-версии):

* Reload **атомарен**: перед изменениями делается ``snapshot_state``;
  при ошибке — ``restore_state`` + событие пишется в лог. Реестр никогда
  не остаётся в полу-применённом виде.
* При удалении YAML-файла соответствующий маршрут удаляется из реестра
  через :meth:`RouteRegistry.unregister`.
* Дебаунс file-event'ов делегирован ``awatch(debounce=...)`` —
  не дублируем логику ожидания «окна тишины» в Python.
* Public API (``DSLYamlWatcher``, ``PipelineLoader``) сохранён —
  существующие импортёры (``manage.py``, ``plugins/composition/lifecycle``,
  тесты) продолжают работать без правок.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchfiles import awatch

if TYPE_CHECKING:
    from src.dsl.commands.registry import RouteRegistry
    from src.dsl.engine.pipeline import Pipeline

__all__ = ("DSLYamlWatcher", "PipelineLoader")

logger = logging.getLogger("dsl.yaml_watcher")

PipelineLoader = Callable[[Path], "Pipeline"]
"""Функция загрузки YAML-файла в Pipeline. Default: load_pipeline_from_file."""

_YAML_SUFFIXES: tuple[str, ...] = (".yaml", ".yml", ".dsl.yaml")


def _is_yaml_path(path: str) -> bool:
    """Проверяет, что путь похож на DSL-YAML.

    Принимаются ``.yaml``, ``.yml``, ``.dsl.yaml``.
    """
    return any(path.endswith(suffix) for suffix in _YAML_SUFFIXES)


class DSLYamlWatcher:
    """watchfiles-based hot-reload для DSL-маршрутов из YAML.

    Args:
        routes_dir: Каталог с DSL-файлами.
        route_registry: Реестр маршрутов для регистрации/обновления.
        loader: Функция загрузки одного YAML в Pipeline. По умолчанию —
            :func:`src.dsl.yaml_loader.load_pipeline_from_file`.
        debounce_ms: Окно агрегирования file-event'ов (мс).
            Передаётся напрямую в ``watchfiles.awatch(debounce=...)``.
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
        self._debounce_ms = max(debounce_ms, 0)

        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._yaml_route_ids: dict[Path, str] = {}

    async def start(self) -> None:
        """Поднимает async-consumer поверх ``awatch``.

        Идемпотентно: повторный вызов на работающем watcher'е — no-op.
        """
        if self._task is not None and not self._task.done():
            return

        self._dir.mkdir(parents=True, exist_ok=True)
        self._initial_load()

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._consume_loop(), name="dsl-yaml-watcher")
        logger.info(
            "DSLYamlWatcher started: dir=%s, debounce=%dms, initial_routes=%d",
            self._dir,
            self._debounce_ms,
            len(self._yaml_route_ids),
        )

    async def stop(self) -> None:
        """Останавливает async-consumer.

        Идемпотентно: повторный вызов на остановленном watcher'е — no-op.
        """
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("DSLYamlWatcher stopped: dir=%s", self._dir)

    async def reload_all(self) -> dict[str, Any]:
        """Принудительный full reload без watchfiles (для CLI).

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
        """Цикл потребления file-event'ов через ``awatch``.

        Дебаунс делегирован ``watchfiles`` (ничего не блокирует loop).
        Каждая итерация — атомарный rescan каталога: гарантирует
        консистентность при удалениях, переименованиях и параллельных
        правках.
        """
        try:
            async for changes in awatch(
                self._dir,
                stop_event=self._stop_event,
                recursive=True,
                debounce=self._debounce_ms,
            ):
                if not any(_is_yaml_path(path) for _, path in changes):
                    continue
                await asyncio.to_thread(self._sync_reload_all)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("DSLYamlWatcher consume_loop crashed: %s", exc, exc_info=True)
            raise

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
