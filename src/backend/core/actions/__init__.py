"""Реализация Gateway-функциональности action (Wave 14.1.B).

Содержит адаптеры и хелперы вокруг :class:`ActionMetadata`,
определённого в ``src/core/interfaces/action_dispatcher.py``.

Подпакет осознанно не импортирует код из ``entrypoints/``,
``services/`` или ``infrastructure/`` — все адаптеры используют
duck-typing (``getattr`` с дефолтами), чтобы оставаться внутри
слоя ``core/``.
"""

from src.backend.core.actions.spec_to_metadata import action_spec_to_metadata

__all__ = ("action_spec_to_metadata",)
