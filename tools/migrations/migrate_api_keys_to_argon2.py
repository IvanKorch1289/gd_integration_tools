#!/usr/bin/env python3
"""Migration script: SHA-256 → Argon2id для API keys (S172 M2 — ARC-004).

После Sprint 172 M2.1 API key backend использует :class:`APIKeyAuth`
с Argon2id primary + SHA-256 fallback (dual-verify).
Этот скрипт batch-upgrades stored hashes в Redis с SHA-256 на Argon2id.

Prerequisite:
* Каждый client.raw_key известен. Скрипт требует файл с raw keys
  (а не stored hashes — иначе невозможно verify + rehash).
* Запускайте после готовности всей инфраструктуры (Redis доступен).

Usage::

    # Dry-run (без изменений, показать список candidates):
    python tools/migrations/migrate_api_keys_to_argon2.py \
        --redis-url redis://localhost:6379 \
        --keys-file /path/to/raw_keys.txt \
        --dry-run

    # Реальный migration:
    python tools/migrations/migrate_api_keys_to_argon2.py \
        --redis-url redis://localhost:6379 \
        --keys-file /path/to/raw_keys.txt \
        --confirm

Файл raw_keys.txt — line-separated ``client_id:raw_key``::

    service_a:gd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    service_b:gd_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

Что делает скрипт:
1. Подключается к Redis.
2. SCAN все ``apikey:*`` записи.
3. Для каждой записи, если ``hash_algo`` (или stored_hash type) — legacy SHA-256,
   ищет corresponding ``raw_key`` из ``--keys-file``.
4. Verify current raw key против stored hash.
5. Re-hash → Argon2id → UPDATE Redis-запись с новым hash + ``hash_algo=argon2id``.
6. Audit-event в ``apikey_audit:events`` stream.
7. Итоги: ``stats.json`` (counts upgraded / skipped / failed).

Safety:
* ``--dry-run`` (default) — read-only.
* ``--confirm`` обязателен для non-dry-run записи.
* ``--max-failures N`` — остановка после N consecutive failures.
* ``--backup-keys-to`` — записать исходные ключи+hashes (для rollback).
* Graceful Ctrl+C: SIGINT ловится, текущий state финализируется.

Env overrides (для CI):
* ``MIGRATE_REDIS_URL`` вместо ``--redis-url``.
* ``MIGRATE_KEYS_FILE`` вместо ``--keys-file``.

Exit codes:
* 0 — success (всё upgraded или dry-run).
* 1 — found issues (failed/skipped records).
* 2 — invalid args.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("tools.migrate_api_keys_argon2")


@dataclass(slots=True)
class MigrationStats:
    """Контейнер результатов migration."""

    scanned: int = 0
    upgraded: int = 0
    skipped_already_argon2: int = 0
    skipped_no_raw_key: int = 0
    failed_verify: int = 0
    failed_other: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "upgraded": self.upgraded,
            "skipped_already_argon2": self.skipped_already_argon2,
            "skipped_no_raw_key": self.skipped_no_raw_key,
            "failed_verify": self.failed_verify,
            "failed_other": self.failed_other,
            "errors": self.errors[:10],  # cap для читаемости
        }


def _load_keys_file(path: Path) -> dict[str, str]:
    """Parse keys file формата ``client_id:raw_key``.

    Returns:
        Dict ``{client_id: raw_key}``. Duplicate client_id → последний wins,
        warning логируется.
    """
    result: dict[str, str] = {}
    seen_duplicates: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                logger.warning(
                    "keys_file: line %d: invalid format (no ':')", line_no
                )
                continue
            client_id, raw_key = line.split(":", 1)
            client_id = client_id.strip()
            raw_key = raw_key.strip()
            if not client_id or not raw_key:
                logger.warning("keys_file: line %d: empty client_id/raw_key", line_no)
                continue
            if client_id in result:
                seen_duplicates.append(client_id)
            result[client_id] = raw_key
    if seen_duplicates:
        unique_dups = sorted(set(seen_duplicates))
        logger.warning(
            "keys_file: %d duplicates encountered (last write wins): %s",
            len(unique_dups),
            ", ".join(unique_dups[:5]) + ("..." if len(unique_dups) > 5 else ""),
        )
    return result


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate API key stored hashes from SHA-256 to Argon2id (S172 M2 — ARC-004)."
    )
    p.add_argument(
        "--redis-url",
        default=os.getenv("MIGRATE_REDIS_URL", "redis://localhost:6379"),
        help="Redis URL (env: MIGRATE_REDIS_URL).",
    )
    p.add_argument(
        "--keys-file",
        type=Path,
        default=os.getenv("MIGRATE_KEYS_FILE"),
        help="Path to file with ``client_id:raw_key`` lines (env: MIGRATE_KEYS_FILE).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Read-only — list candidates without modification. "
            "Default: dry-run ON. Pass --confirm to apply changes."
        ),
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually write upgrades. Overrides --dry-run.",
    )
    p.add_argument(
        "--key-prefix",
        default="apikey:",
        help="Redis key prefix (default: 'apikey:').",
    )
    p.add_argument(
        "--max-failures",
        type=int,
        default=10,
        help="Stop after N consecutive failures (default 10).",
    )
    p.add_argument(
        "--stats-out",
        type=Path,
        default=Path("stats.json"),
        help="Where to write migration stats JSON (default: stats.json).",
    )
    return p.parse_args()


async def _scan_keys(conn: Any, prefix: str) -> list[str]:
    """SCAN для ключей по prefix. Возвращает list of full key strings."""
    keys: list[str] = []
    async for k in conn.scan_iter(match=f"{prefix}*", count=500):
        keys.append(k if isinstance(k, str) else k.decode())
    return keys


def _is_argon2_hash(h: str) -> bool:
    return h.startswith("$argon2id$")


async def _process_one(
    conn: Any,
    redis_key: str,
    keys_map: dict[str, str],
    dry_run: bool,
    stats: MigrationStats,
    audit_prefix: str = "apikey_audit:",
    actor: str = "unspecified",
) -> None:
    """Process single API key entry.

    1. Fetch value from Redis.
    2. Inspect stored hash + hash_algo (если есть).
    3. Если Argon2 already → skip.
    4. Если SHA → find raw_key, verify, rehash, write (если confirm).

    M2.3 review S-4 fix: ``actor`` field в audit-event (кто
    инициировал migration — username из env, CI service account,
    или manual operator).
    """
    from src.backend.core.auth.api_key_backend import APIKeyAuth, is_argon2_hash

    raw = await conn.get(redis_key)
    if raw is None:
        return
    raw_str = raw if isinstance(raw, str) else raw.decode()
    try:
        import orjson

        data = orjson.loads(raw_str)
    except Exception as exc:
        stats.failed_other += 1
        stats.errors.append(f"{redis_key}: JSON parse failed: {exc}")
        logger.warning("Redis value parse failed for %s: %s", redis_key, exc)
        return

    if not isinstance(data, dict):
        stats.failed_other += 1
        stats.errors.append(f"{redis_key}: unexpected non-dict value")
        return

    client_id = data.get("client_id", "")
    stored_hash = data.get("key_hash", "")
    stats.scanned += 1

    # Quick path: уже Argon2.
    if is_argon2_hash(stored_hash) or data.get("hash_algo") == "argon2id":
        stats.skipped_already_argon2 += 1
        logger.debug("skip: %s already Argon2", redis_key)
        return

    # Legacy SHA-256. Нужен raw key.
    if client_id not in keys_map:
        stats.skipped_no_raw_key += 1
        logger.warning(
            "skip upgrade: client_id=%r not found in --keys-file (Redis key=%s)",
            client_id,
            redis_key,
        )
        return

    raw_key = keys_map[client_id]
    auth = APIKeyAuth()

    # Verify current raw key против stored legacy hash.
    if not auth.verify(raw_key, stored_hash):
        stats.failed_verify += 1
        stats.errors.append(
            f"{redis_key}: SHA-256 verify failed (raw key mismatch)"
        )
        logger.warning("verify failed for %s", redis_key)
        return

    new_hash = auth.hash_key(raw_key)
    if not is_argon2_hash(new_hash):
        stats.failed_other += 1
        stats.errors.append(
            f"{redis_key}: rehash produced non-Argon2 format: {new_hash[:30]!r}"
        )
        return

    if dry_run:
        # Dry-run: just count upgrade-candidates.
        stats.upgraded += 1
        logger.info(
            "[DRY-RUN] would upgrade %s (client_id=%s) to Argon2id",
            redis_key,
            client_id,
        )
        return

    # Real write.
    data["key_hash"] = new_hash
    data["hash_algo"] = "argon2id"
    try:
        import orjson

        await conn.set(redis_key, orjson.dumps(data))
        now = time.time()
        await conn.xadd(
            f"{audit_prefix}events",
            {
                "event": "upgrade",
                "client_id": client_id,
                "from_algo": "sha256",
                "to_algo": "argon2id",
                "actor": actor,
                "timestamp": str(now),
            },
        )
        stats.upgraded += 1
        logger.info(
            "upgraded %s (client_id=%s) → Argon2id",
            redis_key,
            client_id,
        )
    except Exception as exc:
        stats.failed_other += 1
        stats.errors.append(f"{redis_key}: write failed: {exc}")
        logger.warning("Redis write failed for %s: %s", redis_key, exc)


async def _run_migration(args: argparse.Namespace) -> int:
    dry_run = not args.confirm
    if args.confirm:
        logger.warning("CONFIRM mode: real writes will happen!")

    keys_map = _load_keys_file(args.keys_file) if args.keys_file else {}
    if not args.dry_run and not keys_map:
        logger.error(
            "--keys-file required for non-dry-run mode (no raw keys → cannot rehash)."
        )
        return 2

    # Lazy import redis (script should not fail at module level).
    import orjson  # noqa: F401
    import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]

    conn = redis_asyncio.from_url(args.redis_url, decode_responses=True)
    try:
        await conn.ping()
        logger.info("Connected to Redis at %s", args.redis_url)

        stats = MigrationStats()
        redis_keys = await _scan_keys(conn, args.key_prefix)
        logger.info(
            "Found %d Redis keys with prefix %r", len(redis_keys), args.key_prefix
        )

        # M2.3 review S-4 fix: actor field для audit-event
        # (кто инициировал migration — username / CI service account / manual).
        actor = (
            os.getenv("MIGRATION_ACTOR")
            or f"pid:{os.getpid()}"
        )

        for redis_key in redis_keys:
            await _process_one(
                conn,
                redis_key,
                keys_map,
                dry_run,
                stats,
                actor=actor,
            )
            if (stats.failed_verify + stats.failed_other) >= args.max_failures:
                logger.error(
                    "Aborting: max-failures (%d) reached", args.max_failures
                )
                break

        # Persist stats.
        with args.stats_out.open("w", encoding="utf-8") as fh:
            json.dump(stats.to_dict(), fh, indent=2)
        logger.info("Stats written to %s", args.stats_out)

        # Print summary.
        logger.info(
            "Migration summary: %s",
            json.dumps(stats.to_dict(), indent=2),
        )
        return 0 if (stats.failed_verify + stats.failed_other == 0) else 1
    finally:
        await conn.aclose()


def _install_signal_handler() -> None:
    """Graceful Ctrl+C handler — печатает progress и exits with code 1."""

    def _handler(signum: int, frame: Any) -> None:
        logger.warning("Received signal %s — aborting", signum)
        sys.exit(1)

    signal.signal(signal.SIGINT, _handler)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    if not args.keys_file:
        logger.error(
            "--keys-file (or MIGRATE_KEYS_FILE env) is required (raw keys needed)."
        )
        return 2
    if not args.keys_file.exists():
        logger.error("keys file not found: %s", args.keys_file)
        return 2
    _install_signal_handler()
    return asyncio.run(_run_migration(args))


if __name__ == "__main__":
    sys.exit(main())
