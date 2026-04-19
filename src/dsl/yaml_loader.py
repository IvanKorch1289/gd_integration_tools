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

from app.dsl.builder import RouteBuilder
from app.dsl.engine.pipeline import Pipeline

__all__ = ("load_pipeline_from_yaml", "load_pipeline_from_file", "load_all_from_directory")

logger = logging.getLogger("dsl.yaml_loader")


def load_pipeline_from_yaml(yaml_str: str) -> Pipeline:
    """Парсит YAML-строку в Pipeline.

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
            logger.info("Loaded pipeline '%s' from %s", pipeline.route_id, yaml_file.name)
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
            raise ValueError(f"Processor spec must have one key, got: {list(spec.keys())}")
        proc_name = next(iter(spec))
        raw_params = spec[proc_name]
        params = raw_params if isinstance(raw_params, dict) else {}
    else:
        raise ValueError(f"Invalid processor spec: {spec}")

    method = getattr(builder, proc_name, None)
    if method is None or not callable(method):
        raise ValueError(
            f"Unknown processor '{proc_name}'. "
            f"Check RouteBuilder methods."
        )

    try:
        method(**params)
    except TypeError as exc:
        raise ValueError(f"Invalid params for '{proc_name}': {exc}") from exc
