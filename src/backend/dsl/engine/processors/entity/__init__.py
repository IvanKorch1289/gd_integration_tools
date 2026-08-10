"""S175: entity subpackage — split 370 LOC god-file.

Разбивает :file:`entity.py` (370 LOC, 6 классов) на subpackage.
5 Entity операций + 1 base class.

Modules:
- :mod:`base` — :class:`_BaseEntityProcessor` (internal)
- :mod:`create` — :class:`EntityCreateProcessor`
- :mod:`get` — :class:`EntityGetProcessor`
- :mod:`update` — :class:`EntityUpdateProcessor`
- :mod:`delete` — :class:`EntityDeleteProcessor`
- :mod:`list` — :class:`EntityListProcessor`

Ponytail: Phase 1 = re-export из legacy godfile (zero-risk).
Phase 2 = физическое разделение в thematic files (S175.5+).

Backward-compat:
    ``from src.backend.dsl.engine.processors.entity import X``
    продолжает работать через этот ``__init__.py``.
"""
from __future__ import annotations as annotations

# Phase 1: re-export из legacy godfile (S175 — этот sprint)
from src.backend.dsl.engine.processors.entity._legacy import (
    _BaseEntityProcessor as _BaseEntityProcessor,
)

# S175: _resolve helper restored (parallel WIP forgot to migrate from
# original entity.py). _resolve используется audit.py и другими
# callers для namespace-path resolution.
from src.backend.dsl.engine.processors.entity._resolve import (
    _resolve as _resolve,
)
from src.backend.dsl.engine.processors.entity.create import (
    EntityCreateProcessor as EntityCreateProcessor,
)
from src.backend.dsl.engine.processors.entity.delete import (
    EntityDeleteProcessor as EntityDeleteProcessor,
)
from src.backend.dsl.engine.processors.entity.get import (
    EntityGetProcessor as EntityGetProcessor,
)
from src.backend.dsl.engine.processors.entity.list import (
    EntityListProcessor as EntityListProcessor,
)
from src.backend.dsl.engine.processors.entity.update import (
    EntityUpdateProcessor as EntityUpdateProcessor,
)

__all__ = (
    "EntityCreateProcessor",
    "EntityDeleteProcessor",
    "EntityGetProcessor",
    "EntityListProcessor",
    "EntityUpdateProcessor",
    "_resolve",
)
