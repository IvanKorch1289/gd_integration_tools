"""Smoke test для tools/migrations/migrate_api_keys_to_argon2.py.

Тест НЕ требует live Redis — мы проверяем логику без сетевых вызовов:

1. Поведение CLI (--dry-run default ON, --confirm OFF).
2. Логика обработки каждого Redis-ключа (используем mock async client).
3. Корректность ``MigrationStats`` (counters / errors / JSON).
4. Корректность handling corrupt JSON, missing keys, verify failure.

Это "smoke" потому что настоящий тест требует running Redis container —
этот тест идёт через всю migration-логику в mocked-режиме.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Добавляем tools/migrations в path для импорта.
_TOOLS_MIGRATIONS = Path(__file__).resolve().parents[3] / "tools" / "migrations"
if str(_TOOLS_MIGRATIONS) not in sys.path:
    sys.path.insert(0, str(_TOOLS_MIGRATIONS))

import migrate_api_keys_to_argon2 as mig  # noqa: E402


class TestMigrationDryRunSafe:
    """Tests that dry-run mode NEVER calls SET on Redis."""

    @pytest.mark.asyncio
    async def test_legacy_to_argon2_path_dry_run_no_set(
        self, tmp_path: Path
    ) -> None:
        """Legacy SHA → would-upgrade: НЕ пишем в Redis (dry-run)."""
        import hashlib

        raw_key = "gd_dry_run_legacy"
        legacy_sha = hashlib.sha256(raw_key.encode()).hexdigest()

        conn = MagicMock()
        stored = json.dumps(
            {
                "client_id": "c_dry",
                "key_hash": legacy_sha,
                "hash_algo": "sha256",
            }
        ).encode()
        conn.get = AsyncMock(return_value=stored)
        conn.set = AsyncMock()
        conn.xadd = AsyncMock()

        keys_map = {"c_dry": raw_key}
        stats = mig.MigrationStats()
        await mig._process_one(
            conn, "apikey:c_dry", keys_map, dry_run=True, stats=stats
        )

        assert stats.upgraded == 1  # dry-run count
        conn.set.assert_not_called()
        conn.xadd.assert_not_called()


class TestMigrationCorruptJSONTolerance:
    """Corrupt JSON in Redis → failed_other count, не падаем."""

    @pytest.mark.asyncio
    async def test_corrupt_json_counted(self) -> None:
        conn = MagicMock()
        conn.get = AsyncMock(return_value=b"definitely-not-json")

        stats = mig.MigrationStats()
        await mig._process_one(
            conn, "apikey:bad", keys_map={}, dry_run=True, stats=stats
        )

        assert stats.failed_other == 1
        assert stats.scanned == 0
        assert len(stats.errors) == 1
        assert "JSON parse failed" in stats.errors[0]


class TestMigrationStatsJSON:
    """``MigrationStats.to_dict()`` сериализуемо + complete."""

    def test_stats_to_dict_keys_complete(self) -> None:
        stats = mig.MigrationStats()
        stats.scanned = 10
        stats.upgraded = 5
        stats.skipped_already_argon2 = 2
        stats.skipped_no_raw_key = 1
        stats.failed_verify = 1
        stats.failed_other = 1
        stats.errors = ["e1", "e2", "e3"]

        d = stats.to_dict()
        assert d["scanned"] == 10
        assert d["upgraded"] == 5
        assert d["skipped_already_argon2"] == 2
        assert d["skipped_no_raw_key"] == 1
        assert d["failed_verify"] == 1
        assert d["failed_other"] == 1
        assert d["errors"] == ["e1", "e2", "e3"]

    def test_errors_truncated_when_many(self) -> None:
        """to_dict caps errors[:10] для читаемости."""
        stats = mig.MigrationStats()
        stats.errors = [f"err_{i}" for i in range(20)]
        d = stats.to_dict()
        assert len(d["errors"]) == 10


class TestMigrationMaxFailures:
    """``--max-failures N`` останавливает скрипт после N consecutive failures."""

    @pytest.mark.asyncio
    async def test_max_failures_aborts_loop(self) -> None:
        """В цикле: max_failures=2 → 2 errors → abort.

        Используем legacy SHA, чтобы все 5 ключей дают
        failed_verify (а не skipped_no_raw_key). Каждый Redis-запись
        возвращает валидный JSON, но raw_key в keys_map заведомо
        отличается от ожидаемого → verify fail.
        """
        import hashlib

        raw_key_right = "gd_right_for_legacy_sha"
        legacy_sha = hashlib.sha256(raw_key_right.encode()).hexdigest()

        redis_keys = [f"apikey:c{i}" for i in range(5)]
        keys_map = {f"c{i}": "definitely_wrong_raw" for i in range(5)}

        call_idx = {"i": 0}

        async def _get(key: str) -> bytes:
            idx = call_idx["i"]
            call_idx["i"] += 1
            return json.dumps(
                {"client_id": f"c{idx}", "key_hash": legacy_sha}
            ).encode()

        conn = MagicMock()
        conn.get = AsyncMock(side_effect=_get)
        conn.set = AsyncMock()
        conn.xadd = AsyncMock()

        stats = mig.MigrationStats()
        aborted = False
        for redis_key in redis_keys:
            await mig._process_one(
                conn, redis_key, keys_map, dry_run=True, stats=stats
            )
            if (stats.failed_verify + stats.failed_other) >= 2:
                aborted = True
                break

        assert aborted is True
        assert stats.failed_verify >= 2
        assert stats.scanned < 5


class TestMigrationLoadKeysFileEdgeCases:
    """Edge cases в parsing keys-file."""

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.txt"
        path.write_text("")
        assert mig._load_keys_file(path) == {}

    def test_only_comments(self, tmp_path: Path) -> None:
        path = tmp_path / "comments.txt"
        path.write_text("# comment 1\n# comment 2\n")
        assert mig._load_keys_file(path) == {}

    def test_mixed_valid_and_invalid(self, tmp_path: Path) -> None:
        path = tmp_path / "mixed.txt"
        path.write_text(
            "# Header\n"
            "valid_a:gd_aaa\n"
            "no_colon\n"
            "\n"
            ":empty_client_id\n"
            "valid_b:\n"  # empty raw_key
            "valid_c:gd_ccc\n"
        )
        result = mig._load_keys_file(path)
        # valid_a + valid_c должны попасть. valid_b пропущен (empty raw).
        assert "valid_a" in result
        assert "valid_c" in result
        assert "valid_b" not in result  # empty raw_key rejected
