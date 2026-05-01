"""Адаптер ``ActionSpec`` → :class:`ActionMetadata` (Wave 14.1.B).

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
    transports                = ("http",)  по умолчанию для ActionSpec

Поля Gateway, не выводимые из ``ActionSpec`` (``side_effect``,
``idempotent``, ``permissions``, ``rate_limit``, ``timeout_ms``,
``deprecated``, ``since_version``, ``error_types``) остаются
дефолтными — их можно дополнять отдельной декларацией поверх
``ActionSpec`` в последующих фазах W14.1.
"""

from __future__ import annotations

from typing import Any

from src.core.interfaces.action_dispatcher import ActionMetadata

__all__ = ("action_spec_to_metadata",)


def _coerce_tuple(value: Any) -> tuple[str, ...]:
    """Безопасно превратить ``Sequence[str]`` или ``None`` в кортеж.

    ``ActionSpec.tags`` декларирован как ``Sequence[str]``, но
    в core/ мы не хотим зависеть от конкретного типа.
    """
    if value is None:
        return ()
    return tuple(value)


def action_spec_to_metadata(spec: Any) -> ActionMetadata:
    """Сконвертировать ``ActionSpec`` в :class:`ActionMetadata`.

    Args:
        spec: Декларативное описание action (``ActionSpec`` из
            ``src/entrypoints/api/generator/specs.py``). Принимается
            как ``Any`` — см. docstring модуля о соблюдении слоёв.

    Returns:
        :class:`ActionMetadata` с заполненными полями
        ``action``, ``description``, ``input_model``,
        ``output_model``, ``tags`` и ``transports=("http",)``.

    Raises:
        AttributeError: Если у ``spec`` нет поля ``name`` —
            это обязательный признак ``ActionSpec``.
    """
    action_name: str = spec.name  # обязательное поле — пусть упадёт явно

    # input_model: body_model > path_model > query_model.
    input_model = (
        getattr(spec, "body_model", None)
        or getattr(spec, "path_model", None)
        or getattr(spec, "query_model", None)
    )
    output_model = getattr(spec, "response_model", None)

    description = getattr(spec, "description", None) or ""
    tags = _coerce_tuple(getattr(spec, "tags", None))

    return ActionMetadata(
        action=action_name,
        description=description,
        input_model=input_model,
        output_model=output_model,
        transports=("http",),
        tags=tags,
    )
