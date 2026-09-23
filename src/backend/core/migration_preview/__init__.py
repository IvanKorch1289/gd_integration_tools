"""Migration Preview / Dry-run (Wave 4 #33b).

Проблема:
    Нет способа preview SQL migration перед apply:
    - Не знаем какие locks будут взяты.
    - Не знаем какие tables/data изменятся.
    - Можно случайно drop'нуть production table.

Решение:
    ``MigrationPreview`` — pure-Python SQL analyzer (no DB connection):

    1. ``MigrationOperation`` — single SQL statement (parsed).
    2. ``MigrationPreviewReport`` — list of operations + impact summary.
    3. ``MigrationPreviewer`` — parse + analyze SQL file.
    4. Pattern matching: DROP/ALTER/INSERT/UPDATE/CREATE.
    5. Lock type detection (ACCESS EXCLUSIVE / SHARE / etc).
    6. Severity: CRITICAL (DROP) / HIGH (ALTER) / LOW (CREATE).

Использование::

    from src.backend.core.migration_preview import (  # noqa: F401 — re-export
        MigrationPreviewer, MigrationPreviewReport, OperationType,
        LockType, get_migration_previewer,
    )

    previewer = get_migration_previewer()
    report = previewer.preview_file("migrations/0042_add_table.sql")
    for op in report.operations:
        print(f"{op.severity} {op.lock_type}: {op.statement[:50]}")
"""

from __future__ import annotations

from src.backend.core.migration_preview.preview import (  # noqa: F401 — re-export
    LockType,
    MigrationOperation,
    MigrationPreviewer,
    MigrationPreviewReport,
    OperationType,
    Severity,
    get_migration_previewer,
)

__all__ = (
    "LockType",
    "MigrationOperation",
    "MigrationPreviewer",
    "MigrationPreviewReport",
    "OperationType",
    "Severity",
    "get_migration_previewer",
)
