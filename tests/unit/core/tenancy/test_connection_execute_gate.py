"""ADR-0386: гейт привилегированных raw-вызовов ``Connection.execute(text(...))``.

ORM-фильтр живёт в session-level событии ``do_orm_execute``. Core-вызов
``Connection.execute(text(...))`` идёт мимо этого guard'а — это
**привилегированный путь**, разрешённый по контракту ADR-0386 только
инфраструктуре (CDC со своим профилем БД, warmup ``SELECT 1``, внутренний
retry-обход).

Гейт сканирует бизнес-слой (``src/backend/dsl``,
``src/backend/services``) и падает на любом неallowlisted-вызове.
Инфраструктурные каталоги в сканирование не входят — они осознанно
привилегированные (перечень — в ADR-0386).

Session-level вызовы (``session.execute(text(...))``) guard проходит
(``do_orm_execute`` срабатывает и на ``TextClause``) — они нарушением
не являются.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

#: Каталоги бизнес-слоя, где привилегированный raw-вызов запрещён.
SCAN_ROOTS: tuple[str, ...] = (
    "src/backend/dsl",
    "src/backend/services",
)

#: Session-получатели: ``Session.execute`` проходит через tenant-guard.
_SESSION_RECEIVERS: frozenset[str] = frozenset(
    {"session", "_session", "db_session", "async_session", "sync_session"}
)

#: Осознанно привилегированные вызовы (найдены wave-17 аудитом).
#: Формат: относительный путь → обоснование.
ALLOWLIST: dict[str, str] = {
    "src/backend/dsl/engine/processors/components/databasequeryprocessor.py": (
        "DSL-процессор «сырой SQL»: валидация SQL (ADR-0382/0380) + "
        "tenant-guard обходится осознанно — но ADR-0393 добавил перед "
        "выполнением fail-closed проверку tenant-предиката "
        "(core.tenancy.sqlalchemy_filter.guard_raw_sql) и capability-гейт "
        "db.read/db.write; остаётся Core-вызов, а не Session"
    ),
    "src/backend/dsl/engine/processors/ml_inference.py": (
        "Transactional outbox: INSERT в outbox_messages — таблица без "
        "tenant_id, tenant-скоуп неприменим"
    ),
    "src/backend/dsl/engine/processors/storage_ext.py": (
        "Time-series writer (INSERT в timeseries-таблицу): tenant_id "
        "у таблицы нет, tenant-скоуп неприменим"
    ),
}


@dataclass(frozen=True)
class Finding:
    """Найденный привилегированный raw-вызов."""

    path: str
    line: int
    receiver: str


def _receiver_name(node: ast.expr) -> str:
    """Имя получателя вызова ``.execute(...)``.

    Args:
        node: Выражение-получатель (``conn``, ``self._conn``, ``session``).

    Returns:
        Имя атрибута/переменной (пустая строка — неизвестный получатель).

    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_text_call(node: ast.expr) -> bool:
    """Является ли выражение вызовом ``text(...)``.

    Args:
        node: Выражение-аргумент.

    Returns:
        ``True``, если это ``text(...)``.

    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "text"
    )


def find_violations(root: Path) -> list[Finding]:
    """Найти привилегированные raw-вызовы в каталоге.

    Args:
        root: Корень сканирования.

    Returns:
        Список нарушений (пустой — нарушений нет).

    """
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "execute":
                continue
            if not node.args or not _is_text_call(node.args[0]):
                continue
            receiver = _receiver_name(func.value)
            if receiver in _SESSION_RECEIVERS:
                continue
            try:
                relative = path.relative_to(_PROJECT_ROOT).as_posix()
            except ValueError:
                relative = path.as_posix()
            findings.append(
                Finding(
                    path=relative,
                    line=node.lineno,
                    receiver=receiver,
                )
            )
    return findings


def _all_findings() -> list[Finding]:
    """Собрать нарушения по всем сканируемым каталогам."""
    findings: list[Finding] = []
    for root in SCAN_ROOTS:
        findings.extend(find_violations(_PROJECT_ROOT / root))
    return findings


def test_no_unclassified_privileged_execute_calls() -> None:
    """В бизнес-слое нет неallowlisted ``Connection.execute(text(...))``."""
    findings = _all_findings()
    unclassified = [f for f in findings if f.path not in ALLOWLIST]

    assert not unclassified, (
        "Привилегированный raw-вызов в бизнес-слое (ADR-0386): "
        + "; ".join(f"{f.path}:{f.line} ({f.receiver}.execute(text(...)))" for f in unclassified)
        + ". Используйте Session (ORM/raw-SQL guard) либо добавьте обоснование "
        "в ALLOWLIST гейта."
    )


def test_allowlist_entries_are_not_stale() -> None:
    """Allowlist не содержит «мёртвых» записей."""
    findings = _all_findings()
    found_paths = {f.path for f in findings}

    stale = [path for path in ALLOWLIST if path not in found_paths]

    assert not stale, f"Allowlist-гейта содержит устаревшие записи: {stale}"


def test_detector_finds_connection_but_not_session(tmp_path: Path) -> None:
    """Сам детектор: ``conn.execute(text(...))`` — нарушение, session — нет."""
    module = tmp_path / "sample.py"
    module.write_text(
        "from sqlalchemy import text\n"
        "\n"
        "async def run(conn, session):\n"
        "    await conn.execute(text('SELECT 1'))\n"
        "    await session.execute(text('SELECT 1'))\n",
        encoding="utf-8",
    )

    findings = find_violations(tmp_path)

    assert [(f.receiver, f.line) for f in findings] == [("conn", 4)]


def test_allowlist_entries_have_reason() -> None:
    """Каждая запись allowlist объясняет, почему вызов привилегированный."""
    for path, reason in ALLOWLIST.items():
        assert reason.strip(), f"Пустое обоснование для {path}"
        assert ( _PROJECT_ROOT / path).is_file(), f"Allowlist-путь не найден: {path}"
