"""S62 W4 — build.py part of yaml_loader decomp.

Funcs: _build_pipeline, _is_allowed_processor, _build_sub, _apply_processor.

pipeline building (build_pipeline + processor gating + sub-pipeline + apply processor).
"""

from __future__ import annotations

import inspect
from typing import Any, Final

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline, ResponseBinding
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.yaml_loader.control_flow import _materialize_control_flow_params

# Sentinel for "not set" to distinguish from None
_MISSING = object()

# Аннотации builder'а, по которым определяется «вложенный список
# процессоров». Модули builder'а используют ``from __future__ import
# annotations`` → аннотации приходят строками, поэтому матчим по тексту.
_NESTED_MAP_ANNOTATION: Final[str] = "dict[str, list[BaseProcessor]]"
_NESTED_LIST_OF_LISTS_ANNOTATION: Final[str] = "list[list[BaseProcessor]]"
_NESTED_LIST_ANNOTATION: Final[str] = "list[BaseProcessor]"

#: Control-flow-шаги с bespoke-структурой: их вложенные списки
#: материализирует :func:`_materialize_control_flow_params`
#: (``choice.when`` — список ``ChoiceBranch``, ``saga.steps`` — список
#: ``SagaStep``), поэтому общий разбор аннотаций к ним не применяется.
_BESPOKE_CONTROL_FLOW: Final[frozenset[str]] = frozenset(
    {"do_try", "retry", "parallel", "saga", "choice"}
)


def _iter_steps(specs: list[Any]) -> list[Any]:
    """Отбрасывает пустые (comment-only) элементы списка шагов.

    Элемент YAML-списка, состоящий только из комментариев, разбирается в
    ``None``. Такая запись семантически пуста, но до 2026-10-06 доходила до
    :func:`_apply_processor` и роняла загрузку с
    ``ValueError: Invalid processor spec: None``.

    На живых данных это ломало ``routes/hello_route/main.dsl.yaml`` (3 таких
    элемента) и ``routes/test_route_w1/main.dsl.yaml`` (2). Отбрасывание
    пустых узлов ничего не ослабляет: настоящие шаги (dict/str) по-прежнему
    проходят ту же валидацию.
    """
    return [spec for spec in specs if spec is not None]


def _build_pipeline(
    spec: dict[str, Any], *, default_route_id: str | None = None
) -> Pipeline:
    """Строит Pipeline из распарсенного spec.

    Args:
        spec: распарсенный YAML.
        default_route_id: ``route_id``, используемый, если в spec его нет.
            Нужен V11-пути ``RouteLoader``: имя маршрута уже объявлено в
            ``route.toml`` (``[route] name``), и требовать его дублирование
            в pipeline-YAML — источник рассинхронизации. Для автономной
            загрузки YAML (без манифеста) параметр не передаётся, и
            ``route_id`` остаётся обязательным.
    """
    route_id = spec.get("route_id") or default_route_id
    if not route_id:
        raise ValueError("Missing required field: route_id")

    source = spec.get("source", f"yaml:{route_id}")
    # Dual-mode (CLAUDE.md, «DSL Dual-Mode Principle»): YAML-форма объявляет
    # транспорт блоком ``from:``, Python-форма — аргументом ``source=``.
    # До 2026-10-06 ключ ``from:`` не читался НИГДЕ, то есть блок транспорта
    # молча игнорировался, а маршрут получал source по умолчанию
    # ``yaml:{route_id}`` — без привязки к HTTP-пути.
    #
    # Здесь ``from:`` принимается как алиас ``source``. Явный ``source:``
    # имеет приоритет: если объявлены оба, ``from:`` — лишний, и молча
    # выбирать одно было бы молчанием, поэтому источник фиксируется явно.
    if "from" in spec:
        if "source" in spec:
            raise ValueError(
                "YAML declares both 'from' and 'source'; they are aliases for "
                "the same transport binding — keep exactly one"
            )
        source = spec["from"]
    description = spec.get("description")

    builder = RouteBuilder.from_(route_id, source=source, description=description)

    # Support both `processors` (original) and `steps` (V11 route format)
    processors_spec = spec.get("processors") or spec.get("steps", [])
    if not isinstance(processors_spec, list):
        raise ValueError("'processors' must be a list")

    for proc_spec in _iter_steps(processors_spec):
        _apply_processor(builder, proc_spec)

    # ADR-0349: опциональный response-binding (sibling ``from:`` / ``steps:``).
    # Формат YAML::
    #
    #     to:
    #       body:
    #         status: ok
    #         user_id: "${body.user_id}"
    #       headers:
    #         X-Frame-Options: DENY
    #
    # Внутри строк в ``body`` ``${expr}`` резолвится ``_resolve``-helper'ом
    # (неймспейсы body./properties./result./header.). Все остальные значения
    # проходят как литералы — это позволяет смешивать ссылки и значения.
    to_spec = spec.get("to")
    if to_spec is not None:
        if not isinstance(to_spec, dict):
            raise ValueError("'to' must be a mapping with 'body' and/or 'headers'")
        if "body" not in to_spec and "headers" not in to_spec:
            raise ValueError("'to' must declare at least one of 'body' or 'headers'")
        body = to_spec.get("body", {})
        headers = to_spec.get("headers", {})
        if not isinstance(body, dict):
            raise ValueError("'to.body' must be a mapping")
        if not isinstance(headers, dict):
            raise ValueError("'to.headers' must be a mapping")
        builder.to_response(ResponseBinding(body=body, headers=dict(headers)))

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
    for s in _iter_steps(specs):
        _apply_processor(sub_builder, s)
    return list(sub_builder._processors)  # type: ignore[attr-defined]


