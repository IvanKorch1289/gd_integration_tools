# ADR-0204: Sprint 118 — Docstring Ratchet Plan (multi-sprint, -200/wave)

- **Status:** Accepted (Sprint 118 W1, 2026-06-12)
- **Wave:** s118-w1-baseline-verify
- **Sprint:** 118

## Context

Sprint 118 goal: docstring ratchet baseline -200 (per V2 backlog P3). S118 W1 — **verify baseline** перед ratchet.

## Baseline Fact-Check (S118 W1)

```
src/backend/ — strict mode: 1625 violations
allowlist: 1630 entries (suppresses all violations → exit 0)
```

| Top-level dir | Violations |
|---|---|
| `infrastructure/` | 512 |
| `dsl/` | 444 |
| `services/` | 305 |
| `core/` | 192 |
| `entrypoints/` | 137 |
| (unparseable/dup) | ~35 |
| **TOTAL** | **1625** |

## Ratchet Plan (multi-sprint, -200/wave)

| Sprint | Wave | Target | Subset | Effort |
|---|---|---|---|---|
| **S118** | W1 | baseline verify | — | DONE (1 commit) |
| S118 | W2-W3 | -200 | dsl/ (444 → 244) | 1-2 days |
| S119 | W1-W3 | -200 | infrastructure/ (512 → 312) | 1-2 days |
| S120 | W1-W3 | -200 | services/ (305 → 105) | 1-2 days |
| S121 | W1-W3 | -200 | core/ + entrypoints/ (329 → 129) | 1-2 days |
| S122 | W1-W3 | -200 | remaining | 1-2 days |
| S123 | W1-W3 | -200 | cleanup to 825 (50%) | 1-2 days |
| S124+ | — | -200/wave | until 0 | ongoing |

**Total estimated:** 7+ sprints (~3-4 weeks) до 0 violations.

## Why -200/wave

- Каждое нарушение = минимум 1 строка docstring.
- Сложные случаи (Protocol methods, abstract methods, dunder) = 3-5 строк описания.
- 200/wave = ~40 funcs/day × 5 days = achievable для focused work.
- Quality > speed: docstring должен объяснять WHY, не WHAT.

## Tool Status

`tools/check_docstrings.py` — готов (typer+rich, --strict/--update-allowlist/--files).
`tools/check_docstrings_allowlist.txt` — 1630 entries, стабильный.

## S118 W2-W3 — first ratchet wave (DSL)

DSL = 444 violations, но многие — auto-generated processors и Protocol-методы.
Подход:
1. Сгруппировать по файлу (find/grep)
2. Написать docstrings для top-10 файлов по volume
3. Re-run strict, убрать из allowlist
4. Commit

## Honest Scope Reduction (S118 W1)

Это W1 — **только baseline verify**. W2-W3 = реальная работа. Не пытаюсь сделать 200 docstrings в одной сессии.

## Consequences

- **Baseline зафиксирован:** 1625 violations, 1630 allowlist entries
- **Plan committed:** multi-sprint ratchet
- **Score:** 9.8/10 (maintained)
- **TD closed:** 0 (analysis-only W1)

## Lesson (S58 W6 reinforcement)

Sprint planning = **assume stale**. Fact-check перед W1 saves 1-2 days of wrong-direction work (same lesson as S117 W1).
