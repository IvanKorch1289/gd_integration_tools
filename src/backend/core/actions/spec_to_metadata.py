"""Адаптер ``ActionSpec`` → :class:`ActionMetadata` (Wave 14.1.B + post-sprint-2).

``ActionSpec`` определён в ``src/entrypoints/api/generator/specs.py`` —
прямой импорт из ``core/`` запрещён политикой слоёв
(``tools/check_layers.py``: ``core`` → только stdlib и pip-пакеты).

Решение: адаптер принимает спецификацию как ``Any`` и читает поля
через :func:`getattr` с дефолтами (duck-typing). Это сохраняет
изоляцию слоя ``core/`` и одновременно позволяет вызывающей
стороне (``entrypoints/api/generator/actions.py``,
``ActionRouterBuilder``) без приведений типов передать
``ActionSpec`` сюда.

Соответствие полей::

    ActionSpec.name           → ActionMetadata.action
    ActionSpec.description    → ActionMetadata.description
    ActionSpec.body_model     → ActionMetadata.input_model
        ?? path_model         (если body_model отсутствует)
        ?? query_model        (если path_model отсутствует)
    ActionSpec.response_model → ActionMetadata.output_model
    ActionSpec.tags           → ActionMetadata.tags

    Wave 14.1 post-sprint-2 расширение:
    ActionSpec.transports     → ActionMetadata.transports (default ("http",))
    ActionSpec.side_effect    → ActionMetadata.side_effect
        (если None — выводится из HTTP method)
    ActionSpec.idempotent     → ActionMetadata.idempotent
        (если None — выводится из HTTP method)
    ActionSpec.permissions    → ActionMetadata.permissions
    ActionSpec.rate_limit     → ActionMetadata.rate_limit
    ActionSpec.timeout_ms     → ActionMetadata.timeout_ms
    ActionSpec.deprecated     → ActionMetadata.deprecated
    ActionSpec.since_version  → ActionMetadata.since_version

Поле ``ActionSpec.use_dispatcher`` относится к control-plane
(per-action override env-флага) и в :class:`ActionMetadata` не
переносится — оно читается отдельно ``actions.py``.
"""

from __future__ import annotations

from typing import Any

from src.core.interfaces.action_dispatcher import ActionMetadata

__all__ = ("action_spec_to_metadata",)


# REST-конвенция: GET — чтение, всё остальное — запись.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# REST-конвенция: GET, PUT, DELETE, HEAD, OPTIONS — идемпотентны;
# POST и PATCH — нет.
_IDEMPOTENT_METHODS = frozenset({"GET", "PUT", "DELETE", "HEAD", "OPTIONS"})


def _coerce_tuple(value: Any) -> tuple[str, ...]:
    """Безопасно превратить ``Sequence[str]`` или ``None`` в кортеж.

    ``ActionSpec.tags`` декларирован как ``Sequence[str]``, но
    в core/ мы не хотим зависеть от конкретного типа.
    """
    if value is None:
        return ()
    return tuple(value)


def _infer_side_effect(method: str | None) -> str:
    """Вывести ``side_effect`` из HTTP-метода по REST-конвенции.

    Если метод неизвестен или None — возвращается ``"none"`` (явная
    декларация в ``ActionSpec.side_effect`` всегда переопределяет).
    """
    if method is None:
        return "none"
    if method.upper() in _READ_METHODS:
        return "read"
    return "write"


def _infer_idempotent(method: str | None) -> bool:
    """Вывести ``idempotent`` из HTTP-метода по REST-конвенции."""
    if method is None:
        return False
    return method.upper() in _IDEMPOTENT_METHODS


def action_spec_to_metadata(spec: Any) -> ActionMetadata:
    """Сконвертировать ``ActionSpec`` в :class:`ActionMetadata`.

    Args:
        spec: Декларативное описание action (``ActionSpec`` из
            ``src/entrypoints/api/generator/specs.py``). Принимается
            как ``Any`` — см. docstring модуля о соблюдении слоёв.

    Returns:
        :class:`ActionMetadata` с заполненными полями. Если в
        ``spec.side_effect`` или ``spec.idempotent`` стоит ``None``,
        значение выводится из ``spec.method`` по REST-конвенции.

    Raises:
        AttributeError: Если у ``spec`` нет поля ``name`` —
            это обязательный признак ``ActionSpec``.
    """
    # action_id (если задан) — приоритетнее name. Это позволяет HTTP-роуту
    # с собственным OpenAPI-именем делегировать в handler, зарегистрированный
    # под другим именем в action_handler_registry.
    action_name: str = getattr(spec, "action_id", None) or spec.name

    # input_model: body_model > path_model > query_model.
    input_model = (
        getattr(spec, "body_model", None)
        or getattr(spec, "path_model", None)
        or getattr(spec, "query_model", None)
    )
    output_model = getattr(spec, "response_model", None)

    description = getattr(spec, "description", None) or ""
    tags = _coerce_tuple(getattr(spec, "tags", None))

    # transports: явная декларация ИЛИ дефолт ``("http",)``.
    transports_raw = getattr(spec, "transports", None)
    transports = _coerce_tuple(transports_raw) if transports_raw else ("http",)

    method = getattr(spec, "method", None)

    # side_effect / idempotent: ``None`` → вывести из HTTP method.
    side_effect = getattr(spec, "side_effect", None)
    if side_effect is None:
        side_effect = _infer_side_effect(method)

    idempotent = getattr(spec, "idempotent", None)
    if idempotent is None:
        idempotent = _infer_idempotent(method)

    permissions = _coerce_tuple(getattr(spec, "permissions", None))
    rate_limit = getattr(spec, "rate_limit", None)
    timeout_ms = getattr(spec, "timeout_ms", None)
    deprecated = bool(getattr(spec, "deprecated", False))
    since_version = getattr(spec, "since_version", None)

    return ActionMetadata(
        action=action_name,
        description=description,
        input_model=input_model,
        output_model=output_model,
        transports=transports,
        side_effect=side_effect,
        idempotent=idempotent,
        permissions=permissions,
        rate_limit=rate_limit,
        timeout_ms=timeout_ms,
        deprecated=deprecated,
        since_version=since_version,
        tags=tags,
    )
