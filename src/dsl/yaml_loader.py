"""YAML Pipeline Loader — declarative pipeline definitions.

Позволяет описывать DSL-маршруты в YAML и загружать их в runtime.
Полезно для non-developers, конфигурации без перекомпиляции,
и хранения pipeline в БД/файловой системе.

Пример YAML::

    route_id: etl.orders
    source: timer:300s
    description: ETL orders from external API
    processors:
      - http_call:
          url: https://api.example.com/orders
          method: GET
          timeout: 30
      - normalize: {}
      - sort:
          key_field: created_at
          reverse: true
      - dispatch_action:
          action: analytics.insert_batch
      - log:
          level: info
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.dsl.builder import RouteBuilder
from src.dsl.engine.pipeline import Pipeline

__all__ = (
    "load_pipeline_from_yaml",
    "load_pipeline_from_file",
    "load_all_from_directory",
)

logger = logging.getLogger("dsl.yaml_loader")


def load_pipeline_from_yaml(yaml_str: str) -> Pipeline:
    """Парсит YAML-строку в Pipeline.

    Если в spec'е указан ``apiVersion`` отличный от текущего (W25.3
    ``CURRENT_VERSION``), перед сборкой spec прогоняется через
    зарегистрированные миграции (см. ``src/dsl/versioning``).

    Args:
        yaml_str: YAML-описание маршрута.

    Returns:
        Готовый Pipeline.

    Raises:
        ValueError: Неверный формат YAML или неизвестный процессор.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML required: pip install pyyaml") from exc

    data = yaml.safe_load(yaml_str)
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping (dict)")

    from src.dsl.versioning import CURRENT_VERSION, apply_migrations

    if data.get("apiVersion") != CURRENT_VERSION:
        data = apply_migrations(data, target_version=CURRENT_VERSION)

    return _build_pipeline(data)


def load_pipeline_from_file(path: str | Path) -> Pipeline:
    """Загружает Pipeline из YAML-файла."""
    return load_pipeline_from_yaml(Path(path).read_text(encoding="utf-8"))


def load_all_from_directory(directory: str | Path) -> list[Pipeline]:
    """Загружает все .yaml/.yml файлы из директории как Pipelines."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    pipelines: list[Pipeline] = []
    for yaml_file in sorted(dir_path.glob("*.y*ml")):
        try:
            pipeline = load_pipeline_from_file(yaml_file)
            pipelines.append(pipeline)
            logger.info(
                "Loaded pipeline '%s' from %s", pipeline.route_id, yaml_file.name
            )
        except Exception as exc:
            logger.error("Failed to load %s: %s", yaml_file, exc)

    return pipelines


def _build_pipeline(spec: dict[str, Any]) -> Pipeline:
    """Строит Pipeline из распарсенного spec."""
    route_id = spec.get("route_id")
    if not route_id:
        raise ValueError("Missing required field: route_id")

    source = spec.get("source", f"yaml:{route_id}")
    description = spec.get("description")

    builder = RouteBuilder.from_(route_id, source=source, description=description)

    processors_spec = spec.get("processors", [])
    if not isinstance(processors_spec, list):
        raise ValueError("'processors' must be a list")

    for proc_spec in processors_spec:
        _apply_processor(builder, proc_spec)

    return builder.build()


def _is_allowed_processor(builder: RouteBuilder, name: str) -> bool:
    """Whitelist-проверка имени процессора (A2 / ADR-003).

    Разрешены:
    - публичные атрибуты (не начинаются с '_'),
    - объявленные в ``RouteBuilder`` или его миксинах,
    - атрибуты, явно помеченные как ``__dsl_processor__ = True`` (опционально).

    Запрещены:
    - dunder (``__...__``) — защита от ``__class__``, ``__globals__`` и т.п.,
    - приватные (``_foo``),
    - атрибуты из стандартных Python/типов.
    """
    if not isinstance(name, str) or not name.isidentifier():
        return False
    if name.startswith("_"):
        return False
    # Класс builder-а (и его mixin-ы) должны явно содержать метод в public API.
    for cls in type(builder).mro():
        if cls in (object, type):
            continue
        attr = cls.__dict__.get(name)
        if attr is None:
            continue
        # Разрешаем только callable методы/property — не data-атрибуты.
        if callable(attr) or isinstance(attr, (property, classmethod, staticmethod)):
            return True
    return False


def _apply_processor(builder: RouteBuilder, spec: Any) -> None:
    """Применяет один процессор к builder.

    Поддерживаются 2 формата:
    - {name: {params}} — dict с одним ключом
    - "name" — строка без параметров
    """
    if isinstance(spec, str):
        proc_name = spec
        params: dict[str, Any] = {}
    elif isinstance(spec, dict):
        if len(spec) != 1:
            raise ValueError(
                f"Processor spec must have one key, got: {list(spec.keys())}"
            )
        proc_name = next(iter(spec))
        raw_params = spec[proc_name]
        params = raw_params if isinstance(raw_params, dict) else {}
    else:
        raise ValueError(f"Invalid processor spec: {spec}")

    if not _is_allowed_processor(builder, proc_name):
        raise ValueError(
            f"Unknown or forbidden processor '{proc_name}'. "
            "YAML DSL принимает только публичные методы RouteBuilder (A2 whitelist)."
        )

    method = getattr(builder, proc_name)
    if not callable(method):
        raise ValueError(f"Processor '{proc_name}' не является вызываемым методом.")

    try:
        method(**params)
    except TypeError as exc:
        raise ValueError(f"Invalid params for '{proc_name}': {exc}") from exc
