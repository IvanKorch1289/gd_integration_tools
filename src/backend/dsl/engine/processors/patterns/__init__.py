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
from __future__ import annotations as annotations

from src.backend.dsl.engine.processors.patterns._helpers import (
    _SafeDict,
)
from src.backend.dsl.engine.processors.patterns.batch_window import (
    BatchWindowProcessor as BatchWindowProcessor,
)
from src.backend.dsl.engine.processors.patterns.debounce import (
    DebounceProcessor as DebounceProcessor,
)
from src.backend.dsl.engine.processors.patterns.deduplicate import (
    DeduplicateProcessor as DeduplicateProcessor,
)
from src.backend.dsl.engine.processors.patterns.formatter import (
    FormatterProcessor as FormatterProcessor,
)
from src.backend.dsl.engine.processors.patterns.merge import (
    MergeProcessor as MergeProcessor,
)
from src.backend.dsl.engine.processors.patterns.switch import (
    SwitchProcessor as SwitchProcessor,
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
