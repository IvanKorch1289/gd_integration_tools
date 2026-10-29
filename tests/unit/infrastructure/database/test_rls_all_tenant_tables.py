"""ADR-0386: RLS-политики на всех tenant-таблицах (миграция + состав списка).

Миграция ``2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables`` включает
RLS + tenant-политику на всех таблицах с колонкой ``tenant_id``. Тесты
проверяют:

* состав списка таблиц (список tenant_id-таблиц выводится из миграций,
  чтобы новые tenant-таблицы не могли остаться без RLS);
* генерацию SQL (без живой PostgreSQL — ``op.execute`` перехватывается);
* no-op на не-PostgreSQL диалектах;
* обратимость (downgrade) — включая восстановление legacy-политик.
"""

from __future__ import annotations

import ast
import re
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_VERSIONS_DIR = (
    _PROJECT_ROOT
    / "src/backend/infrastructure/database/migrations/versions"
)

migration = import_module(
    "src.backend.infrastructure.database.migrations.versions."
    "2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables"
)

_ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+([A-Za-z_]\w*)\s+ADD\s+COLUMN\s+tenant_id", re.IGNORECASE
)


def _call_name(node: ast.Call) -> str:
    """Имя вызываемой функции/метода.

    Args:
        node: AST-узел вызова.

    Returns:
        Имя атрибута или функции (пустая строка — неизвестно).

    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_tenant_id_column(node: ast.expr) -> bool:
    """Является ли узел колонкой ``tenant_id``.

    Args:
        node: AST-узел (аргумент ``create_table`` / ``add_column``).

    Returns:
        ``True``, если это ``sa.Column("tenant_id", ...)``.

    """
    if not isinstance(node, ast.Call) or _call_name(node) != "Column":
        return False
    if not node.args:
        return False
    first = node.args[0]
    return isinstance(first, ast.Constant) and first.value == "tenant_id"


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Собрать строковые константы уровня модуля ( ``TABLE = "x"`` ).

    Args:
        tree: Разобранный AST миграции.

    Returns:
        Соответствие ``имя → значение``.

    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
    return constants


def _string_value(node: ast.expr, constants: dict[str, str]) -> str | None:
    """Извлечь строковое значение (литерал или модульная константа).

    Args:
        node: AST-узел.
        constants: Константы уровня модуля.

    Returns:
        Значение строки либо ``None``.

    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _tables_with_tenant_id() -> set[str]:
    """Вывести список таблиц с колонкой ``tenant_id`` из миграций.

    Returns:
        Множество имён таблиц.

    """
    tables: set[str] = set()
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in {"create_table", "add_column"} and node.args:
                    table = _string_value(node.args[0], constants)
                    if table and any(
                        _is_tenant_id_column(arg) for arg in node.args[1:]
                    ):
                        tables.add(table)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                match = _ADD_COLUMN_RE.search(node.value)
                if match:
                    tables.add(match.group(1))
    return tables


def _run_migration(dialect: str, func_name: str) -> list[str]:
    """Выполнить ``upgrade``/``downgrade`` миграции на поддельном bind.

    Args:
        dialect: Имя диалекта (``postgresql`` / ``sqlite``).
        func_name: Имя функции миграции.

    Returns:
        Список выполненных SQL-команд.

    """
    fake_op = MagicMock()
    fake_op.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name=dialect)
    )
    original_op = migration.op
    migration.op = fake_op
    try:
        getattr(migration, func_name)()
    finally:
        migration.op = original_op
    return [call.args[0] for call in fake_op.execute.call_args_list]


