#!/usr/bin/env python3
"""G8 doc-accuracy atomic fixer.

Applies 7 atomic fixes via str.replace() (more reliable than hand-crafted
unified-diff). Each fix is a (file, old_text, new_text) tuple.

Usage:
    python deliverables/g8-doc-accuracy/apply.py            # apply all
    python deliverables/g8-doc-accuracy/apply.py --check    # dry-run (verify)
    python deliverables/g8-doc-accuracy/apply.py --fix Q1   # apply only Q1
    python deliverables/g8-doc-accuracy/apply.py --fix Q1,Q3  # multiple

After running with --check, the script will:
  * find all unique matches (exit 1 if any old_text not found)
  * report file-by-file change counts
  * exit 0 if all checks pass

Q5 (actions count) is NOT included — separate decision.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Each fix: (id, file_path, old_text, new_text)
FIXES: list[tuple[str, Path, str, str]] = [
    # === Q1.1: AGENTS.md:100 ===
    (
        "Q1.1",
        REPO / "AGENTS.md",
        "2. `PLAN.md` (V22) — текущий roadmap и архитектурные решения;",
        "2. `docs/roadmap/FINAL_REPORT.md` + `docs/roadmap/PROD_READINESS_GAPS.md` — текущий roadmap и архитектурные решения;",
    ),
    # === Q1.2: AGENTS.md:289 ===
    (
        "Q1.2",
        REPO / "AGENTS.md",
        "с `PLAN.md` V22 FINAL и является source of truth для проекта.",
        "с `docs/roadmap/FINAL_REPORT.md` (V22 final, prod-readiness v8) и является source of truth для проекта.",
    ),
    # === Q2.1: plan-execute/SKILL.md:18 ===
    (
        "Q2.1",
        REPO / ".claude/skills/plan-execute/SKILL.md",
        "   - `graphify-out/wiki/index.md` при наличии",
        "   - `graphify-out/wiki/index.md` (если есть; fallback: `graphify-out/GRAPH_REPORT.md`)",
    ),
    # === Q2.2: docs-navigator.md:12 ===
    (
        "Q2.2",
        REPO / ".claude/agents/docs-navigator.md",
        "1. `graphify-out/wiki/index.md`",
        "1. `graphify-out/wiki/index.md` (если существует; fallback: `graphify-out/GRAPH_REPORT.md`)",
    ),
    # === Q3.1: DECISIONS.md:327 ===
    (
        "Q3.1",
        REPO / ".claude/DECISIONS.md",
        "Источник: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` (Hermes Agent ultrathink, 10 L1–L10 субагентов). После Sprint 20 (`v1.0.0-production`) запускается post-production backlog S21-S23 (PLAN.md V22.2 FINAL §4) для закрытия 28 нерешённых GAP-пунктов. 4 новых ADR (ADR-NEW-12..15) — backbone S21/S23.",
        "Источник: `docs/architecture/repository-navigation-audit.md` + `docs/roadmap/PROD_READINESS_GAPS.md` (DEEP-RESEARCH Hermes Agent, 10 L1–L10 субагентов, 2026-05-20; исходный gap-analysis/ каталог удалён в ходе G8). После Sprint 20 (`v1.0.0-production`) запускается post-production backlog S21-S23 для закрытия 28 нерешённых GAP-пунктов. 4 новых ADR (ADR-NEW-12..15) — backbone S21/S23.",
    ),
    # === Q3.2: DECISIONS.md:475 ===
    (
        "Q3.2",
        REPO / ".claude/DECISIONS.md",
        "**Wave**: `[wave:s24/w1-presidio-ru-ner]`. Источник: gap-analysis/AI-GAP-ANALYSIS-2026-05-22 P0-1 Зона 7.",
        "**Wave**: `[wave:s24/w1-presidio-ru-ner]`. Источник: `docs/roadmap/PROD_READINESS_GAPS.md` (AI-GAP-ANALYSIS 2026-05-22, P0-1 Зона 7).",
    ),
    # === Q3.3: DECISIONS.md:493 ===
    (
        "Q3.3",
        REPO / ".claude/DECISIONS.md",
        "**Wave**: `[wave:s24/w2-nemo-llamaguard]`. Источник: gap-analysis/AI-GAP-ANALYSIS-2026-05-22 P0-2 Зона 8.",
        "**Wave**: `[wave:s24/w2-nemo-llamaguard]`. Источник: `docs/roadmap/PROD_READINESS_GAPS.md` (AI-GAP-ANALYSIS 2026-05-22, P0-2 Зона 8).",
    ),
    # === Q3.4: DECISIONS.md:512 ===
    (
        "Q3.4",
        REPO / ".claude/DECISIONS.md",
        "**Wave**: `[wave:s24/w3-memory-persistence]`. Источник: gap-analysis/AI-GAP-ANALYSIS-2026-05-22 P0-3 Зона 2.",
        "**Wave**: `[wave:s24/w3-memory-persistence]`. Источник: `docs/roadmap/PROD_READINESS_GAPS.md` (AI-GAP-ANALYSIS 2026-05-22, P0-3 Зона 2).",
    ),
    # === Q3.5: DECISIONS.md:608 ===
    (
        "Q3.5",
        REPO / ".claude/DECISIONS.md",
        "Источник: GAP-анализ V2 (`gap-analysis/GAP-ANALYSIS-V2-gd_integration_tools-2026-05-21.md`).",
        "Источник: GAP-анализ V2 (`docs/roadmap/PROD_READINESS_GAPS.md` V2 + `docs/architecture/repository-navigation-audit.md`).",
    ),
    # === Q3.6: KNOWN_ISSUES.md:490 ===
    (
        "Q3.6",
        REPO / ".claude/KNOWN_ISSUES.md",
        "**Источник**: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` + PLAN.md V22.2 FINAL §4.",
        "**Источник**: `docs/architecture/repository-navigation-audit.md` + `docs/roadmap/PROD_READINESS_GAPS.md` (DEEP-RESEARCH 2026-05-20).",
    ),
    # === Q3.7: KNOWN_ISSUES.md:700 ===
    (
        "Q3.7",
        REPO / ".claude/KNOWN_ISSUES.md",
        "- **Sprint 21-23 (NEW V22.2 FINAL, post-production)** — 28 пунктов из `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` + 5 follow-up. См. секцию «Sprint 21-23 GAP-backlog» ниже.",
        "- **Sprint 21-23 (NEW V22.2 FINAL, post-production)** — 28 пунктов из `docs/roadmap/PROD_READINESS_GAPS.md` (DEEP-RESEARCH 2026-05-20) + 5 follow-up. См. секцию «Sprint 21-23 GAP-backlog» ниже.",
    ),
    # === Q3.8: KNOWN_ISSUES.md:709 ===
    (
        "Q3.8",
        REPO / ".claude/KNOWN_ISSUES.md",
        "Полный отчёт: `gap-analysis/GAP-ANALYSIS-V2-gd_integration_tools-2026-05-21.md`.",
        "Полный отчёт: `docs/roadmap/PROD_READINESS_GAPS.md` (V2) + `docs/architecture/repository-navigation-audit.md`.",
    ),
    # === Q3.9: KNOWN_ISSUES.md:807 ===
    (
        "Q3.9",
        REPO / ".claude/KNOWN_ISSUES.md",
        "**Контекст**. После Sprint 20 (`v1.0.0-production`) начинается post-production backlog S21-S23 (PLAN.md V22.2 FINAL §4) для закрытия 28 нерешённых GAP-пунктов из `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` (668 LOC, Hermes Agent ultrathink, 10 L1–L10 субагентов).",
        "**Контекст**. После Sprint 20 (`v1.0.0-production`) начинается post-production backlog S21-S23 для закрытия 28 нерешённых GAP-пунктов из `docs/roadmap/PROD_READINESS_GAPS.md` (DEEP-RESEARCH 2026-05-20, 668 LOC, Hermes Agent ultrathink, 10 L1–L10 субагентов).",
    ),
    # === Q4: FINAL_REPORT.md:188 ===
    (
        "Q4",
        REPO / "docs/roadmap/FINAL_REPORT.md",
        "| G8 навигация | Дубли каталогов устранены: `docs/workflow/`→`workflows/worker-versioning.md`, `docs/migrations/`→`migration/` (git mv; синхронно с полосой 9cf3429ba); AGENTS.md — актуальная фаза + канонические источники вместо PLAN.md/Sprint-36; ARCHITECTURE.md — дата 2026-09-11 | `8f62c06bb` |",
        "| G8 навигация | Дубли каталогов устранены: `docs/workflows/`→`workflow/worker-versioning.md`, `docs/migrations/`→`migration/{dlq-partition,waf-phase2}.md` (git mv, коммит 9cf3429ba; описание в этом отчёте было инвертировано); AGENTS.md — актуальная фаза + канонические источники вместо `docs/roadmap/PROD_READINESS_GAPS.md`/Sprint-36; ARCHITECTURE.md — дата 2026-09-11 | `8f62c06bb`, `9cf3429ba` |",
    ),
    # === Q6.1: AUDIT_2026-06-30.md:214 ===
    (
        "Q6.1",
        REPO / "docs/audit/AUDIT_2026-06-30.md",
        "- **Recommendations**: документировать HITL pattern в `docs/workflows/HITL.md`.",
        "- **Recommendations**: документировать HITL pattern в `docs/workflow/HITL.md` (отложено — не входит в текущий G8 scope).",
    ),
    # === Q6.2: repository-navigation-audit.md:68 ===
    (
        "Q6.2",
        REPO / "docs/architecture/repository-navigation-audit.md",
        "| `docs/workflow/` vs `docs/workflows/` | workflow/: 1 файл (versioning D172); workflows/: обзор. Nav ведёт только в `workflows/` | **CONSOLIDATE** → `workflows/` |",
        "| `docs/workflow/` vs `docs/workflows/` | workflow/: 1 файл (versioning D172); workflows/: обзор. Nav ведёт только в `workflows/` | **CONSOLIDATE** → `workflows/` (Sprint 47 принял singular; см. 9cf3429ba) |",
    ),
    # === Q6.3: repository-navigation-audit.md:69 ===
    (
        "Q6.3",
        REPO / "docs/architecture/repository-navigation-audit.md",
        "| `docs/migration/` vs `docs/migrations/` | Два документа об одном WAF Phase-2 (`waf-phase-2.md` vs `waf-phase2.md`). Nav — `migration/` | **CONSOLIDATE** |",
        "| `docs/migration/` vs `docs/migrations/` | Два документа об одном WAF Phase-2 (`waf-phase-2.md` vs `waf-phase2.md`). Nav — `migration/` | **CONSOLIDATE** (Sprint 47 принял singular; см. 9cf3429ba) |",
    ),
    # === Q6.4: sprint-171-summary.md:43 ===
    (
        "Q6.4",
        REPO / "docs/sprints/sprint-171-summary.md",
        "- `docs/workflows/worker-versioning.md` (D172)",
        "- `docs/workflow/worker-versioning.md` (D172)",
    ),
    # === Q7.1: waf-phase-2.md end ===
    (
        "Q7.1",
        REPO / "docs/migration/waf-phase-2.md",
        "* PLAN.md V19.1 §S9 K1 W3",
        "* [WAF Phase-2 Migration Guide](waf-phase2.md) — overview, rollback, team ownership\n* `docs/roadmap/PROD_READINESS_GAPS.md` V19.1 §S9 K1 W3",
    ),
    # === Q7.2: waf-phase2.md start (insert after the blockquote, before Status) ===
    (
        "Q7.2",
        REPO / "docs/migration/waf-phase2.md",
        "> Аудитория: команды К2–К5, plugin authors, integration owners.\n\n## Status",
        "> Аудитория: команды К2–К5, plugin authors, integration owners.\n\n> **Per-callsite recipe**: см. [waf-phase-2.md](waf-phase-2.md) — пошаговая\n> миграция одного callsite (Шаг 1-6).\n\n## Status",
    ),
    # === Q8: AGENTS.md — sprint numbering map (insert after «## Текущая фаза» header) ===
    (
        "Q8",
        REPO / "AGENTS.md",
        "## Текущая фаза (Sprint 171+ / B-series 2026-07-28)\n\n### Аудит (завершён 2026-07-28)",
        "## Текущая фаза (Sprint 171+ / B-series 2026-07-28)\n\n### Sprint numbering map\n\n| Обозначение | Что это | Период |\n|---|---|---|\n| Sprint 35 | SBOM+cosign/OWASP ZAP/chaos/hypothesis/pip-audit | 2026-07-31 → 2026-08-18 |\n| Sprint 36 | Production Readiness (90%+) | 2026-08-18 → 2026-08-31 |\n| Sprint 170+ / Sprint 171 | audit-waves M5/M6/M6.1/M7 (middleware, RPA, settings, integration) | 2026-08-25 → 2026-09-11 |\n| B-series (B1..B7) | post-2026-07-28 hygiene (pre-existing commits, docstring gate, mkdocs, etc.) | 2026-09-... |\n| FW7-series (FW7.1..FW7.83) | docstring ratchet (commit-range 360a57e6b..647b081be) | 2026-09-... |\n\n### Аудит (завершён 2026-07-28)",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="G8 doc-accuracy atomic fixer")
    parser.add_argument("--check", action="store_true", help="dry-run, no writes")
    parser.add_argument("--fix", type=str, help="comma-separated fix IDs (e.g. Q1,Q3.5)")
    args = parser.parse_args()

    selected: list[tuple[str, Path, str, str]] = FIXES
    if args.fix:
        wanted = {x.strip() for x in args.fix.split(",")}
        selected = [f for f in FIXES if f[0] in wanted]
        if not selected:
            print(f"No fixes matched: {args.fix}", file=sys.stderr)
            return 1

    # Group by file
    by_file: dict[Path, list[tuple[str, str, str]]] = {}
    for fix_id, path, old, new in selected:
        by_file.setdefault(path, []).append((fix_id, old, new))

    errors: list[str] = []
    files_changed: dict[Path, int] = {}

    for path, fixes in by_file.items():
        if not path.exists():
            errors.append(f"{path}: file not found")
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        applied = 0
        for fix_id, old, new in fixes:
            count = text.count(old)
            if count == 0:
                errors.append(f"[{fix_id}] {path.name}: old_text not found (drift?)")
                continue
            if count > 1:
                errors.append(f"[{fix_id}] {path.name}: old_text matches {count} times (not unique)")
                continue
            text = text.replace(old, new, 1)
            applied += 1
        if applied > 0 and not args.check:
            path.write_text(text, encoding="utf-8")
        files_changed[path] = applied

    # Report
    print("=" * 60)
    print(f"G8 doc-accuracy {'CHECK' if args.check else 'APPLY'}")
    print("=" * 60)
    total = 0
    for path, count in files_changed.items():
        rel = path.relative_to(REPO)
        print(f"  {count:>2} fix(es)  {rel}")
        total += count
    print("-" * 60)
    print(f"  Total: {total} fix(es) across {len(files_changed)} file(s)")
    if args.check:
        print(f"  Mode:   dry-run (no writes)")
    else:
        print(f"  Mode:   APPLIED")
    if errors:
        print()
        print("ERRORS:")
        for e in errors:
            print(f"  ! {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
