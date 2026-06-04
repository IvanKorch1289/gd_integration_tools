#!/usr/bin/env python3
"""Управление team worktree (K10 Sprint 2 — on-demand creation).

Назначение:
    Sprint 2 V15.3 MVP вводит 10-team параллельную работу через git worktree.
    Вместо предсоздания всех 10 копий (~26GB) — команды создают worktree
    при kickoff своей Wave.

Команды::

    python tools/team_worktree.py create k4        # создать team/04-workflow
    python tools/team_worktree.py list             # список активных
    python tools/team_worktree.py remove k4        # удалить после merge

Конфигурация команд читается из ``.claude/team-ownership.toml``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

OWNERSHIP_PATH = Path(".claude/team-ownership.toml")


def _load_teams() -> dict[str, dict]:
    """Загружает секцию [team.*] из team-ownership.toml."""
    if not OWNERSHIP_PATH.exists():
        print(f"✗ {OWNERSHIP_PATH} not found", file=sys.stderr)
        sys.exit(2)
    data = tomllib.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))
    return data.get("team", {})


def _resolve_team(team_id: str) -> tuple[str, str]:
    """Возвращает (worktree_path, branch_name) по team_id (k1..k10)."""
    teams = _load_teams()
    team_id = team_id.lower().lstrip("k")
    key = f"k{team_id}"
    if key not in teams:
        print(
            f"✗ Команда '{key}' не найдена. Доступно: {sorted(teams)}", file=sys.stderr
        )
        sys.exit(2)
    team_data = teams[key]
    worktree = team_data["worktree"]
    branch_prefix = team_data["git_branch_prefix"]
    return worktree, branch_prefix


def cmd_create(team_id: str) -> int:
    """git worktree add для команды team_id."""
    worktree, branch = _resolve_team(team_id)
    worktree_path = Path(worktree)

    if worktree_path.exists():
        print(f"✓ worktree уже существует: {worktree}")
        return 0

    branch_exists = (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            check=False,
        ).returncode
        == 0
    )

    cmd = ["git", "worktree", "add"]
    if not branch_exists:
        cmd.extend(["-b", branch, str(worktree_path), "master"])
    else:
        cmd.extend([str(worktree_path), branch])

    print(f"Creating worktree: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return result.returncode
    print(f"✓ Worktree created: {worktree_path} (branch: {branch})")
    print(f"  cd {worktree_path} && git status")
    return 0


def cmd_list() -> int:
    """Список активных worktree (включая master)."""
    print("Active git worktrees:")
    result = subprocess.run(
        ["git", "worktree", "list"], check=False, capture_output=True, text=True
    )
    print(result.stdout)

    teams = _load_teams()
    print(f"\nExpected team worktrees (per team-ownership.toml, {len(teams)} teams):")
    for team_id, team_data in sorted(teams.items()):
        wt = team_data["worktree"]
        status = "✓ exists" if Path(wt).exists() else "✗ missing"
        print(f"  {team_id:5s} → {wt:60s} [{status}]")
    return 0


def cmd_remove(team_id: str) -> int:
    """git worktree remove для команды team_id."""
    worktree, branch = _resolve_team(team_id)
    worktree_path = Path(worktree)

    if not worktree_path.exists():
        print(f"✓ worktree не существует, ничего удалять: {worktree}")
        return 0

    print(
        f"⚠ Удаление worktree '{worktree}' (branch={branch}). "
        f"Убедитесь, что изменения замёрджены в master."
    )
    print(f"  Подтвердите запуском вручную: git worktree remove {worktree_path}")
    print(f"  Затем (если ветка тоже не нужна): git branch -d {branch}")
    return 0


def main() -> int:
    """CLI-entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Создать team worktree")
    p_create.add_argument("team", help="ID команды (k1..k10)")

    sub.add_parser("list", help="Список активных worktree")

    p_remove = sub.add_parser("remove", help="Удалить team worktree (manual confirm)")
    p_remove.add_argument("team", help="ID команды (k1..k10)")

    args = parser.parse_args()

    match args.cmd:
        case "create":
            return cmd_create(args.team)
        case "list":
            return cmd_list()
        case "remove":
            return cmd_remove(args.team)
        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
