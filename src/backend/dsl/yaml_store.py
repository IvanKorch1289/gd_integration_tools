"""YAMLStore — файловое хранилище DSL-маршрутов в YAML.

Хранит каждый Pipeline как отдельный YAML-файл в директории ``store_dir``.
Имя файла = ``{route_id}.yaml`` (слэши → двойные подчёркивания).

Пример::

    store = YAMLStore("/app/routes")
    store.save(pipeline)
    pipeline = store.load("orders.create")
    names = store.list()
    diff = store.diff(pipeline_v1, pipeline_v2)
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.engine.pipeline import Pipeline

__all__ = ("YAMLStore",)

_logger = logging.getLogger("dsl.yaml_store")


def _route_to_filename(route_id: str) -> str:
    """Конвертирует route_id в безопасное имя файла."""
    return route_id.replace("/", "__").replace(":", "__") + ".yaml"


def _filename_to_route(filename: str) -> str:
    """Восстанавливает route_id из имени файла."""
    return filename.removesuffix(".yaml").replace("__", ".")


class YAMLStore:
    """Файловое хранилище Pipeline-маршрутов в YAML-формате.

    Args:
        store_dir: Путь к директории хранилища.
            Создаётся автоматически при необходимости.
    """

    def __init__(self, store_dir: str | Path) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, pipeline: Pipeline) -> Path:
        """Сохраняет Pipeline в YAML-файл.

        Args:
            pipeline: Pipeline для сохранения.

        Returns:
            Path: Путь к сохранённому файлу.

        Raises:
            ValueError: Если у Pipeline нет сериализуемых процессоров.
        """
        filename = _route_to_filename(pipeline.route_id)
        path = self._dir / filename
        path.write_text(pipeline.to_yaml(), encoding="utf-8")
        _logger.info("YAMLStore: saved %r → %s", pipeline.route_id, path)
        return path

    def load(self, route_id: str) -> Pipeline:
        """Загружает Pipeline из YAML-файла.

        Args:
            route_id: Идентификатор маршрута.

        Returns:
            Загруженный Pipeline.

        Raises:
            FileNotFoundError: Если файл не найден.
            ValueError: Если YAML некорректен.
        """
        from src.backend.dsl.yaml_loader import load_pipeline_from_yaml

        filename = _route_to_filename(route_id)
        path = self._dir / filename
        if not path.exists():
            raise FileNotFoundError(
                f"YAMLStore: маршрут {route_id!r} не найден в {self._dir}"
            )
        yaml_str = path.read_text(encoding="utf-8")
        return load_pipeline_from_yaml(yaml_str)

    def delete(self, route_id: str) -> bool:
        """Удаляет файл маршрута.

        Args:
            route_id: Идентификатор маршрута.

        Returns:
            True если файл был удалён, False если не существовал.
        """
        path = self._dir / _route_to_filename(route_id)
        if path.exists():
            path.unlink()
            _logger.info("YAMLStore: deleted %r", route_id)
            return True
        return False

    def list(self) -> list[str]:
        """Возвращает список route_id всех сохранённых маршрутов.

        Returns:
            Отсортированный список route_id.
        """
        return sorted(_filename_to_route(p.name) for p in self._dir.glob("*.yaml"))

    def exists(self, route_id: str) -> bool:
        """Проверяет, существует ли маршрут в хранилище."""
        return (self._dir / _route_to_filename(route_id)).exists()

    def diff(self, pipeline_a: Pipeline, pipeline_b: Pipeline) -> str:
        """Возвращает unified-diff между YAML-представлениями двух Pipeline.

        Args:
            pipeline_a: Исходный Pipeline.
            pipeline_b: Целевой Pipeline.

        Returns:
            Строка unified-diff (пустая если изменений нет).
        """
        yaml_a = pipeline_a.to_yaml().splitlines(keepends=True)
        yaml_b = pipeline_b.to_yaml().splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(
                yaml_a,
                yaml_b,
                fromfile=f"{pipeline_a.route_id}.yaml",
                tofile=f"{pipeline_b.route_id}.yaml",
            )
        )

    def load_all(self) -> list[Pipeline]:
        """Загружает все маршруты из хранилища.

        Returns:
            Список Pipeline (ошибочные файлы пропускаются с предупреждением).
        """
        from src.backend.dsl.yaml_loader import load_pipeline_from_file

        pipelines = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                pipeline = load_pipeline_from_file(path)
                pipelines.append(pipeline)
            except Exception as exc:
                _logger.warning(
                    "YAMLStore: не удалось загрузить %s: %s", path.name, exc
                )
        return pipelines
