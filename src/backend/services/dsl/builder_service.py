"""W25.2 — DSLBuilderService: фасад для просмотра/сохранения DSL-маршрутов.

Используется Streamlit-страницей ``32_DSL_Builder`` и dev-CLI
``manage.py dsl write-yaml``. Обращается к ``RouteRegistry`` и
``YAMLStore`` через core-API; никаких прямых impl-импортов.

Сохранение в YAML защищено environment-guard'ом: запись разрешена
только когда ``settings.app.environment == "development"``. На staging
и production write-back недоступен (read-only YAMLStore).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.backend.core.config.settings import settings as app_settings
from src.backend.dsl.commands.registry import route_registry
from src.backend.dsl.yaml_store import YAMLStore

if TYPE_CHECKING:
    from src.backend.dsl.engine.pipeline import Pipeline

__all__ = ("DSLBuilderService", "SaveResult", "get_dsl_builder_service")

_logger = logging.getLogger("services.dsl.builder")

_DEV_ENVIRONMENT = "development"


@dataclass(slots=True, frozen=True)
class SaveResult:
    """Результат write-back операции.

    Attrs:
        path: Путь сохранённого/целевого файла.
        written: ``True`` если файл реально записан, ``False`` —
            если запись была заблокирована (env-guard или dry-run).
        diff: unified-diff между предыдущей и новой версией (пустой
            при отсутствии изменений или новом файле).
        reason: Причина для ``written=False``.
    """

    path: Path
    written: bool
    diff: str = ""
    reason: str | None = None


class DSLBuilderService:
    """Фасад для DSL builder UI и CLI.

    Args:
        store_dir: Каталог YAMLStore'а (по умолчанию из
            ``settings.dsl.routes_dir``).
        environment: Текущая среда (override для тестов). По умолчанию —
            ``settings.app.environment``.
    """

    def __init__(
        self, store_dir: str | Path | None = None, *, environment: str | None = None
    ) -> None:
        self._dir = Path(store_dir) if store_dir else Path(app_settings.dsl.routes_dir)
        self._env = environment or app_settings.app.environment
        self._store = YAMLStore(self._dir)

    # ── Read API ────────────────────────────────────────────

    def list_routes(self) -> tuple[str, ...]:
        """Возвращает все route_id, известные runtime'у."""
        return route_registry.list_routes()

    def get_pipeline(self, route_id: str) -> Pipeline | None:
        """Возвращает Pipeline или None, если не зарегистрирован."""
        return route_registry.get_optional(route_id)

    def render_yaml(self, route_id: str) -> str:
        """Сериализует Pipeline в YAML.

        Возвращает пустую строку если route_id не найден.
        """
        pipeline = self.get_pipeline(route_id)
        if pipeline is None:
            return ""
        return pipeline.to_yaml()

    def preview_diff(self, route_id: str) -> str:
        """unified-diff между текущим YAML в store и runtime-Pipeline.

        Возвращает пустую строку при отсутствии файла или изменений.
        """
        pipeline = self.get_pipeline(route_id)
        if pipeline is None:
            return ""
        if not self._store.exists(route_id):
            return ""
        existing = self._store.load(route_id)
        return self._store.diff(existing, pipeline)

    # ── Write API ──────────────────────────────────────────

    def is_write_enabled(self) -> bool:
        """Разрешена ли запись в YAMLStore (только dev)."""
        return self._env == _DEV_ENVIRONMENT

    def save_route(self, route_id: str, *, dry_run: bool = False) -> SaveResult:
        """Сохраняет runtime-Pipeline в YAMLStore.

        Args:
            route_id: Идентификатор маршрута.
            dry_run: Если ``True`` — только diff, без записи.

        Returns:
            SaveResult с путём, флагом фактической записи и diff'ом.

        Raises:
            KeyError: Если route_id не зарегистрирован.
            PermissionError: Если environment != "development".
        """
        pipeline = self.get_pipeline(route_id)
        if pipeline is None:
            raise KeyError(f"Route {route_id!r} не зарегистрирован")

        diff = self.preview_diff(route_id)

        if not self.is_write_enabled():
            return SaveResult(
                path=self._dir / f"{route_id}.yaml",
                written=False,
                diff=diff,
                reason=f"write disabled in environment={self._env}",
            )

        if dry_run:
            return SaveResult(
                path=self._dir / f"{route_id}.yaml",
                written=False,
                diff=diff,
                reason="dry_run",
            )

        path = self._store.save(pipeline)
        _logger.info("DSLBuilderService: saved %s → %s", route_id, path)
        return SaveResult(path=path, written=True, diff=diff)


_singleton: DSLBuilderService | None = None


def get_dsl_builder_service() -> DSLBuilderService:
    """Возвращает кешированный экземпляр сервиса.

    Lazy-инициализация чтобы избежать чтения settings при import-time
    в тестах, где settings ещё не сформированы.
    """
    global _singleton
    if _singleton is None:
        _singleton = DSLBuilderService()
    return _singleton
