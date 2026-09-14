"""Migration Safety Gate — Alembic migration analysis (Wave 4 #33).

Проблема:
    Миграция может:
    - Взять ACCESS EXCLUSIVE lock на большой таблице.
    - Заблокировать production на минуты/часы.
    - Удалить колонку, от которой зависят старые сервисы.
    - Не иметь rollback plan.

Решение:
    ``MigrationSafetyGate`` — pure-Python static analysis:

    1. ``analyze_migration(revision, previous)`` — detect risky operations.
    2. ``MigrationReport`` — список findings с severity.
    3. ``RiskLevel`` — LOW / MEDIUM / HIGH / CRITICAL.
    4. ``check_lock_grades(operations)`` — estimate lock time.
    5. ``check_rollback(operations)`` — detect irreversible ops.

Использование::

    from src.backend.core.migration_safety import (
        MigrationSafetyGate, analyze_migration, RiskLevel,
    )

    gate = MigrationSafetyGate()
    report = gate.analyze_migration(revision_file)
    if report.critical_count > 0:
        raise ValueError(f"Migration blocked: {report.findings}")
"""

from __future__ import annotations

from src.backend.core.migration_safety.gate import (
    Finding,
    MigrationReport,
    MigrationSafetyGate,
    RiskLevel,
    analyze_migration,
    get_safety_gate,
)

__all__ = (
    "Finding",
    "MigrationReport",
    "MigrationSafetyGate",
    "RiskLevel",
    "analyze_migration",
    "get_safety_gate",
)
