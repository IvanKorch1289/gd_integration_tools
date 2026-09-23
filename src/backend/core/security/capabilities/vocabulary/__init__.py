"""Capability vocabulary package (S62 W2 decomp from vocabulary.py 509 LOC).

2 classes + 1 BIG function → 3 files:
- ``models.py``: CapabilityDef (data class)
- ``vocabulary.py``: CapabilityVocabulary (7 methods)
- ``defaults.py``: build_default_vocabulary (388 LOC, BIG function)

Backward-compat: ``from src.backend.core.security.capabilities.vocabulary import build_default_vocabulary`` works.
"""

from __future__ import annotations

from src.backend.core.security.capabilities.vocabulary.defaults import (
    build_default_vocabulary,  # S62 W2: re-export
)
from src.backend.core.security.capabilities.vocabulary.models import (
    CapabilityDef,  # S62 W2: re-export
)
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,  # S62 W2: re-export
)

__all__ = ("CapabilityDef", "CapabilityVocabulary", "build_default_vocabulary")