def _is_spec_list(value: Any) -> bool:
    """Похоже ли значение на список YAML-спеков процессоров.

    Спец — это ``str`` (шаг без параметров) либо ``dict`` с одним ключом
    (``{name: params}``). Уже материализованные ``BaseProcessor`` сюда
    не попадают — значит повторная материализация не выполняется.
    """
    if not isinstance(value, list):
        return False
    return all(
        isinstance(item, str)
        or (isinstance(item, dict) and len(item) == 1)
        for item in value
    )


def _nested_param_kinds(builder: RouteBuilder, proc_name: str) -> dict[str, str]:
    """Определить, какие params шага содержат вложенные процессоры.

    Источник истины — сигнатура метода :class:`RouteBuilder`: параметр с
    аннотацией ``list[BaseProcessor]`` / ``dict[str, list[BaseProcessor]]``
    / ``list[list[BaseProcessor]]`` принимает готовые процессоры, а не
    YAML-спеки. Такой разбор покрывает все шаги с вложенными списками
    (``for_each``, ``fork_join``, ``switch``, ``timeout``, ``fallback``,
    ``circuit_breaker``, ``multicast`` …) без ручного перечисления.

    Args:
        builder: Экземпляр builder'а (для resolve метода через MRO).
        proc_name: Имя YAML-шага.

    Returns:
        Mapping ``param → kind`` (``list`` / ``list_of_lists`` / ``map``).
        Пустой mapping, если вложенных параметров нет.

    """
    method = getattr(type(builder), proc_name, None)
    if method is None:
        return {}
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):  # pragma: no cover — C-фичи без сигнатуры
        return {}
    kinds: dict[str, str] = {}
    for name, param in signature.parameters.items():
        annotation = param.annotation
        if not isinstance(annotation, str):
            annotation = str(annotation)
        if _NESTED_MAP_ANNOTATION in annotation:
            kinds[name] = "map"
        elif _NESTED_LIST_OF_LISTS_ANNOTATION in annotation:
            kinds[name] = "list_of_lists"
        elif _NESTED_LIST_ANNOTATION in annotation:
            kinds[name] = "list"
    return kinds


