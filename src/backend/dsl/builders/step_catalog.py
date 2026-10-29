"""Каталог YAML-шагов DSL — единый источник истины (ADR-0397, кластер D).

Модуль закрывает дефект 6: списки шагов / capability / схем держались
вручную (``_PROCESSOR_CAPABILITIES`` в линтере, ``STEP_COMPLETIONS`` в
``tools/dsl_lsp/schema_completion.py``) и разъезжались с API:

* 9 из 11 ключей capability-карты не соответствовали ни одному шагу;
* completion предлагал 55 шагов при 441 публичных методах
  ``RouteBuilder``;
* JSON-Schema генерировались только для зарегистрированных в
  ``@processor`` процессоров.

Каталог собирается из трёх источников:

1. **Сигнатуры ``RouteBuilder``** — канонический список допустимых
   YAML-шагов и их параметров (тот же whitelist, что и в
   ``dsl/yaml_loader/build.py::_is_allowed_processor``);
2. **AST тела метода** (``self._add_lazy(...)`` / ``self._add(...)``) —
   связь «шаг → класс процессора»;
3. **Реестр ``@processor``** — ``required_capability`` и JSON-Schema
   процессора (ADR-0058).

Публичный API:

* :func:`builder_step_names` — все публичные методы ``RouteBuilder``;
* :func:`step_capability_map` — ``шаг → требуемая capability``;
* :func:`step_schema_map` — ``шаг → JSON-Schema параметров``;
* :func:`catalog_coverage` — счётчики покрытия (для мягкого CI-гейта).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
import textwrap
from functools import lru_cache
from typing import Any, Final

__all__ = (
    "builder_step_names",
    "catalog_coverage",
    "step_capability_map",
    "step_schema_map",
)

#: Capability, которую шаг требует на уровне ФАСАДА, а не процессора.
#: Единственный такой случай — исходящий HTTP: ``HttpCallProcessor`` не
#: объявляет ``required_capability``, а проверку ``net.outbound`` делает
#: ``OutboundHttpClient`` (``core/net/outbound_http.py``).
FACADE_CAPABILITIES: Final[dict[str, str]] = {"http_call": "net.outbound"}

#: Грубое отображение python-аннотации → JSON-Schema type.
_JSON_TYPES: Final[dict[str, str]] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}


def _literal_str(node: ast.AST) -> str | None:
    """Строковый literal из AST-узла (или ``None``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


@lru_cache(maxsize=1)
def builder_step_names() -> tuple[str, ...]:
    """Публичные методы ``RouteBuilder`` — допустимые имена YAML-шагов.

    Тот же whitelist, что использует YAML-загрузчик
    (``dsl/yaml_loader/build.py::_is_allowed_processor``).

    Returns:
        Отсортированный кортеж имён шагов.

    """
    from src.backend.dsl.builder import RouteBuilder

    names: set[str] = set()
    for cls in RouteBuilder.__mro__:
        if cls in (object, type):
            continue
        for name, attr in vars(cls).items():
            if name.startswith("_"):
                continue
            if callable(attr) or isinstance(
                attr, (property, classmethod, staticmethod)
            ):
                names.add(name)
    return tuple(sorted(names))


def _resolve_class_expr(
    node: ast.AST, namespace: dict[str, Any]
) -> type[Any] | None:
    """Найти класс процессора в AST-выражении по namespace'у модуля."""
    if isinstance(node, ast.Call):
        return _resolve_class_expr(node.func, namespace)
    if isinstance(node, ast.Name):
        candidate = namespace.get(node.id)
        return candidate if isinstance(candidate, type) else None
    if isinstance(node, ast.Attribute):
        candidate = namespace.get(node.attr)
        return candidate if isinstance(candidate, type) else None
    return None


def _processor_class_in_return(
    node: ast.AST, namespace: dict[str, Any]
) -> type[Any] | None:
    """Класс процессора из ``return self._add_lazy(...)`` / ``_add(...)``.

    Builder'ы создают процессоры единообразно: ``self._add_lazy(module,
    "ClassName", **kwargs)`` либо ``self._add(SomeProcessor(...))``.
    Разбор AST даёт связь «YAML-шаг → класс процессора» без ручного
    перечисления шагов.

    Args:
        node: AST-узел (обычно ``ast.Return``).
        namespace: ``globals()`` модуля, где определён метод.

    Returns:
        Класс процессора либо ``None``.

    """
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(
            child.func, ast.Attribute
        ):
            continue
        if child.func.attr == "_add_lazy" and len(child.args) >= 2:
            module_path = _literal_str(child.args[0])
            class_name = _literal_str(child.args[1])
            if not module_path or not class_name:
                continue
            try:
                loaded = importlib.import_module(module_path)
            except ImportError:
                continue
            candidate = getattr(loaded, class_name, None)
            if isinstance(candidate, type):
                return candidate
        elif child.func.attr == "_add" and child.args:
            candidate = _resolve_class_expr(child.args[0], namespace)
            if candidate is not None:
                return candidate
    return None


def _processor_class_for_step(step: str) -> type[Any] | None:
    """Класс процессора, создаваемый builder'ом для YAML-шага ``step``.

    Args:
        step: Имя YAML-шага (метод ``RouteBuilder``).

    Returns:
        Класс процессора либо ``None``, если шаг не создаёт процессор
        (или его не удалось разобрать).

    """
    from src.backend.dsl.builder import RouteBuilder

    method = getattr(RouteBuilder, step, None)
    if method is None or not callable(method):
        return None
    try:
        source = textwrap.dedent(inspect.getsource(method))
    except (OSError, TypeError):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — исходники builder'а валидны
        return None
    module = sys.modules.get(getattr(method, "__module__", ""), None)
    namespace = vars(module) if module is not None else {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            candidate = _processor_class_in_return(node.value, namespace)
            if candidate is not None:
                return candidate
    return None


@lru_cache(maxsize=1)
def step_capability_map() -> dict[str, str]:
    """Карта «YAML-шаг → требуемая capability».

    ADR-0397: источник истины — ``required_capability`` процессора.
    Карта собирается из двух источников:

    1. **Класс процессора**, создаваемого методом ``RouteBuilder``
       (AST-разбор ``self._add_lazy(...)`` / ``self._add(...)``) —
       покрывает и незарегистрированные в реестре шаги
       (``db_query_external``, ``rpa_*`` и т.д.);
    2. **Реестр ``@processor``** — для процессоров, чей шаг не удалось
       сопоставить с методом builder'а.

    Returns:
        Mapping ``step → capability name``.

    """
    mapping: dict[str, str] = {}
    steps = builder_step_names()
    for step in steps:
        processor_cls = _processor_class_for_step(step)
        if processor_cls is None:
            continue
        capability = getattr(processor_cls, "required_capability", None)
        if isinstance(capability, str) and capability:
            mapping[step] = capability

    try:
        import src.backend.dsl.engine.processors  # noqa: F401  — side-effect
        from src.backend.dsl.registry.processor import get_processor_registry
    except ImportError:  # pragma: no cover — optional deps
        pass
    else:
        for spec in get_processor_registry().list_specs():
            capability = getattr(spec.cls, "required_capability", None)
            if not isinstance(capability, str) or not capability:
                continue
            # Реестр содержит и процессоры без метода builder'а
            # (``memory_recall`` и др.) — в YAML они не адресуемы.
            if spec.name not in steps:
                continue
            mapping.setdefault(spec.name, capability)

    for step, capability in FACADE_CAPABILITIES.items():
        mapping.setdefault(step, capability)
    return mapping


def _annotation_type(annotation: object) -> str | None:
    """Грубый JSON-тип по текстовой аннотации параметра."""
    text = annotation if isinstance(annotation, str) else str(annotation)
    for prefix, json_type in _JSON_TYPES.items():
        if text.startswith(prefix) or f"{prefix}[" in text or f"{prefix} |" in text:
            return json_type
    return None


def _signature_schema(step: str) -> dict[str, Any]:
    """Каркас JSON-Schema параметров шага по сигнатуре builder'а.

    Используется для шагов, чей процессор не зарегистрирован в
    ``@processor`` (у них нет готовой схемы в реестре).

    Args:
        step: Имя YAML-шага.

    Returns:
        JSON-Schema (draft-07) объекта параметров.

    """
    from src.backend.dsl.builder import RouteBuilder

    method = getattr(RouteBuilder, step, None)
    properties: dict[str, Any] = {}
    required: list[str] = []
    if method is not None and callable(method):
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):  # pragma: no cover
            signature = None
        if signature is not None:
            for name, param in signature.parameters.items():
                if name in ("self", "cls") or param.kind in (
                    param.VAR_POSITIONAL,
                    param.VAR_KEYWORD,
                ):
                    continue
                schema: dict[str, Any] = {"title": name}
                json_type = _annotation_type(param.annotation)
                if json_type:
                    schema["type"] = json_type
                properties[name] = schema
                if param.default is param.empty:
                    required.append(name)
    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{step} step",
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


@lru_cache(maxsize=1)
def step_schema_map() -> dict[str, dict[str, Any]]:
    """JSON-Schema параметров каждого YAML-шага.

    Схема берётся из реестра ``@processor`` (ADR-0058), если процессор
    зарегистрирован; иначе строится каркас по сигнатуре метода
    ``RouteBuilder``.

    Returns:
        Mapping ``step → JSON-Schema``.

    """
    schemas: dict[str, dict[str, Any]] = {}
    try:
        import src.backend.dsl.engine.processors  # noqa: F401  — side-effect
        from src.backend.dsl.registry.processor import get_processor_registry
    except ImportError:  # pragma: no cover — optional deps
        registry = None
    else:
        registry = get_processor_registry()
    if registry is not None:
        for fqn, schema in registry.export_schemas().items():
            short = fqn.split(":", 1)[-1]
            schemas[short] = schema
    for step in builder_step_names():
        schemas.setdefault(step, _signature_schema(step))
    return schemas


def catalog_coverage() -> dict[str, int]:
    """Счётчики покрытия каталога (для мягкого CI-гейта).

    Returns:
        Mapping ``метрика → значение``: ``steps`` (всего шагов),
        ``with_capability`` (шагов с известной capability),
        ``with_registry_schema`` (шагов со схемой из реестра).

    """
    schemas = step_schema_map()
    registry_schema_count = 0
    try:
        import src.backend.dsl.engine.processors  # noqa: F401  — side-effect
        from src.backend.dsl.registry.processor import get_processor_registry
    except ImportError:  # pragma: no cover — optional deps
        registry = None
    else:
        registry = get_processor_registry()
    if registry is not None:
        registry_names = {spec.name for spec in registry.list_specs()}
        registry_schema_count = sum(1 for name in registry_names if name in schemas)
    return {
        "steps": len(builder_step_names()),
        "with_capability": len(step_capability_map()),
        "with_registry_schema": registry_schema_count,
    }
