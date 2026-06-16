"""Structural protocol for FormatConvertProcessor mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты, чтобы mypy видел
``self.secret``, ``self.algorithm``, ``self.claims``, ``self.schema``.
"""

from __future__ import annotations

from typing import Any, Protocol


class _FormatConvertProtocol(Protocol):
    """Общий контракт для FormatConvertProcessor mixins."""

    secret: str | None
    algorithm: str | None
    claims: Any
    schema: Any
