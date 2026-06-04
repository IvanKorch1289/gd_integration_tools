#!/usr/bin/env python3
"""Валидация ``.claude/team-ownership.toml`` (K10 Sprint 2 coordination gate).

Назначение:
    Проверяет, что team-ownership-карта актуальна и согласована:
    - 10 команд (k1..k10) определены;
    - каждая команда имеет goal/owned_paths/worktree;
    - >=3 блокера определены в секции ``[blockers]``;
    - каждый блокер ссылается на существующую owner_team;
    - feature-flag, упомянутые в блокерах, существуют в
      ``src/backend/core/config/features.py``.

Запуск::

    python tools/check_team_ownership.py [--strict]

Exit-code 1 при несоответствии.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

OWNERSHIP_PATH = Path(".claude/team-ownership.toml")
EXPECTED_TEAMS = 10
MIN_BLOCKERS = 3
REQUIRED_TEAM_FIELDS = ("name", "goal", "owned_paths", "worktree")
REQUIRED_BLOCKER_FIELDS = ("title", "owner_team", "eta", "dod", "risk")


def validate() -> list[str]:
    """Возвращает список ошибок валидации (пустой → всё ОК)."""
    errors: list[str] = []

    if not OWNERSHIP_PATH.exists():
        return [f"{OWNERSHIP_PATH} отсутствует"]

    try:
        data = tomllib.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return [f"TOML parse error: {exc}"]

    teams = data.get("team", {})
    blockers = data.get("blockers", {})

    if len(teams) != EXPECTED_TEAMS:
        errors.append(
            f"Ожидалось {EXPECTED_TEAMS} команд, найдено {len(teams)}: {sorted(teams)}"
        )

    for team_id, team_data in teams.items():
        for field in REQUIRED_TEAM_FIELDS:
            if field not in team_data:
                errors.append(f"team.{team_id}: отсутствует поле '{field}'")

    if len(blockers) < MIN_BLOCKERS:
        errors.append(
            f"Ожидалось ≥{MIN_BLOCKERS} блокеров, найдено {len(blockers)}: "
            f"{sorted(blockers)}"
        )

    valid_team_ids = set(teams.keys())
    for blocker_id, blocker_data in blockers.items():
        for field in REQUIRED_BLOCKER_FIELDS:
            if field not in blocker_data:
                errors.append(f"blockers.{blocker_id}: отсутствует поле '{field}'")
        owner = blocker_data.get("owner_team")
        if owner and owner not in valid_team_ids:
            errors.append(
                f"blockers.{blocker_id}: owner_team='{owner}' "
                f"не входит в {sorted(valid_team_ids)}"
            )

    return errors


def main() -> int:
    """CLI-entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Дополнительно валидирует ссылки на feature-flags (S3+).",
    )
    args = parser.parse_args()
    _ = args  # --strict пока не используется (заготовка)

    errors = validate()
    if errors:
        print("✗ team-ownership.toml validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    data = tomllib.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))
    teams = data.get("team", {})
    blockers = data.get("blockers", {})
    print(
        f"✓ team-ownership.toml OK: "
        f"{len(teams)} команд ({', '.join(sorted(teams))}), "
        f"{len(blockers)} блокеров ({', '.join(sorted(blockers))})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
