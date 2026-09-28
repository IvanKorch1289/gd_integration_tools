"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors.batch_processor``.

Ранее shim был «молчаливым» ``import *``-re-export'ом: класс отдавался
корректно, но миграционный сигнал отсутствовал, поэтому downstream-импорты
не могли отследить оставшиеся обращения к legacy-пути.

Теперь при импорте испускается :class:`DeprecationWarning` с owner/replacement/
remove-date, как требует политика compatibility-shim'ов (ADR-0313, migration
window до cycle 156).

Warning испускается только при ПЕРВОМ импорте модуля (top-level), поэтому для
повторной проверки в тестах нужен ``importlib.reload``.
"""

from __future__ import annotations

import warnings

from src.backend.dsl.engine.processors.batch_processor import *  # noqa: F401,F403

warnings.warn(
    "src.backend.dsl.processors.batch_processor — legacy путь, DEPRECATED "
    "(ADR-0313). Используйте canonical "
    "src.backend.dsl.engine.processors.batch_processor. "
    "Remove date: cycle 156 (telemetry audit).",
    DeprecationWarning,
    stacklevel=2,
)
