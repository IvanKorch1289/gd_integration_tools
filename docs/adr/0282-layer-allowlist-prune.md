# ADR-0282: Layer allowlist multi-sprint prune plan (S34-S39)

> **Status**: PROPOSED (2026-08-27).
> **Method**: phased ratchet с explicit per-phase ADR-фоллоwing.
> **Scope**: long-term architectural hygiene (62 → 0 entries).
> **Date**: 2026-08-27.

## 0. Контекст

`tools/check_layers_allowlist.txt` = **61 entries** (verified `awk -F'\t'`
`NR>6 && NF>=3` | wc -l → 61, 2026-08-27). Каждая entry — documented layer
violation, защищённая explicit `make layers` baseline.

### Распределение по importer layer (verified 2026-08-27)

| Layer | Count |
|-------|-------|
| `core` | 42 (69%) |
| `entrypoints` | 7 (11%) |
| `infrastructure` | 6 (10%) |
| `services` | 5 (8%) |
| `workflows` | 1 (2%) |

### Trend (verified git log baselines)

| Sprint | Entries | Delta |
|--------|---------|-------|
| S38 | 98 | baseline |
| S39 | 93 | −5 |
| S40 | 76→73 | −17 (M5 consolidation) |
| S41 | 65 | −8 |
| S42 | 60 | −5 |
| S34 (current) | 61 | +1 (NS-3 audit cycle, no new violations) |

**Average ratchet**: ~−4 entries/Sprint. Target 0 entries → **S52** (~17 sprints)
если maintain current pace.

## 1. Проблема

Текущий ratchet (~4/Sprint) **слишком медленный** для 0 target. Без formal plan:
- reviewers могут revert \"лишние\" entries (не понимая паттерн)
- layer hygiene остаётся decorative metric (не real safety property)
- новые violations могут накапливаться быстрее чем удаляются

## 2. Рассмотренные варианты

### Вариант A: Status-quo ratchet (~4/Sprint, no formal plan)

**Pros**: zero work, established pattern.
**Cons**: target 0 → S52 (17 sprints); risk of regression без ADR.

**VERDICT**: ❌ Отклонён. Слишком медленно.

### Вариант B: Aggressive prune (10+/Sprint)

**Pros**: быстрее к 0.
**Cons**: HIGH risk (могут сломаться extensions); нет time для proper ADR на
каждый prune; reviewers могут push back.

**VERDICT**: ❌ Отклонён. Risk > benefit.

### Вариант C: Phased plan с explicit per-phase scope (current ADR)

**Pros**: 5-7 entries/Sprint (aggressive enough); explicit ADR scope per phase;
public expectation для reviewers.
**Cons**: больше ADRs требует maintenance.

**VERDICT**: ✅ ADOPT.

## 3. Решение

**3-phase plan** (61 → 0 за 6 sprints):

### Phase A (S34 W2, 1 sprint): Inventory + ADR publish

- Аудит 61 entries с column classification (тип violation: structural /
  consolidation-needed / leftover-from-refactor)
- Identify low-risk candidates (single-import structural patterns)
- Публикация ADR-0282 (этот документ)
- NO entry removal в Phase A — pure inventory + planning

### Phase B (S35-S39, 5 sprints): Aggressive ratchet

- **S35 W1**: 2 entries (estimated: `core/notifications/__init__.py` →
  `infrastructure.notifications.gateway` consolidation)
- **S36 W1**: 3 entries (estimated: 1 structural + 2 consolidation)
- **S37 W1**: 5 entries (estimated: multi-sprint carryover)
- **S38 W1**: 5 entries
- **S39 W1**: 5 entries

**Target end-of-Phase-B**: 61 → 41 entries (−20 за 5 sprints).

**Per-prune** workflow:
1. `grep -rn "<violation_pattern>" src/ | head -5` — find all callers
2. Per entry: добавить в `core.api` re-export (NS-3 cycle 32 pattern) ИЛИ
   inline import (small cases)
3. Regression test: расширить `test_no_frontend_facade_regression` analog
4. Commit + ADR update (link к этому ADR)
5. Verify `make layers` → 0 NEW violations

### Phase C (S40-S49, multi-sprint): Structural migrations

- **frontend_facade.py** → dsl_portal (entry #40): 14 файлов frontend
  мигрированы на `core.api` (1-2 файла/Sprint × 8 sprints)
- **mcp_server/tools_*.py** → dsl (3 entries): MCP tools = DSL bridge by
  design → требует capability-gate migration (отдельный ADR, S41+)
- **bridge.py** files (consolidation candidates): `core/notifications/`,
  `infrastructure/database/migrations/env.py` → S45-S49 inline consolidation

**Target end-of-Phase-C**: 41 → 0 entries (S49-S50).

## 4. Consequences

### Positive
- ✅ Public commitment: target 61 → 0 за ~16 sprints (S50)
- ✅ Reviewer clarity: каждый prune имеет explicit scope в per-cycle commit
- ✅ Phase B aggressive ratchet (−4 → −5/Sprint) компенсирует возможные
  накопления violations
- ✅ Phase C defer сложных structural migrations до ADR-ready состояния

### Negative
- (−) 5-7 entries/Sprint prune rate — может всплыть test-isolation flakiness
  при aggressive migration
- (−) Phase C может потребовать дополнительных ADRs для каждого bridge
  consolidation
- (−) Без регулярного inventory (Phase A style) — drift возможен

### Neutral
- ADR-0280 (LISTEN/NOTIFY defer) pattern: deferred items documented separately
  в per-sprint retro
- ADR-0281 (Phase C close-out) pattern: 2 symbols per sprint максимум

## 5. Verification (per-Sprint)

```bash
# 1. Allowlist count monotonic decreasing
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# target: S35=59, S36=56, S37=51, S38=46, S39=41

# 2. Each prune has explicit commit message + ADR link
$ git log --oneline --grep "prune" --since="1 month ago" | head -5
# expected: ≥3 prune commits per Sprint

# 3. Layer check stays clean
$ make layers
# expected: 0 NEW violations throughout

# 4. No new layer violations during Sprint
$ git diff --since="1 week ago" -- 'src/' | grep -E "from src.backend" | \
    awk -F'src.' '{print $2}' | awk -F. '{print $1}' | sort -u
# expected: no new core→infra, core→services patterns (allowed-list only)
```

## 6. Related

- `tools/check_layers_allowlist.txt` — baseline (61 entries, 2026-08-27)
- `tools/check_layers.py` — CI gate
- `make layers` — local + CI validation
- `docs/audit/PRINCIPAL_RE_AUDIT_2026-08-27.md` — 22 audit items, 12 archived
- ADR-0281 (HTTP-migration close-out) — Phase C sibling для NS-3 architecture
- ADR-0280 (LISTEN/NOTIFY defer) — pattern для deferred items documentation
