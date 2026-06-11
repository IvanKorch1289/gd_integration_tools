from __future__ import annotations

"""S62 W2 — vocabulary.py part of vocabulary decomp.

CapabilityVocabulary (7 methods).
"""


from src.backend.core.security.capabilities.errors import CapabilityNotFoundError
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.vocabulary.models import (
    CapabilityDef,  # S62 W2: cross-import
)


class CapabilityVocabulary:
    """Открытый registry capability-определений."""

    def __init__(self) -> None:
        self._defs: dict[str, CapabilityDef] = {}

    def register(self, definition: CapabilityDef) -> None:
        """Зарегистрировать capability.

        Raises:
            ValueError: Если capability с таким именем уже есть.
        """
        if definition.name in self._defs:
            raise ValueError(f"Capability already registered: {definition.name!r}")
        self._defs[definition.name] = definition
        for alias in definition.aliases:
            if alias in self._defs:
                raise ValueError(f"Alias {alias!r} conflicts with existing capability")
            self._defs[alias] = definition

    def get(self, name: str) -> CapabilityDef:
        """Найти определение по имени.

        Raises:
            CapabilityNotFoundError: Если имени нет в registry.
        """
        try:
            return self._defs[name]
        except KeyError as exc:
            raise CapabilityNotFoundError(name=name) from exc

    def has(self, name: str) -> bool:
        """Зарегистрирована ли capability."""
        return name in self._defs

    def all(self) -> tuple[CapabilityDef, ...]:
        """Все определения в порядке регистрации (без дубликатов)."""
        seen: set[str] = set()
        result: list[CapabilityDef] = []
        for definition in self._defs.values():
            if id(definition) in seen:
                continue
            seen.add(id(definition))
            result.append(definition)
        return tuple(result)

    def public_capabilities(self) -> tuple[CapabilityDef, ...]:
        """Подмножество ``public=True`` определений."""
        return tuple(d for d in self.all() if d.public)

    def validate_ref(self, ref: CapabilityRef) -> None:
        """Проверить, что ссылка осмысленна.

        - имя зарегистрировано;
        - если ``scope_required`` — scope не None.

        Raises:
            CapabilityNotFoundError: Имя отсутствует в registry.
            ValueError: ``scope_required`` нарушено.
        """
        definition = self.get(ref.name)
        if definition.scope_required and ref.scope is None:
            raise ValueError(
                f"Capability {ref.name!r} requires explicit scope (scope_required=True)"
            )
