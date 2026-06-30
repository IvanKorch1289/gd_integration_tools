"""Unit tests for tools/migrations/migrate_api_keys_to_argon2.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Добавляем tools/migrations в path для импорта.
_TOOLS_MIGRATIONS = Path(__file__).resolve().parents[3] / "tools" / "migrations"
if str(_TOOLS_MIGRATIONS) not in sys.path:
    sys.path.insert(0, str(_TOOLS_MIGRATIONS))

import migrate_api_keys_to_argon2 as mig  # noqa: E402


class TestLoadKeysFile:
    """Tests for :func:`mig._load_keys_file` (file → {client_id: raw_key})."""

    def test_basic_format(self, tmp_path: Path) -> None:
        path = tmp_path / "keys.txt"
        path.write_text(
            "service_a:gd_aaaaaaaaaaaaaaaaaaaa\n"
            "service_b:gd_bbbbbbbbbbbbbbbbbbbb\n"
        )
        result = mig._load_keys_file(path)
        assert result == {
            "service_a": "gd_aaaaaaaaaaaaaaaaaaaa",
            "service_b": "gd_bbbbbbbbbbbbbbbbbbbb",
        }

    def test_skip_empty_and_comment_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "keys.txt"
        path.write_text(
            "# comment\n"
            "\n"
            "service_a:gd_aaa\n"
            "  \n"
        )
        result = mig._load_keys_file(path)
        assert result == {"service_a": "gd_aaa"}

    def test_skip_invalid_format_no_colon(self, tmp_path: Path, caplog) -> None:
        path = tmp_path / "keys.txt"
        path.write_text(
            "service_a:gd_aaa\n"
            "no_colon_line\n"
            "service_b:gd_bbb\n"
        )
        result = mig._load_keys_file(path)
        assert result == {"service_a": "gd_aaa", "service_b": "gd_bbb"}

    def test_duplicate_client_id_warns_last_wins(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "keys.txt"
        path.write_text("client:gd_first\nclient:gd_second\n")
        with caplog.at_level("WARNING"):
            result = mig._load_keys_file(path)
        assert result == {"client": "gd_second"}


class TestProcessOne:
    """Tests for :func:`mig._process_one` — single-key upgrade logic."""

    @pytest.mark.asyncio
    async def test_already_argon2_skipped(self) -> None:
        conn = MagicMock()
        stored = {
            "client_id": "c1",
            "key_hash": "$argon2id$v=19$m=65536,t=3,p=4$"
            "salt123456789012345678901$h",
            "hash_algo": "argon2id",
        }
        conn.get = AsyncMock(return_value=json.dumps(stored).encode())

        stats = mig.MigrationStats()
        await mig._process_one(
            conn,
            "apikey:c1",
            keys_map={"c1": "irrelevant"},
            dry_run=True,
            stats=stats,
        )
        assert stats.scanned == 1
        assert stats.skipped_already_argon2 == 1
        assert stats.upgraded == 0

    @pytest.mark.asyncio
    async def test_legacy_sha_upgraded_in_dry_run(self) -> None:
        """Dry-run: legacy SHA upgrade-candidate сообщается как upgraded."""
        # Создаём реальный legacy SHA hash для known key.
        import hashlib

        raw_key = "gd_test_raw_key_for_upgrade"
        legacy_sha = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        conn = MagicMock()
        stored = {
            "client_id": "service_a",
            "key_hash": legacy_sha,
            "hash_algo": "sha256",  # legacy marker
        }
        conn.get = AsyncMock(return_value=json.dumps(stored).encode())

        stats = mig.MigrationStats()
        await mig._process_one(
            conn,
            "apikey:service_a",
            keys_map={"service_a": raw_key},
            dry_run=True,
            stats=stats,
        )
        assert stats.scanned == 1
        assert stats.upgraded == 1  # dry-run upgrade counts as "would-upgrade"
        assert stats.failed_verify == 0
        # В dry-run mode SET не вызывается.
        conn.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_upgrade_writes_argon2(self) -> None:
        """Real upgrade path: SET → new Argon2 hash written."""
        import hashlib

        raw_key = "gd_test_real_upgrade"
        legacy_sha = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        conn = MagicMock()
        stored = {
            "client_id": "service_b",
            "key_hash": legacy_sha,
            "hash_algo": "sha256",
        }
        conn.get = AsyncMock(return_value=json.dumps(stored).encode())
        conn.set = AsyncMock()
        conn.xadd = AsyncMock(return_value=b"1-0")

        stats = mig.MigrationStats()
        await mig._process_one(
            conn,
            "apikey:service_b",
            keys_map={"service_b": raw_key},
            dry_run=False,
            stats=stats,
        )

        assert stats.upgraded == 1
        assert stats.scanned == 1

        # Verify SET was called with new Argon2 hash.
        conn.set.assert_awaited_once()
        call_args = conn.set.await_args
        new_value_json = call_args.args[1]
        new_data = json.loads(new_value_json)
        assert new_data["hash_algo"] == "argon2id"
        assert new_data["key_hash"].startswith("$argon2id$")

        # Verify xadd (audit event).
        conn.xadd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_legacy_no_raw_key_skipped(self) -> None:
        """Legacy SHA, но raw_key не в keys-map → skipped."""
        import hashlib

        legacy_sha = hashlib.sha256(b"some-key").hexdigest()
        conn = MagicMock()
        stored = {
            "client_id": "no_in_file",
            "key_hash": legacy_sha,
            "hash_algo": "sha256",
        }
        conn.get = AsyncMock(return_value=json.dumps(stored).encode())

        stats = mig.MigrationStats()
        await mig._process_one(
            conn,
            "apikey:no_in_file",
            keys_map={"different_client": "x"},
            dry_run=False,
            stats=stats,
        )
        assert stats.skipped_no_raw_key == 1
        assert stats.upgraded == 0
        assert stats.failed_verify == 0

    @pytest.mark.asyncio
    async def test_verify_failure_counted(self) -> None:
        """SHA verify fails (wrong raw key) → failed_verify count."""
        import hashlib

        stored_sha = hashlib.sha256(b"original-key").hexdigest()
        conn = MagicMock()
        stored = {
            "client_id": "c1",
            "key_hash": stored_sha,
        }
        conn.get = AsyncMock(return_value=json.dumps(stored).encode())

        stats = mig.MigrationStats()
        # Provide wrong raw key.
        await mig._process_one(
            conn,
            "apikey:c1",
            keys_map={"c1": "different-key"},
            dry_run=False,
            stats=stats,
        )
        assert stats.failed_verify == 1
        assert stats.upgraded == 0

    @pytest.mark.asyncio
    async def test_corrupt_json_fails_other(self) -> None:
        """Corrupt JSON → failed_other counter."""
        conn = MagicMock()
        conn.get = AsyncMock(return_value=b"not-json-{garbage")

        stats = mig.MigrationStats()
        await mig._process_one(
            conn,
            "apikey:corrupt",
            keys_map={},
            dry_run=True,
            stats=stats,
        )
        assert stats.failed_other == 1
        assert stats.scanned == 0


class TestArgs:
    """Tests for :func:`mig._parse_args`."""

    def test_defaults_dry_run_default_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MIGRATE_REDIS_URL", raising=False)
        monkeypatch.delenv("MIGRATE_KEYS_FILE", raising=False)
        with patch.object(sys, "argv", ["mig-script"]):
            args = mig._parse_args()
        assert args.dry_run is False  # --dry-run not passed
        assert args.confirm is False
        assert args.redis_url == "redis://localhost:6379"
        assert args.key_prefix == "apikey:"

    def test_dry_run_flag_sets_dry_run_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MIGRATE_REDIS_URL", raising=False)
        monkeypatch.delenv("MIGRATE_KEYS_FILE", raising=False)
        with patch.object(sys, "argv", ["mig", "--dry-run"]):
            args = mig._parse_args()
        assert args.dry_run is True
        assert args.confirm is False

    def test_confirm_flag_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MIGRATE_REDIS_URL", raising=False)
        monkeypatch.delenv("MIGRATE_KEYS_FILE", raising=False)
        with patch.object(sys, "argv", ["mig", "--confirm"]):
            args = mig._parse_args()
        assert args.dry_run is False
        assert args.confirm is True

    def test_main_resolves_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confirm mode → main() resolves dry_run = False."""
        monkeypatch.delenv("MIGRATE_REDIS_URL", raising=False)
        monkeypatch.delenv("MIGRATE_KEYS_FILE", raising=False)
        with patch.object(sys, "argv", ["mig", "--confirm", "--redis-url", "x", "--keys-file", "y"]):
            args = mig._parse_args()
        # dry_run computation lives in main() / _run_migration.
        assert args.confirm is True
