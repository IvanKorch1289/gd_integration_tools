from __future__ import annotations

from dataclasses import dataclass, field

from src.backend.core.security.capabilities.matchers import ScopeMatcher

"""S62 W2 — models.py part of vocabulary decomp.

CapabilityDef data class.
"""


@dataclass
class CapabilityDef:
    """Метаданные одной зарегистрированной capability.

    Attributes:
        name: Полное имя ``<resource>.<verb>``.
        matcher: Strategy для резолвинга scope.
        scope_required: Если ``True`` — capability с ``scope=None``
            считается ошибкой манифеста.
        description: Человекочитаемая аннотация (для admin-UI и
            DSL-Linter).
        public: Если ``True`` — capability доступна route'у даже
            без явной декларации в плагине (например, общий
            ``net.outbound`` к публичным API).
    """

    name: str
    matcher: ScopeMatcher
    scope_required: bool = True
    description: str = ""
    public: bool = False
    """Часть «публичного капабилити-набора ядра» (см. ADR-044)."""

    aliases: tuple[str, ...] = field(default_factory=tuple)
    """Опц. альтернативные имена (legacy)."""