def _materialize_nested_params(
    builder: RouteBuilder, proc_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Материализовать вложенные списки процессоров по конвенции builder'а.

    Шаги control-flow (``do_try`` / ``retry`` / ``parallel`` / ``saga`` /
    ``choice``) обрабатываются отдельно (у ``saga``/``choice`` собственная
    структура). Остальные шаги с вложенными списками
    (``for_each`` / ``fork_join`` / ``switch`` / ``timeout`` / …)
    материализуются здесь — иначе в runtime оставался raw-dict и шаг падал
    с ``'dict' object has no attribute 'process'``.

    Args:
        builder: Родительский RouteBuilder.
        proc_name: Имя YAML-шага.
        params: Сырые kwargs из YAML.

    Returns:
        Новый dict kwargs с подставленными ``BaseProcessor``.

    """
    materialized = _materialize_control_flow_params(builder, proc_name, params)
    if proc_name in _BESPOKE_CONTROL_FLOW:
        # Структура уже приведена к нужным типам (ChoiceBranch / SagaStep /
        # list[BaseProcessor]) — общий разбор аннотаций здесь только мешает.
        return materialized
    for name, kind in _nested_param_kinds(builder, proc_name).items():
        value = materialized.get(name)
        if value is None:
            continue
        if kind == "map":
            if not isinstance(value, dict):
                raise ValueError(
                    f"'{proc_name}.{name}' must be a mapping "
                    f"name → list of processors, got {type(value).__name__}"
                )
            materialized[name] = {
                key: _build_sub(builder, specs) if _is_spec_list(specs) else specs
                for key, specs in value.items()
            }
        elif kind == "list_of_lists":
            if not isinstance(value, list):
                raise ValueError(
                    f"'{proc_name}.{name}' must be a list of processor lists, "
                    f"got {type(value).__name__}"
                )
            materialized[name] = [
                _build_sub(builder, specs) if _is_spec_list(specs) else specs
                for specs in value
            ]
        elif kind == "list":
            if not isinstance(value, list):
                raise ValueError(
                    f"'{proc_name}.{name}' must be a list of processors, "
                    f"got {type(value).__name__}"
                )
            if _is_spec_list(value):
                materialized[name] = _build_sub(builder, value)
            elif not all(isinstance(item, BaseProcessor) for item in value):
                raise ValueError(
                    f"'{proc_name}.{name}' must be a list of processors "
                    f"(step specs or built processors)"
                )
    return materialized


def _validate_jmespath_expression(proc_name: str, expression: object) -> None:
    """Fail-fast на невалидном JMESPath-выражении.

    ``for_each`` с опечаткой в ``items_path`` раньше молча отрабатывал
    вхолостую (0 итераций, успешный статус) — ошибка всплывала только
    как «тихий» неверный результат. Теперь load-time ошибка.

    Args:
        proc_name: Имя YAML-шага (для сообщения).
        expression: Значение параметра с JMESPath-выражением.

    Raises:
        ValueError: Выражение пустое или не разбирается jmespath.

    """
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError(
            f"'{proc_name}.items_path' requires a non-empty JMESPath expression"
        )
    try:
        import jmespath
    except ImportError:  # pragma: no cover — jmespath — обязательная зависимость
        return
    try:
        jmespath.compile(expression)
    except jmespath.exceptions.ParseError as exc:
        raise ValueError(
            f"Invalid JMESPath expression for '{proc_name}.items_path' "
            f"({expression!r}): {exc}"
        ) from exc


def _apply_processor(builder: RouteBuilder, spec: Any) -> None:
    """Применяет один процессор к builder.

    Поддерживаются 2 формата:
    - {name: {params}} — dict с одним ключом
    - "name" — строка без параметров

    Для control-flow процессоров (``do_try``, ``retry``, ``parallel``,
    ``saga``, ``choice``) и всех прочих шагов с вложенными списками
    (``for_each``, ``fork_join``, ``switch``, ``timeout``, …)
    поддерживается nested-формат: вложенные списки процессоров
    рекурсивно собираются перед передачей в builder.
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
        params = _materialize_nested_params(builder, proc_name, params)
        if proc_name == "for_each":
            _validate_jmespath_expression(proc_name, params.get("items_path"))
        method(**params)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid params for '{proc_name}': {exc}") from exc
