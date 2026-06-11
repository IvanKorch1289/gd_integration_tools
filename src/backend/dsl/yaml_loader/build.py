from __future__ import annotations

"""S62 W4 — build.py part of yaml_loader decomp.

Funcs: _build_pipeline, _is_allowed_processor, _build_sub, _apply_processor.

pipeline building (build_pipeline + processor gating + sub-pipeline + apply processor).
"""

from typing import Any

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline

# Sentinel for "not set" to distinguish from None
_MISSING = object()


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
        f"{parent.route_id}.__sub__",  # type: ignore[attr-defined]
        source=parent.source or "",  # type: ignore[attr-defined]
    )
    for s in specs:
        _apply_processor(sub_builder, s)
    return list(sub_builder._processors)  # type: ignore[attr-defined]


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
