#!/usr/bin/env python3
"""Pre-commit commit-msg hook.

Парсит commit-message формата ``[phase:<ID>] <summary>`` и обновляет:

* ``docs/PROGRESS.md`` — статус строки фазы переводится в ``in-progress``
  (если ранее ``planned``) или остаётся ``done`` (если уже закрыта).
* ``docs/adr/PHASE_STATUS.yml`` — синхронно обновляется ``status``,
  ``commit`` (= HEAD будет проставлен после коммита post-commit-ом),
  ``started_at`` (если впервые).

Если commit-msg не содержит префикса ``[phase:<ID>]`` — hook пропускается без
ошибки (валидацию формата делает ``tools/check_phase_commit.py``).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "docs" / "PROGRESS.md"
STATUS = ROOT / "docs" / "adr" / "PHASE_STATUS.yml"

PHASE_RE = re.compile(r"^\[phase:([A-Z]+(?:-[A-Z]+)?\d+[a-z]?)\]")


def read_commit_msg(path: Path) -> str:
    return path.read_text(encoding="utf-8").splitlines()[0] if path.exists() else ""


def extract_phase(msg: str) -> str | None:
    m = PHASE_RE.match(msg.strip())
    return m.group(1) if m else None


def update_progress_md(phase_id: str) -> None:
    if not PROGRESS.exists():
        return
    text = PROGRESS.read_text(encoding="utf-8")
    pat = re.compile(
        rf"^- \[([ x])\] {re.escape(phase_id)} (.+?) — статус: (\S+) — commit: (\S+) — ADR: (.+)$",
        re.MULTILINE,
    )

    def _sub(m: re.Match[str]) -> str:
        marker, title, status, commit, adr = m.groups()
        if status == "planned":
            status = "in-progress"
        return f"- [{marker}] {phase_id} {title} — статус: {status} — commit: {commit} — ADR: {adr}"

    new_text = pat.sub(_sub, text)
    if new_text != text:
        PROGRESS.write_text(new_text, encoding="utf-8")


def update_status_yml(phase_id: str) -> None:
    if not STATUS.exists():
        return
    data = yaml.safe_load(STATUS.read_text(encoding="utf-8")) or {}
    phases = data.setdefault("phases", {})
    if phase_id not in phases:
        return
    phase = phases[phase_id]
    if phase.get("status") == "planned":
        phase["status"] = "in-progress"
        phase["started_at"] = datetime.now(timezone.utc).isoformat()
    STATUS.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    msg = read_commit_msg(Path(sys.argv[1]))
    phase = extract_phase(msg)
    if not phase:
        return 0
    update_progress_md(phase)
    update_status_yml(phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
