# ADR-0190: Sprint 105 Closure

**Date:** 2026-06-13
**Status:** ACCEPTED
**Sprint:** S105 (4 waves, 4 atomic commits)
**Author:** Autonomous cycle (S105 W1-W3 subagent dispatch + W4-W5 self)

---

## Context

S105 планировал 5 waves: W1 D5 plan, W2 audit soft-deprecate, W3 Temporal
Schedule real, W4 docstring ratchet -20, W5 closure. Sprint выполнен через
parallel subagent dispatch (user выбрал "Вариант А" — 3 subagent'а в
параллель + S104 W4+W5 я сам последовательно).

**Subagent outcomes:**
- Task 1 (D5 plan): 90% готово, subagent исчерпал max_iterations на research
  phase. 3 deliverable файла + 1 commit `5d2206c0` (S105 W1).
- Task 2 (Audit migration): STOPPED early. Обнаружен архитектурный
  конфликт 2 несовместимых паттернов (DI callback vs service-locator).
  Subagent выбрал Path B (soft deprecation) + 1 commit `740f5e02` (S105 W2).
- Task 3 (Temporal Schedule): TIMEOUT 600s. Real implementation выполнена
  мной последовательно + 1 commit `9298d1c7` (S105 W3).

---

## Decision

S105 = 4 atomic commits (W1-W3) + W4 verification + W5 closure.

**S105 W4 — ratchet verification (no work).** После S105 W2-W3 baseline
allowlist = 1636, current = 1636, NEW = 0, stale = 0. Ratchet fully
caught up до S105. Закрытие = verification-only commit.

**S105 W5 — closure ADR (этот документ) + CHANGELOG update.**

---

## Consequences

### Positive

- D5 plan: детальный roadmap B1/B2/B3 с measured numbers, 5 resolved
  OPEN_QUESTIONS, 9-sprint timeline до S106 W5.
- Audit: soft-deprecation gate wired (CI-runnable, exit 1 on regression),
  measured 77 callsites, 22 files. Migration guide с paths A/B/C/D.
- D9 Temporal: real implementation заменила S18 W0 stub. APScheduler +
  Temporal backends теперь оба работают. 50/50 scheduler tests pass.
- Ratchet healthy: 0 regressions, 0 stale, baseline stable.
- All subagent commits atomic, no partial state in tree.

### Negative

- D5 model move — 41 violations в extensions остаются (real move —
  multi-sprint S106+ W1-W4).
- Audit Path A (per-domain helpers) — не выполнен (deferred S106+ W2).
- Pre-commit hook auto-wire — не выполнен (deferred S106+ W3).

### Neutral

- Score: 9.4 → 9.5 (audit + Temporal).
- TODO backlog: 0 (maintained).
- Cumulative S93-S105: 15 sprints, 70+ atomic commits, 295+ NEW tests.

---

## Backlog (S106+)

| Sprint | Wave | Scope | Risk |
|--------|------|-------|------|
| **S106 W1** | D5 B1 | 6 Risk A models → `core/domain/models/` + 6 shims | low |
| **S106 W2** | Audit Path A | per-domain helpers в facade, migration of high-traffic callsites | medium |
| **S106 W3** | Pre-commit hook + D5 B2 starter | auto-wire ratchet + `orderkinds.py` move | low+medium |
| **S106 W4** | D5 B2 orders+files | circular MRO, secondary association | medium |
| **S106 W5** | D5 B3 + closure | workflow_instance + workflow_event (native enum), ADR-0191 | high |

---

## Alternatives Considered

### A. Force W4 ratchet -20 by finding/adding 20 docstrings to NEW code

- **Плюсы:** metric improvement.
- **Плюсы:** aligned with prior sprint pattern.
- **Минусы:** contrived — нет genuine NEW violations после S105 W2-W3.
- **Отклонено:** нарушает "honest W1" rule. Ratchet = regression guard,
  не vanity metric.

### B. Skip W4 entirely, jump to W5

- **Плюсы:** 1 commit saved.
- **Минусы:** W4 verification = valuable artifact (proves 0 regressions
  после subagent dispatch).
- **Отклонено:** verification commit полезен для future maintainers.

---

## References

- DEEP-RESEARCH D5, D9, §3.4 (🔴 + 🟡)
- ADR-0187 (S103 closure, linter wired)
- ADR-0188 (D5 plan, sibling ADR)
- `tools/check_audit_deprecation.py` (S105 W2)
- `src/backend/infrastructure/scheduler/temporal_scheduler_backend.py` (S105 W3)
- `docs/migration/d5-models-to-core.md` (S105 W1)
- `docs/migration/audit-emit-deprecation.md` (S105 W2)

**Score 9.5/10 ACHIEVED.** S106 backlog = 5 waves.
