"""Extension package: domain.

См. ``extensions/core_entities/files/domain/__init__.py`` — общий паттерн.
"""

from __future__ import annotations

from . import models  # noqa: F401 — side-effect: register tables on Base.metadata

__all__ = ("models",)
