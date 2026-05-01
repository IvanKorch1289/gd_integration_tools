"""Адаптер Pydantic → Strawberry GraphQL types (Wave 1.4, Roadmap V10).

Strawberry поддерживает декоратор
:func:`strawberry.experimental.pydantic.type` для маппинга Pydantic-моделей
на GraphQL types. Этот модуль:

* кеширует результаты — одна Pydantic-модель = один Strawberry type;
* проставляет ``all_fields=True`` для полного покрытия модели;
* обрабатывает Optional/list/nested через нативные средства Strawberry
  (которые корректно протаскивают аннотации Pydantic);
* при не-поддерживаемых аннотациях (Generic, Union сложного вида)
  возвращает ``strawberry.scalars.JSON`` как fallback + warning.

Layer policy: модуль живёт в ``src/core/actions/`` и импортирует только
Pydantic + Strawberry (обе — допустимые pip-зависимости в core).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

__all__ = (
    "StrawberryTypeRegistry",
    "pydantic_to_strawberry",
    "global_registry",
)


class StrawberryTypeRegistry:
    """Реестр сконвертированных :class:`pydantic.BaseModel` → Strawberry type.

    Идемпотентен по имени модели: повторный вызов на одной и той же
    модели возвращает тот же strawberry-type (Strawberry не любит
    переопределение типов с одинаковым ``__strawberry_definition__.name``).
    """

    def __init__(self) -> None:
        self._cache: dict[str, type] = {}
        self._fallbacks: list[str] = []

    def get_or_create(self, model: type[BaseModel]) -> type:
        """Вернуть Strawberry-type для Pydantic-модели.

        Args:
            model: Pydantic-модель (subclass :class:`BaseModel`).

        Returns:
            Класс Strawberry-type (динамически созданный).
        """
        cache_key = f"{model.__module__}.{model.__name__}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            strawberry_type = self._convert(model)
        except Exception as exc:  # noqa: BLE001 — Strawberry строг к типам
            self._fallbacks.append(f"{model.__name__}: {exc}")
            logger.warning(
                "strawberry-pydantic fallback для %s: %s — используем JSON-stub",
                model.__name__,
                exc,
            )
            strawberry_type = self._fallback_type(model)

        self._cache[cache_key] = strawberry_type
        return strawberry_type

    @property
    def fallbacks(self) -> tuple[str, ...]:
        """Имена моделей, для которых был использован JSON-fallback."""
        return tuple(self._fallbacks)

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    def _convert(self, model: type[BaseModel]) -> type:
        """Вернуть Strawberry-type через ``strawberry.experimental.pydantic.type``.

        Внутри Strawberry сам разбирает аннотации и резолвит nested
        BaseModel через рекурсивное обращение к декоратору. Чтобы это
        работало, мы предварительно регистрируем nested-модели.
        """
        import strawberry
        from strawberry.experimental.pydantic import type as strawberry_pydantic_type

        # Предварительно регистрируем nested-модели (рекурсивный обход).
        self._prewarm_nested(model)

        # Динамически создаём пустой класс — Strawberry заполнит поля.
        attrs: dict[str, Any] = {
            "__doc__": (model.__doc__ or "").strip() or None,
        }
        new_type_name = f"{model.__name__}Type"
        decorator = strawberry_pydantic_type(model=model, all_fields=True)
        new_cls = type(new_type_name, (), attrs)
        decorated = decorator(new_cls)
        # Strawberry мутирует класс (добавляет ``_type_definition``); метаданных
        # достаточно для использования в Query/Mutation.
        _ = strawberry  # silence unused
        return decorated

    def _prewarm_nested(self, model: type[BaseModel]) -> None:
        """Зарегистрировать вложенные :class:`BaseModel` до основной модели.

        Strawberry резолвит аннотации лениво, но при создании Schema
        требует все типы доступными — проще зарегистрировать заранее.
        """
        from typing import get_args

        for info in model.model_fields.values():
            for nested in self._iter_nested_models(info.annotation):
                if nested is model:
                    continue
                self.get_or_create(nested)

            # ItemsView для list[Model] / Optional[Model] и т.п.
            for arg in get_args(info.annotation):
                for nested in self._iter_nested_models(arg):
                    if nested is model:
                        continue
                    self.get_or_create(nested)

    @staticmethod
    def _iter_nested_models(annotation: Any) -> tuple[type[BaseModel], ...]:
        """Извлечь :class:`BaseModel` из аннотации (на верхнем уровне)."""
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return (annotation,)
        return ()

    @staticmethod
    def _fallback_type(model: type[BaseModel]) -> type:
        """Вернуть JSON-fallback type, если конвертация не удалась.

        Используется ``strawberry.scalars.JSON`` через тонкую обёртку, чтобы
        вернуть полноценный type (требование Strawberry — не scalar).
        """
        import strawberry
        from strawberry.scalars import JSON

        @strawberry.type(name=f"{model.__name__}Json", description=(model.__doc__ or ""))
        class _JsonStub:
            """JSON-fallback (полная модель не сконвертирована)."""

            data: JSON | None = None

        return _JsonStub


# Глобальный singleton — упрощает регистрацию из нескольких мест.
global_registry = StrawberryTypeRegistry()


def pydantic_to_strawberry(model: type[BaseModel]) -> type:
    """Сахар над :meth:`StrawberryTypeRegistry.get_or_create`.

    Args:
        model: Pydantic-модель.

    Returns:
        Strawberry-type.
    """
    return global_registry.get_or_create(model)
