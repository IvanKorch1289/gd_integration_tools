"""Data Quality Engine — rules + quarantine (Wave 4 #35).

Проблема:
    Интеграция «прошла», но данные испорчены:
    - Отсутствуют обязательные поля.
    - Дубликаты (тот же order_id дважды).
    - Значения вне допустимого диапазона.
    - Невалидный формат (email, ИНН).

Решение:
    ``DataQualityEngine`` — declarative rules + quarantine:

    1. ``QualityRule`` — единое правило (completeness/uniqueness/range/format/ref).
    2. ``RuleSet`` — набор правил для конкретного record type.
    3. ``DataQualityEngine`` — execute rules against records.
    4. ``QualityReport`` — passed/failed + violation details.
    5. ``quarantine(record, reason)`` — separate failed records.
    6. Pure-Python (без external deps).

Использование::

    from src.backend.core.data_quality import (  # noqa: F401 — re-export
        DataQualityEngine, RuleSet, QualityRule, RuleKind,
    )

    engine = DataQualityEngine()
    rules = RuleSet(
        record_type="order",
        rules=[
            QualityRule(field="order_id", kind=RuleKind.NON_NULL),
            QualityRule(field="amount", kind=RuleKind.RANGE, min=0, max=1_000_000),
            QualityRule(field="email", kind=RuleKind.FORMAT, regex=r"^[^@]+@[^@]+$"),
            QualityRule(field="order_id", kind=RuleKind.UNIQUE),
        ],
    )
    engine.register(rules)

    report = engine.check("order", records)
    if report.failed > 0:
        for violation in report.violations:
            engine.quarantine(violation.record, reason=violation.reason)
"""

from __future__ import annotations

from src.backend.core.data_quality.engine import (  # noqa: F401 — re-export
    DataQualityEngine,
    QualityReport,
    QualityRule,
    QualityViolation,
    RuleKind,
    RuleSet,
    get_data_quality_engine,
)

__all__ = (
    "DataQualityEngine",
    "QualityReport",
    "QualityRule",
    "QualityViolation",
    "RuleKind",
    "RuleSet",
    "get_data_quality_engine",
)
