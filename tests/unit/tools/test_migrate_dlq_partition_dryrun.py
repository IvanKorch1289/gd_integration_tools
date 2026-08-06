"""Unit tests for tools/migrations/migrate_dlq_partition.py (D-AUDIT-#15).

Строгие проверки dry-run vs confirm:

* dry-run: ``client.command`` НЕ вызывается (assert_not_called).
* --confirm: ``client.command`` вызывается ровно один раз для каждого
  DDL-шага с правильным SQL.

Покрывает:
1. ``parse_args`` defaults (dry-run on).
2. ``build_ddl_statements`` — структура SQL.
3. ``run_migration(dry-run)`` — НЕТ вызова client.command.
4. ``run_migration(--confirm)`` — РОВНО один вызов каждого DDL-шага.
5. Env-based CONFIRM=1 — equivalent to --confirm.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# tools/migrations в path для импорта.
_TOOLS_MIGRATIONS = Path(__file__).resolve().parents[3] / "tools" / "migrations"
if str(_TOOLS_MIGRATIONS) not in sys.path:
    sys.path.insert(0, str(_TOOLS_MIGRATIONS))

import migrate_dlq_partition as mig  # noqa: E402


class TestParseArgs:
    """Defaults: dry-run ON (no --confirm)."""

    def test_dry_run_default(self) -> None:
        args = mig.parse_args([])
        assert args.dry_run is True
        assert args.confirm is False
        assert args.table_source == "dlq_events"
        assert args.database == "default"

    def test_confirm_flag_overrides(self) -> None:
        args = mig.parse_args(["--confirm"])
        assert args.confirm is True
        assert args.dry_run is True  # argparse default не меняется

    def test_custom_database(self) -> None:
        args = mig.parse_args(["--database", "analytics"])
        assert args.database == "analytics"

    def test_cluster_opt_in(self) -> None:
        args = mig.parse_args(["--cluster", "company_cluster"])
        assert args.cluster == "company_cluster"


class TestBuildDdlStatements:
    """Структура DDL: 3 шага (CREATE NEW, COPY, RENAME)."""

    def test_returns_three_statements(self) -> None:
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )
        assert len(plan.statements) == 3

    def test_create_new_has_partition_by(self) -> None:
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )
        assert "PARTITION BY toYYYYMM(created_at)" in plan.create_new_sql

    def test_copy_sql_selects_from_source(self) -> None:
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )
        assert "INSERT INTO analytics.dlq_events_new" in plan.copy_sql
        assert "SELECT * FROM analytics.dlq_events" in plan.copy_sql

    def test_rename_atomic_swap(self) -> None:
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )
        assert (
            "RENAME TABLE analytics.dlq_events TO analytics.dlq_events_old"
            in plan.rename_sql
        )
        assert (
            ", analytics.dlq_events_new TO analytics.dlq_events"
            in plan.rename_sql
        )

    def test_replicated_cluster_adds_on_cluster(self) -> None:
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
            cluster="company_cluster",
        )
        assert "ON CLUSTER 'company_cluster'" in plan.create_new_sql
        assert "ON CLUSTER 'company_cluster'" in plan.rename_sql

    def test_single_node_no_on_cluster(self) -> None:
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
            cluster=None,
        )
        assert "ON CLUSTER" not in plan.create_new_sql
        assert "ON CLUSTER" not in plan.rename_sql


class TestRunMigrationDryRun:
    """Dry-run: ни одного вызова client.command (STRICT)."""

    def test_dry_run_does_not_invoke_client(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = MagicMock()
        client.command = MagicMock(return_value=None)

        args = mig.parse_args(
            [
                "--database",
                "analytics",
                "--stats-out",
                str(tmp_path / "stats.json"),
            ]
        )
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )

        exit_code = mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        assert exit_code == 0
        # STRICT: ни одного DDL call.
        client.command.assert_not_called()

    def test_dry_run_via_no_confirm_flag(
        self,
        tmp_path: Path,
    ) -> None:
        """Default mode (no --confirm) = dry-run."""

        client = MagicMock()
        client.command = MagicMock(return_value=None)

        args = mig.parse_args(
            [
                "--dry-run",
                "--stats-out",
                str(tmp_path / "stats.json"),
            ]
        )
        # Аргумент --dry-run в CLI уже включён по умолчанию;
        # проверяем, что confirm=False → dry-run.
        assert args.confirm is False

        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="default",
        )
        exit_code = mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )
        assert exit_code == 0
        client.command.assert_not_called()

    def test_dry_run_writes_stats_with_plan(
        self,
        tmp_path: Path,
    ) -> None:
        client = MagicMock()
        client.command = MagicMock(return_value=None)
        stats_path = tmp_path / "dry_stats.json"
        args = mig.parse_args(["--stats-out", str(stats_path)])
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )

        mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        assert stats_path.exists()
        payload = json.loads(stats_path.read_text())
        assert payload["mode"] == "dry-run"
        assert len(payload["plan"]["statements"]) == 3
        assert payload["executed"] == []


class TestRunMigrationConfirm:
    """Confirm mode: каждый DDL-шаг вызывается ровно один раз."""

    def test_confirm_invokes_each_ddl_once(
        self,
        tmp_path: Path,
    ) -> None:
        client = MagicMock()
        client.command = MagicMock(return_value=None)
        client.close = MagicMock(return_value=None)

        args = mig.parse_args(
            [
                "--confirm",
                "--database",
                "analytics",
                "--stats-out",
                str(tmp_path / "confirm_stats.json"),
            ]
        )
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )

        exit_code = mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        assert exit_code == 0
        # STRICT: ровно 3 вызова (CREATE + INSERT + RENAME).
        assert client.command.call_count == 3

        # Первый вызов — CREATE TABLE dlq_events_new.
        first_call = client.command.call_args_list[0]
        assert "CREATE TABLE" in first_call.args[0]
        assert "analytics.dlq_events_new" in first_call.args[0]
        assert "PARTITION BY toYYYYMM(created_at)" in first_call.args[0]

        # Второй — INSERT INTO ... SELECT.
        second_call = client.command.call_args_list[1]
        assert "INSERT INTO analytics.dlq_events_new" in second_call.args[0]
        assert "SELECT * FROM analytics.dlq_events" in second_call.args[0]

        # Третий — RENAME (atomic swap).
        third_call = client.command.call_args_list[2]
        assert "RENAME TABLE" in third_call.args[0]
        assert "analytics.dlq_events TO analytics.dlq_events_old" in third_call.args[0]
        assert (
            "analytics.dlq_events_new TO analytics.dlq_events"
            in third_call.args[0]
        )

    def test_confirm_does_not_drop_old_table(
        self,
        tmp_path: Path,
    ) -> None:
        """DROP TABLE оставлен на ручное выполнение — НЕ вызывается."""

        client = MagicMock()
        client.command = MagicMock(return_value=None)

        args = mig.parse_args(
            [
                "--confirm",
                "--stats-out",
                str(tmp_path / "no_drop.json"),
            ]
        )
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="default",
        )

        mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        # Ни один из вызовов не должен содержать DROP TABLE.
        for call in client.command.call_args_list:
            sql = call.args[0]
            assert "DROP TABLE" not in sql.upper()

    def test_confirm_writes_stats_with_executed(
        self,
        tmp_path: Path,
    ) -> None:
        client = MagicMock()
        client.command = MagicMock(return_value=None)
        stats_path = tmp_path / "confirm_executed.json"
        args = mig.parse_args(["--confirm", "--stats-out", str(stats_path)])
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )

        mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        payload = json.loads(stats_path.read_text())
        assert payload["mode"] == "confirm"
        assert len(payload["executed"]) == 3
        assert payload["completed_at"] is not None

    def test_env_confirm_enables_write_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CONFIRM=1 env var → equivalent to --confirm."""

        client = MagicMock()
        client.command = MagicMock(return_value=None)

        monkeypatch.setenv("CONFIRM", "1")
        args = mig.parse_args(
            [
                "--database",
                "analytics",
                "--stats-out",
                str(tmp_path / "env_confirm.json"),
            ]
        )
        # CLI без --confirm, но env должен включить write mode.
        assert args.confirm is False
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="analytics",
        )

        exit_code = mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        assert exit_code == 0
        assert client.command.call_count == 3

    def test_ddl_failure_returns_exit_one(
        self,
        tmp_path: Path,
    ) -> None:
        client = MagicMock()
        client.command = MagicMock(side_effect=RuntimeError("boom"))
        client.close = MagicMock(return_value=None)

        args = mig.parse_args(
            [
                "--confirm",
                "--stats-out",
                str(tmp_path / "failure.json"),
            ]
        )
        plan = mig.build_ddl_statements(
            table_source="dlq_events",
            table_new="dlq_events_new",
            database="default",
        )

        exit_code = mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=plan,
        )

        assert exit_code == 1
        # Только первая команда была попытка (CREATE), упала.
        assert client.command.call_count == 1
        # Stats должен содержать failed_step.
        payload = json.loads((tmp_path / "failure.json").read_text())
        assert payload["failed_step"] == 1


class TestPlanInjection:
    """Plan можно инжектить (для тестов с альтернативным schema)."""

    def test_custom_plan_is_used(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.command = MagicMock(return_value=None)

        custom_plan = mig.MigrationPlan(
            table_source="dlq_events",
            table_new="dlq_events_new",
            table_old="dlq_events_old",
            database="analytics",
            statements=[
                "CREATE TABLE analytics.dlq_events_new (x Int32) "
                "ENGINE = MergeTree() PARTITION BY x ORDER BY x",
                "INSERT INTO analytics.dlq_events_new SELECT * "
                "FROM analytics.dlq_events",
                "RENAME TABLE analytics.dlq_events TO "
                "analytics.dlq_events_old, analytics.dlq_events_new "
                "TO analytics.dlq_events",
            ],
        )

        args = mig.parse_args(
            ["--confirm", "--stats-out", str(tmp_path / "custom.json")]
        )
        exit_code = mig.run_migration(
            args,
            client_factory=lambda **_: client,
            plan=custom_plan,
        )
        assert exit_code == 0
        assert client.command.call_count == 3
        # Проверяем, что кастомный SQL использован.
        first_sql = client.command.call_args_list[0].args[0]
        assert "x Int32" in first_sql
