"""S62 W4 — loaders.py part of yaml_loader decomp.

Funcs: load_pipeline_from_yaml, load_pipeline_from_file, load_all_from_directory.

public loaders (yaml/file/directory).
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.yaml_loader.build import _build_pipeline
from src.backend.dsl.yaml_loader.resolve import (
    _is_route_composition_include_enabled,
    _resolve_include_extends,
)

logger = get_logger(__name__)

# Sentinel for "not set" to distinguish from None
_MISSING = object()


def load_pipeline_from_yaml(yaml_str: str, base_path: Path | None = None) -> Pipeline:
    """Парсит YAML-строку в Pipeline.

    Если в spec'е указан ``apiVersion`` отличный от текущего (W25.3
    ``CURRENT_VERSION``), перед сборкой spec прогоняется через
    зарегистрированные миграции (см. ``src/dsl/versioning``).

    При route_composition_include=True поддерживает include:/extends: с
    cycle detection (один уровень включения).

    Args:
        yaml_str: YAML-описание маршрута.
        base_path: Optional base path for resolving relative include/extends paths.

    Returns:
        Готовый Pipeline.

    Raises:
        ValueError: Неверный формат YAML или неизвестный процессор.
        RuntimeError: Цикл в include:/extends: цепочке.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML required: pip install pyyaml") from exc

    data = yaml.safe_load(yaml_str)
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping (dict)")

    # S157 W2: use module attribute lookup (not local binding) so that
    # monkeypatching yaml_loader._is_route_composition_include_enabled
    # in tests takes effect. Was 'if _is_route_composition_include_enabled():'
    # which used the local binding from 'from ... import' and ignored patches.
    from src.backend.dsl import yaml_loader as _yaml_loader

    if _yaml_loader._is_route_composition_include_enabled():
        data = _resolve_include_extends(data, base_path)

    from src.backend.dsl.versioning import CURRENT_VERSION, apply_migrations

    if data.get("apiVersion") != CURRENT_VERSION:
        data = apply_migrations(data, target_version=CURRENT_VERSION)

    return _build_pipeline(data)


def load_pipeline_from_file(path: str | Path) -> Pipeline:
    """Загружает Pipeline из YAML-файла.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Готовый Pipeline.
    """
    file_path = Path(path)
    yaml_str = file_path.read_text(encoding="utf-8")
    return load_pipeline_from_yaml(yaml_str, base_path=file_path.parent)


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
