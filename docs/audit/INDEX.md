# Audit Index — `docs/audit/`

> **Обновлено**: 2026-07-01 (per S177 audit-mode, cycle 38, 32 atomic commits).
> **Принцип**: индекс для navigation по audit-документам. Все ссылки указывают на файлы в `docs/audit/`.

---

## Мастер-документы (Master)

| Документ | Размер | Дата | Назначение |
|---|---|---|---|
| **`AUDIT_2026-07-01.md`** | 30K | 2026-07-01 | **MASTER**: 22-topic full-repo audit synthesis (13 секций A-M). Principal-architect role. Current state, 22-topic analysis, DSL coverage map, deps review, refactoring roadmap references. |
| **`REFACTORING_MASTER_PLAN_2026.md`** | 12K | 2026-07-01 | **MASTER PLAN**: 3-horizon roadmap (Quick wins / Stabilization / Platform evolution), 12-item prioritized backlog, target architecture, critical files, migration risk matrix. |

## Sprint retrospective

| Документ | Размер | Дата | Назначение |
|---|---|---|---|
| **`SPRINT_S177_RETROSPECTIVE.md`** | 18K | 2026-07-01 | S172-S177 retrospective: 32 atomic commits, 6 sprints, 24/24 milestones, 3/12 tech-debt closed retroactively. |

## Deep audits (cycle 36 prehistory)

| Документ | Размер | Дата | Назначение |
|---|---|---|---|
| `DEEP-AUDIT-2026-06-22.md` | 115K | 2026-06-22 | **DEEPEST file-by-file**: 12 major areas, per-file evidence. Most comprehensive baseline. Source of truth for layer-by-layer coverage. |
| `DEEP_AUDIT_REPORT.md` | 24K | 2026-06-24 | Top-level cross-domain synthesis. Architectural, production, agent safety, maintainability scores. |
| `DELTA-AUDIT-2026-06-24.md` | 43K | 2026-06-24 | Delta vs DEEP_AUDIT (changes since previous). |
| `AUDIT_2026-06-30.md` | 32K | 2026-06-30 | ARC backlog initial. 12 items (M1-M12) for sequential milestone execution. |

## Targeted analyses

| Документ | Размер | Назначение |
|---|---|---|
| `ARC-005_LAYER_VIOLATIONS_ANALYSIS.md` | 4.8K | 56 layer violations в `infrastructure_facade.py` (canonical S22 W3 pattern). Multi-sprint refactor scope. |
| `S173-FRONTEND-UI-UX-ANALYSIS.md` | 13K | Frontend (Streamlit only) — UX patterns, pages, observability. |

## Document chronology

| Date | Action |
|---|---|
| 2026-06-22 | `DEEP-AUDIT-2026-06-22.md` (115K) — baseline deep audit |
| 2026-06-24 | `DEEP_AUDIT_REPORT.md` + `DELTA-AUDIT-2026-06-24.md` |
| 2026-06-30 | `AUDIT_2026-06-30.md` — ARC backlog initial |
| 2026-07-01 | `SPRINT_S177_RETROSPECTIVE.md` (18K) — 32-commits synthesis |
| 2026-07-01 | `AUDIT_2026-07-01.md` + `REFACTORING_MASTER_PLAN_2026.md` + `INDEX.md` (current session) |

## How to use

1. **For first read** → start with `AUDIT_2026-07-01.md` (synthesis, 13 sections A-M).
2. **For deep dive** → read `DEEP-AUDIT-2026-06-22.md` (file-by-file).
3. **For refactoring planning** → `REFACTORING_MASTER_PLAN_2026.md` (3 horizons + backlog).
4. **For sprint history** → `SPRINT_S177_RETROSPECTIVE.md` (32 commits).
5. **For layer violations** → `ARC-005_LAYER_VIOLATIONS_ANALYSIS.md`.
6. **For frontend** → `S173-FRONTEND-UI-UX-ANALYSIS.md`.

## Related external docs (outside `docs/audit/`)

- `docs/architecture/architecture/...` — main architecture docs.
- `docs/security/argon2id_migration.md` — M2 ARC-004 migration guide.
- `docs/security/sandbox_backends.md` — M5 ARC-008 backend matrix.
- `docs/ai/token_budget_enforcement.md` — M4 ARC-007 architecture.
- `docs/integration/extension_di_registry.md` — M3 ARC-006 SDK surface.
- `docs/integration/sprint_s177_retrospective.md` (alias to `docs/audit/SPRINT_S177_RETROSPECTIVE.md`).

## References

- `.mimocode/plans/1782802381991-proud-garden.md` — meta-plan (multi-session audit + agent dispatch).
- `MEMORY/cycle31-32-audit-stable.md` — 10 subagents, 4 batches.
- `MEMORY/cycle36-audit-e1-stable.md` — E1 admin auth coverage.
- `MEMORY/cycle37-audit-durable.md` — 16-point executive, layer counts.
- `MEMORY/codebase-inventory.md` — Diataxis docs structure.
- `CLAUDE.md` (41K) + `AGENTS.md` (15K) — project rules.
