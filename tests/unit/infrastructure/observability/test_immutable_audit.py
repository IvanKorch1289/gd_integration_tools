"""Unit-тесты ``ImmutableAuditStore`` (Wave 13, Q18: имя таблицы в SQL).

Имя таблицы интерполируется в 4 SQL-запросах модуля (``append``/``verify``).
Bind-параметры к идентификаторам неприменимы, поэтому имя валидируется
allowlist-регексом в конструкторе (fail-fast на старте).
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.immutable_audit import ImmutableAuditStore


def _store(table_name: str) -> ImmutableAuditStore:
    """Собрать store с явным секретом (без зависимости от env)."""
    return ImmutableAuditStore(
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
        secret_key=b"test-secret",
        table_name=table_name,
    )


@pytest.mark.parametrize(
    "bad_name",
    [
        "audit; DROP TABLE x",
        "audit log",
        "audit'--",
        "1audit",
        "",
        "audit\n",
    ],
)
def test_invalid_table_name_rejected(bad_name: str) -> None:
    """Невалидное имя таблицы → ValueError на конструкторе (fail-fast)."""
    with pytest.raises(ValueError, match="Недопустимый SQL identifier"):
        _store(bad_name)


def test_valid_table_name_accepted() -> None:
    """Валидное имя таблицы принимается без изменений."""
    assert _store("audit_log_immutable")._table == "audit_log_immutable"
