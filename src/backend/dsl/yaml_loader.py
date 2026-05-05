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


def _build_sub(parent: RouteBuilder, specs: list[Any]) -> list[Any]:
    """Строит sub-pipeline из nested-spec'ов через временный ``RouteBuilder``.

    Используется для control-flow процессоров (do_try / retry / parallel /
    saga / choice), где параметры содержат вложенные списки процессоров.

    Args:
        parent: Родительский RouteBuilder (нужен только для route_id/source —
            sub-pipeline собирается изолированно и затем возвращается списком).
        specs: Список nested-spec'ов (тот же формат, что и верхнего уровня).

    Returns:
        Список собранных :class:`BaseProcessor`.
    """
    sub_builder = RouteBuilder.from_(
        f"{parent.route_id}.__sub__", source=parent.source or ""
    )
    for s in specs:
        _apply_processor(sub_builder, s)
    return list(sub_builder._processors)


def _apply_processor(builder: RouteBuilder, spec: Any) -> None:
    """Применяет один процессор к builder.

    Поддерживаются 2 формата:
    - {name: {params}} — dict с одним ключом
    - "name" — строка без параметров

    Для control-flow процессоров (``do_try``, ``retry``, ``parallel``,
    ``saga``, ``choice``) поддерживается nested-формат: вложенные
    списки процессоров рекурсивно собираются перед передачей в builder.
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

    if proc_name in {"do_try", "retry", "parallel", "saga", "choice"}:
        params = _materialize_control_flow_params(builder, proc_name, params)

    try:
        method(**params)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid params for '{proc_name}': {exc}") from exc


def _materialize_control_flow_params(
    builder: RouteBuilder, proc_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Рекурсивно превращает nested-spec'и в готовые объекты для builder.

    Args:
        builder: Родительский RouteBuilder (для context route_id/source).
        proc_name: Имя control-flow процессора.
        params: Сырые kwargs из YAML.

    Returns:
        Новый dict kwargs с подставленными ``BaseProcessor`` / ``ChoiceBranch``
        / ``SagaStep`` объектами.
    """
    from src.dsl.engine.processors import ChoiceBranch, SagaStep

    materialized = dict(params)

    match proc_name:
        case "do_try":
            for key in ("try_processors", "catch_processors", "finally_processors"):
                if key in materialized and isinstance(materialized[key], list):
                    materialized[key] = _build_sub(builder, materialized[key])
        case "retry":
            if "processors" in materialized and isinstance(
                materialized["processors"], list
            ):
                materialized["processors"] = _build_sub(
                    builder, materialized["processors"]
                )
        case "parallel":
            branches = materialized.get("branches")
            if isinstance(branches, dict):
                materialized["branches"] = {
                    name: _build_sub(builder, sub_specs)
                    for name, sub_specs in branches.items()
                }
        case "saga":
            steps = materialized.get("steps")
            if isinstance(steps, list):
                saga_steps: list[SagaStep] = []
                for entry in steps:
                    if not isinstance(entry, dict):
                        raise ValueError(f"Saga step must be a mapping, got: {entry!r}")
                    forward_spec = entry.get("forward")
                    if forward_spec is None:
                        raise ValueError("Saga step missing 'forward'")
                    forward = _build_sub(builder, [forward_spec])[0]
                    compensate = None
                    if entry.get("compensate") is not None:
                        compensate = _build_sub(builder, [entry["compensate"]])[0]
                    saga_steps.append(SagaStep(forward=forward, compensate=compensate))
                materialized["steps"] = saga_steps
        case "choice":
            when = materialized.get("when")
            if isinstance(when, list):
                branches_obj: list[ChoiceBranch] = []
                for entry in when:
                    if not isinstance(entry, dict) or "expr" not in entry:
                        raise ValueError(
                            "Choice branch must be a mapping with 'expr' (JMESPath)"
                        )
                    sub_specs = entry.get("processors", []) or []
                    branches_obj.append(
                        ChoiceBranch(
                            expr=entry["expr"],
                            processors=_build_sub(builder, sub_specs),
                        )
                    )
                materialized["when"] = branches_obj
            otherwise = materialized.get("otherwise")
            if isinstance(otherwise, list):
                materialized["otherwise"] = _build_sub(builder, otherwise)

    return materialized
