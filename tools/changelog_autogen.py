"""Changelog / release-notes generator from git wave-tags (Wave s19/k5-w4-quick-wins-pack).

Reads git log for [wave:sXX/...] tags, groups commits by sprint/team,
and formats as release notes.

Запуск:
    uv run python tools/changelog_autogen.py
    uv run python tools/changelog_autogen.py --from v0.1.0 --to v0.2.0
    uv run python tools/changelog_autogen.py --output dist/release-notes.md
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]


class Commit(NamedTuple):
    sha: str
    message: str
    author: str
    wave_tag: str | None


_WAVE_RE = re.compile(r"\[wave:([^\]]+)\]")
_CONV_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
    r"(?:\([^\)]+\))?:(.+)"
)


def _parse_git_log(from_ref: str | None = None, to_ref: str = "HEAD") -> list[Commit]:
    """Parse git log for wave-tagged commits."""
    import subprocess

    cmd = [
        "git", "log", "--format=%H|%s|%an",
    ]
    if from_ref:
        cmd.append(f"{from_ref}..{to_ref}")
    else:
        cmd.append(to_ref)

    try:
        result = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as exc:
        print(f"FAIL: git log failed: {exc.stderr}", file=sys.stderr)
        return []

    commits: list[Commit] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, message, author = parts
        wave_match = _WAVE_RE.search(message)
        wave_tag = wave_match.group(1) if wave_match else None
        commits.append(Commit(sha=sha, message=message, author=author, wave_tag=wave_tag))
    return commits


def _group_by_wave(commits: list[Commit]) -> dict[str, list[Commit]]:
    """Group commits by wave tag."""
    grouped: dict[str, list[Commit]] = {}
    for commit in commits:
        key = commit.wave_tag or "untagged"
        grouped.setdefault(key, []).append(commit)
    return grouped


def _format_commit(commit: Commit) -> str:
    """Format a single commit line."""
    m = _CONV_RE.match(commit.message)
    if m:
        prefix = m.group(1)
        desc = m.group(2).strip()
    else:
        prefix = "misc"
        desc = commit.message
    short_sha = commit.sha[:8]
    return f"  - [{short_sha}] {prefix}: {desc}"


def main(
    from_ref: str | None = None,
    to_ref: str = "HEAD",
    output: Path | None = None,
) -> int:
    commits = _parse_git_log(from_ref, to_ref)
    if not commits:
        msg = "No commits found"
        if output:
            output.write_text(f"# Release Notes\n\n{msg}\n", encoding="utf-8")
        print(msg)
        return 0 if output else 1

    grouped = _group_by_wave(commits)
    today = date.today().isoformat()

    lines: list[str] = [
        f"# Release Notes — {today}",
        "",
        f"Total commits: {len(commits)}",
        "",
    ]

    for wave_tag, wave_commits in sorted(grouped.items()):
        lines.append(f"## [{wave_tag}]")
        lines.append("")
        for commit in wave_commits:
            lines.append(_format_commit(commit))
        lines.append("")

    content = "\n".join(lines) + "\n"

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"OK: release notes written to {output}")
    else:
        print(content)

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate release notes from wave-tags")
    parser.add_argument(
        "--from", dest="from_ref", default=None,
        help="Start git ref (exclusive). If not given, uses all commits."
    )
    parser.add_argument(
        "--to", dest="to_ref", default="HEAD",
        help="End git ref (inclusive). Default: HEAD."
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output file (default: stdout)"
    )
    args = parser.parse_args()
    sys.exit(main(args.from_ref, args.to_ref, args.output))
