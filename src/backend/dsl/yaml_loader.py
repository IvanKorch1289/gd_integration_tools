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

K3 S19 W2: route composition via include:/extends: с cycle detection.
При route_composition_include=True *.dsl.yaml поддерживает::

    # Include shared steps from other YAML files (one level)
    include:
      - ./common-steps.yaml
      - ./shared-transforms.yaml

    # Extend a base route (inherits all fields, can override)
    extends: ./base-route.yaml

Cycle detection: RuntimeError raised if include/extends chain creates a cycle.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline

__all__ = (
    "load_pipeline_from_yaml",
    "load_pipeline_from_file",
    "load_all_from_directory",
)

logger = logging.getLogger("dsl.yaml_loader")

# Sentinel for "not set" to distinguish from None
_MISSING = object()


def _is_route_composition_include_enabled() -> bool:
    """Check if route_composition_include feature flag is enabled."""
    try:
        from src.backend.core.config.features import feature_flags
        return getattr(feature_flags, "route_composition_include", False)
    except ImportError:
        return False


def _resolve_include_extends(
    data: dict[str, Any],
    base_path: Path | None = None,
    _visited: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve include: and extends: fields in a YAML spec with cycle detection.

    Args:
        data: Parsed YAML dict.
        base_path: Base directory for resolving relative paths.
        _visited: Internal set for cycle detection (files being processed).

    Returns:
        Merged spec with include:/extends: resolved.

    Raises:
        RuntimeError: If a cycle is detected in include/extends chain.
    """
    if _visited is None:
        _visited = set()

    # If feature flag is off, return data as-is
    if not _is_route_composition_include_enabled():
        return data

    # Work on a copy to avoid mutating the original
    spec = dict(data)

    # Handle extends: - inherit from a base YAML file
    extends_path = spec.pop("extends", None)
    if extends_path is not None:
        ext_str = str(extends_path)

        if base_path is not None:
            resolved_path = (base_path.parent / ext_str).resolve()
        else:
            resolved_path = Path(ext_str).resolve()

        # Check existence BEFORE tracking to avoid false-positive on first pass
        if not resolved_path.exists():
            raise FileNotFoundError(
                f"Extended YAML file not found: {resolved_path}"
            )

        # Track resolved path to avoid cycle detection
        resolved_str = str(resolved_path)
        if resolved_str in _visited:
            raise RuntimeError(
                f"Cycle detected in extends: chain: {resolved_str} is already "
                f"being processed. Chain: {_visited}"
            )
        _visited.add(resolved_str)

        ext_yaml_str = resolved_path.read_text(encoding="utf-8")
        import yaml
        base_data = yaml.safe_load(ext_yaml_str)
        if not isinstance(base_data, dict):
            raise ValueError(
                f"Extended YAML must be a mapping, got: {type(base_data).__name__}"
            )

        # Recursively resolve the base (in case it also has include/extends)
        base_data = _resolve_include_extends(
            base_data, resolved_path.parent, _visited
        )

        # Merge: child overrides parent
        # Start with base, then overlay child (child takes precedence)
        merged: dict[str, Any] = {}
        # First add all from base
        for k, v in base_data.items():
            if k not in ("include", "extends"):  # Don't copy composition fields
                merged[k] = v
        # Then overlay from child (allows overriding)
        for k, v in spec.items():
            if k not in ("include", "extends"):
                merged[k] = v
        spec = merged

    # Handle include: - include steps from other YAML files (one level)
    include_paths = spec.pop("include", None)
    if include_paths is not None:
        if isinstance(include_paths, str):
            include_paths = [include_paths]
        if not isinstance(include_paths, list):
            raise ValueError(
                f"include: must be a string or list of strings, got: "
                f"{type(include_paths).__name__}"
            )

        # Collect steps from all included files
        all_steps: list[Any] = []

        for inc_path in include_paths:
            inc_str = str(inc_path)

            if base_path is not None:
                resolved_inc = (base_path.parent / inc_str).resolve()
            else:
                resolved_inc = Path(inc_str).resolve()

            # Check existence BEFORE tracking to avoid false-positive on first pass
            if not resolved_inc.exists():
                raise FileNotFoundError(
                    f"Included YAML file not found: {resolved_inc}"
                )

            resolved_inc_str = str(resolved_inc)
            if resolved_inc_str in _visited:
                raise RuntimeError(
                    f"Cycle detected in include: chain: {resolved_inc_str} is "
                    f"already being processed. Chain: {_visited}"
                )
            _visited.add(resolved_inc_str)

            inc_yaml_str = resolved_inc.read_text(encoding="utf-8")
            import yaml
            inc_data = yaml.safe_load(inc_yaml_str)
            if not isinstance(inc_data, dict):
                raise ValueError(
                    f"Included YAML must be a mapping, got: "
                    f"{type(inc_data).__name__}"
                )

            # Get steps from included file
            inc_steps = inc_data.get("steps", [])
            if not isinstance(inc_steps, list):
                raise ValueError(
                    f"steps: in included file must be a list, got: "
                    f"{type(inc_steps).__name__}"
                )
            all_steps.extend(inc_steps)

        # Append included steps to the current spec's steps
        existing_steps = spec.get("steps", [])
        if not isinstance(existing_steps, list):
            raise ValueError(
                f"steps: must be a list, got: {type(existing_steps).__name__}"
            )
        spec["steps"] = existing_steps + all_steps

    return spec


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

    # Resolve include:/extends: if feature flag is enabled
    if _is_route_composition_include_enabled():
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


def _build_pipeline(spec: dict[str, Any]) -> Pipeline:
    """Строит Pipeline из распарсенного spec."""
    route_id = spec.get("route_id")
    if not route_id:
        raise ValueError("Missing required field: route_id")

    source = spec.get("source", f"yaml:{route_id}")
    description = spec.get("description")

    builder = RouteBuilder.from_(route_id, source=source, description=description)

    # Support both `processors` (original) and `steps` (V11 route format)
    processors_spec = spec.get("processors") or spec.get("steps", [])
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
    from src.backend.dsl.engine.processors import ChoiceBranch, SagaStep

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