class TestRLSTableList:
    """Состав списка tenant-таблиц."""

    def test_excluded_tables_are_explicit(self) -> None:
        """Исключения зафиксированы явно и с обоснованием."""
        excluded = migration.EXCLUDED_TABLES

        assert set(excluded) == {
            "audit_log_immutable",
            "dlq_inbox",
            "scheduler_run_history",
        }
        for table, reason in excluded.items():
            assert reason.strip(), f"Пустое обоснование для {table}"

    def test_covers_every_tenant_id_table(self) -> None:
        """Каждая таблица с ``tenant_id`` покрыта RLS или исключена."""
        derived = _tables_with_tenant_id()
        covered = {table.name for table in migration.RLS_TABLES}

        assert derived - covered == set(migration.EXCLUDED_TABLES), (
            "Таблицы с tenant_id без RLS и без явного исключения: "
            f"{sorted(derived - covered - set(migration.EXCLUDED_TABLES))}"
        )

    def test_no_duplicate_tables(self) -> None:
        """Список без дублей."""
        names = [table.name for table in migration.RLS_TABLES]
        assert len(names) == len(set(names))

    def test_langmem_tables_not_included(self) -> None:
        """``langmem_*`` изолируются колонкой ``tenant``, не ``tenant_id``."""
        names = {table.name for table in migration.RLS_TABLES}
        assert "langmem_episodic" not in names
        assert "langmem_procedural" not in names


class TestUpgradeSQL:
    """Генерация SQL (без живой PostgreSQL)."""

    def test_generates_rls_for_every_table(self) -> None:
        """Для каждой таблицы — ENABLE + FORCE + CREATE POLICY."""
        statements = _run_migration("postgresql", "upgrade")
        joined = "\n".join(statements)

        assert len(statements) == len(migration.RLS_TABLES)
        for table in migration.RLS_TABLES:
            policy = migration.policy_name(table.name)
            assert f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY" in joined
            assert f"ALTER TABLE {table.name} FORCE ROW LEVEL SECURITY" in joined
            assert f"CREATE POLICY {policy} ON {table.name}" in joined
            assert "current_setting(''app.tenant_id'', true)" in joined

    def test_global_tables_allow_null_tenant(self) -> None:
        """Nullable ``tenant_id`` — глобальные строки остаются видимыми."""
        joined = " ".join("\n".join(_run_migration("postgresql", "upgrade")).split())

        for table in migration.RLS_TABLES:
            policy = migration.policy_name(table.name)
            predicate = (
                "tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', true)"
                if table.allow_global
                else "tenant_id = current_setting('app.tenant_id', true)"
            )
            # Внутри ``EXECUTE``-строки кавычки экранированы удвоением.
            escaped = predicate.replace("'", "''")
            assert (
                f"CREATE POLICY {policy} ON {table.name} ' || 'USING ({escaped}) '"
                in joined
            ), f"Некорректный предикат политики {policy}"

    def test_legacy_policies_are_replaced(self) -> None:
        """Legacy-политики S21 удаляются (иначе две политики на таблицу)."""
        joined = "\n".join(_run_migration("postgresql", "upgrade"))

        for table in migration.RLS_TABLES:
            if table.legacy_policy:
                assert (
                    f"DROP POLICY IF EXISTS {table.legacy_policy} ON {table.name}"
                    in joined
                )

    def test_noop_on_non_postgres(self) -> None:
        """На других диалектах — no-op."""
        assert _run_migration("sqlite", "upgrade") == []


class TestDowngradeSQL:
    """Обратимость миграции."""

    def test_new_tables_disable_rls(self) -> None:
        """Для новых таблиц RLS выключается."""
        joined = "\n".join(_run_migration("postgresql", "downgrade"))

        for table in migration.RLS_TABLES:
            if table.legacy_policy is None:
                assert f"ALTER TABLE {table.name} DISABLE ROW LEVEL SECURITY" in joined

    def test_legacy_policies_restored(self) -> None:
        """Для таблиц S21 legacy-политика восстанавливается."""
        joined = "\n".join(_run_migration("postgresql", "downgrade"))

        for table in migration.RLS_TABLES:
            if table.legacy_policy:
                assert (
                    f"CREATE POLICY {table.legacy_policy} ON {table.name}" in joined
                )

    def test_noop_on_non_postgres(self) -> None:
        """На других диалектах — no-op."""
        assert _run_migration("sqlite", "downgrade") == []


class TestAlembicChain:
    """Миграция встроена в цепочку alembic."""

    def test_revision_ids(self) -> None:
        """revision / down_revision соответствуют ожидаемым."""
        assert migration.revision == "e2f3a4b5c6d7"
        assert migration.down_revision == "f1a2b3c4d5e6"

    def test_single_head(self) -> None:
        """В цепочке alembic остаётся один head."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)

        heads = script.get_heads()
        assert heads == ["e2f3a4b5c6d7"]
