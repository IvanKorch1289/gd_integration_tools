"""S175: patterns subpackage — split 372 LOC god-file.

Разбивает :file:`patterns.py` (372 LOC, 6 классов + _SafeDict helper) на subpackage.

Modules:
- :mod:`switch` — :class:`SwitchProcessor`
- :mod:`merge` — :class:`MergeProcessor`
- :mod:`batch_window` — :class:`BatchWindowProcessor`
- :mod:`deduplicate` — :class:`DeduplicateProcessor`
- :mod:`formatter` — :class:`FormatterProcessor`
- :mod:`debounce` — :class:`DebounceProcessor`

Ponytail: Phase 1 = re-export из legacy godfile (zero-risk).
Phase 2 = физическое разделение в thematic files (S175.5+).
"""
from __future__ import annotations

from src.backend.dsl.engine.processors.patterns._helpers import _SafeDict  # noqa: F401
from src.backend.dsl.engine.processors.patterns.batch_window import (  # noqa: F401
    BatchWindowProcessor,
)
from src.backend.dsl.engine.processors.patterns.debounce import (  # noqa: F401
    DebounceProcessor,
)
from src.backend.dsl.engine.processors.patterns.deduplicate import (  # noqa: F401
    DeduplicateProcessor,
)
from src.backend.dsl.engine.processors.patterns.formatter import (  # noqa: F401
    FormatterProcessor,
)
from src.backend.dsl.engine.processors.patterns.merge import (  # noqa: F401
    MergeProcessor,
)
from src.backend.dsl.engine.processors.patterns.switch import (  # noqa: F401
    SwitchProcessor,
)

__all__ = (
    "BatchWindowProcessor",
    "DebounceProcessor",
    "DeduplicateProcessor",
    "FormatterProcessor",
    "MergeProcessor",
    "SwitchProcessor",
    "_SafeDict",
)
