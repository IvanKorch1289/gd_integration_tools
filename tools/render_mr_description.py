#!/usr/bin/env python3
"""Генерирует Markdown-описание MR по PROGRESS.md и PHASE_STATUS.yml.

Использование::

    python3 tools/render_mr_description.py > docs/MR_DESCRIPTION.md

Выходной документ содержит:

* сводку по статусу 38 фаз;
* таблицу ADR со ссылками на файлы;
* reviewer-checklist (автоинжект из раздела 5.11 плана);
* ссылки на `docs/phases/PHASE_<ID>.md`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "adr" / "PHASE_STATUS.yml"


def main() -> int:
    if not STATUS.exists():
        print("PHASE_STATUS.yml отсутствует", file=sys.stderr)
        return 1
    data = yaml.safe_load(STATUS.read_text(encoding="utf-8")) or {}
    phases = data.get("phases") or {}
    meta = data.get("meta") or {}
    total = len(phases)
    done = sum(1 for p in phases.values() if p.get("status") == "done")
    in_progress = sum(1 for p in phases.values() if p.get("status") == "in-progress")

    out: list[str] = []
    out.append("# Production Readiness MR\n")
    out.append(f"- Ветка: `{meta.get('branch', '?')}` → `{meta.get('target', '?')}`")
    out.append(f"- Фазы: **{done}/{total} done**, {in_progress} in-progress\n")

    out.append("## Сводка по фазам\n")
    out.append("| ID | Название | Статус | ADR | Depends on |")
    out.append("|---|---|---|---|---|")
    for pid, phase in phases.items():
        adr = ", ".join(phase.get("adr") or []) or "—"
        deps = ", ".join(phase.get("depends_on") or []) or "—"
        out.append(
            f"| {pid} | {phase.get('title', '?')} | {phase.get('status', '?')} | {adr} | {deps} |"
        )

    out.append("\n## Reviewer checklist\n")
    out.append("- [ ] Все 38 фаз `done` в `docs/PROGRESS.md`.")
    out.append("- [ ] Все 15+ ADR на месте в `docs/adr/`.")
    out.append("- [ ] CI job `no-tests-gate` зелёный.")
    out.append("- [ ] CI job `progress-gate` зелёный.")
    out.append("- [ ] CI job `phase-gate` зелёный.")
    out.append("- [ ] CI job `regression-grep` зелёный.")
    out.append("- [ ] CI job `final-verification` зелёный.")
    out.append("- [ ] `creosote` — zero unused deps.")
    out.append("- [ ] Docker smoke зелёный (readiness/liveness/portal).")
    out.append("- [ ] Documentation sanity: все `docs/phases/PHASE_<ID>.md` заполнены.")

    out.append("\n## Артефакты\n")
    out.append("- `docs/PROGRESS.md` — чек-лист 38 фаз.")
    out.append("- `docs/adr/PHASE_STATUS.yml` — машиночитаемый статус.")
    out.append("- `docs/phases/PHASE_<ID>.md` — документация каждой фазы.")
    out.append("- `docs/adr/ADR-NNN-*.md` — архитектурные решения.")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
