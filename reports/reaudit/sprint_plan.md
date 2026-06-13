# Compact Sprint Plan — Post-S109 (2 sprints, no Sprint 3)

> **Anti-bloat rule (from master prompt):** каждый sprint
> должен закрывать техдолг, не плодить новый. Поэтому строго 2 спринта
> (Sprint 3 = continuous backlog, не отдельный sprint).

---

## Sprint 1 — Architecture & Layer Policy Hardening

**Цель:** закрыть P0 регрессию layer policy (51 NEW violations
+ 200 stale allowlist entries) + завершить D5 B2/B3 (5 model files
в `infrastructure/database/models/` → `core/domain/models/`)
+ обновить allowlist после S107-S109 work.

**Почему не разбит дальше:** Все 3 задачи — один большой
"D5 split-brain closure". Делать отдельно = лишние overhead-коммиты
на refresh linter allowlist. Один спринт = один большой
git-логически-атомарный tech-debt burn-down.

### Список задач

| # | Task | DoD | Estimated LOC |
|---|------|-----|---------------|
| 1.1 | D5 B2 — move `infrastructure/database/models/orders.py` + `orderkinds.py` to `core/domain/models/` with shims (S106 W1 pattern) | Linter violations ↓; 5+ consumers updated; 3 NEW tests | ~300 |
| 1.2 | D5 B3 — move `infrastructure/database/models/files.py` + `workflow_instance.py` + `workflow_event.py` to `core/domain/models/` with shims | Linter violations ↓; consumers updated; 3 NEW tests | ~400 |
| 1.3 | Refresh layer-policy allowlist (`tools/check_layers.py --update-allowlist`) for 200 stale entries (S107-S109 movement) | New allowlist with < 50 entries; all current violations accounted for | ~10 |
| 1.4 | Migrate `extensions/core_entities/*` services + repositories from `infrastructure.*` to `core.*` (canonical locations from 1.1, 1.2) | Linter `--root extensions` → 0 NEW violations | ~150 |
| 1.5 | Migrate `extensions/credit_pipeline` from `infrastructure.*` to `core.*` | Linter `--root extensions` → 0 NEW | ~80 |
| 1.6 | Investigate + fix 15 NEW `services → infrastructure` violations (`tools/check_layers.py --root src/backend/services`) | 0 NEW | ~100 |
| 1.7 | ADR-0196 — D5 B2/B3 closure | docs updated | ~200 |
| 1.8 | Update `tools/check_layers.py` allowlist (`--update-allowlist`) after all migrations | 0 stale, 0 new | ~5 |

### Tech-debt burn-down

- **Layer policy violations:** 51 active + 200 stale → **0**
- **D5 split-brain:** 5 model files still in `infrastructure/` → **0**
- **D5 B2/B3 backlog:** closed
- **Extension safety:** restored (all ext→infrastructure replaced with ext→core)

### Review protocol

After W3 (D5 moves) and W5 (closure):
- W3 review: list of moved files, consumer updates, linter output diff
- W5 review: full linter output, layer-policy ADR, score update

### Definition of Done

- `tools/check_layers.py --root extensions` → **0 NEW**
- `tools/check_layers.py --root src/backend/services` → **0 NEW**
- `tools/check_layers.py --root src/backend/core` → **<50 allowlist**
  (was 200)
- 0 NEW test regressions
- `make lint && make type-check && make test` all green

### Risks

- **Risk:** Move may break extensions if shim not properly maintained.
  **Mitigation:** S106 W1 pattern proven (Risk A models — 6 files,
  23 consumers, 0 NEW regressions). Apply same pattern.
- **Risk:** Allowlist refresh may hide real regressions.
  **Mitigation:** Run linter BEFORE refresh; manually verify the
  200 stale entries correspond to S107-S109 legitimate work, not
  new violations.

### Rollback strategy

- Each D5 move = atomic commit (model + shim + consumers).
- `git revert` per-commit if downstream extension breaks.
- Allowlist refresh = 1 atomic commit; revert if regressions
  found in CI.

---

## Sprint 2 — DSL Completion + DX + Final Polish

**Цель:** Закрыть P2-P3 hotspots — D17 (s3_delete + s3_list),
`lifespan.py` decomposition candidate, `transport/sources.py` review,
ratchet -10 docstrings, TD-004 final closure (29 → 0).

**Почему не разбит дальше:** Все 4 задачи — "polish & close".
Sprint 1 закрывает P0 (blocker), Sprint 2 закрывает P2-P3
(non-blockers). Sprint 3 = "ongoing backlog" — не отдельный sprint.

### Список задач

| # | Task | DoD | Estimated LOC |
|---|------|-----|---------------|
| 2.1 | Add `s3_delete` + `s3_list` DSL methods (D17) | 2 NEW methods in `transport/sources.py` + 4 tests | ~120 |
| 2.2 | `lifespan.py` (718 LOC) → split into per-phase handlers (startup, shutdown, signal) | 3 NEW files (`startup.py`, `shutdown.py`, `signals.py`); `lifespan.py` becomes orchestrator (< 200 LOC); 5 NEW tests | ~600 |
| 2.3 | TD-004 final close — 29 remaining callsites (mixin internals) — add `LEGITIMATE_STDLIB_FILES`-style allowlist to `tools/check_audit_deprecation.py` | Metric: 29 → 0 (allowlist) | ~30 |
| 2.4 | TD-012 docstring ratchet —10 violations | Metric: 1641 → 1631 | ~50 |
| 2.5 | `transport/sources.py` review — if > 600 LOC after s3 additions, split into per-protocol sub-modules | Maintainable, no LOC growth beyond 600 | ~200 |
| 2.6 | ADR-0197 — Sprint 2 closure | docs updated | ~150 |

### Tech-debt burn-down

- **D17 missing DSL methods:** closed
- **`lifespan.py` god-file:** decomposed
- **TD-004:** 29 → 0 (functional closure via allowlist)
- **TD-012:** -10 docstrings
- **`transport/sources.py`:** reviewed

### Review protocol

After W2 (s3 methods) and W5 (closure):
- W2 review: new DSL methods, e2e test, builder method docstrings
- W5 review: full sprint summary, score update, ADR

### Definition of Done

- `s3_delete` + `s3_list` work end-to-end (e2e test with moto/localstack)
- `lifespan.py` < 200 LOC, multi-phase handlers extracted
- `tools/check_audit_deprecation.py --strict` → exit 0
- Docstring allowlist: 1631 entries (was 1641)
- 0 NEW test regressions
- `make lint && make type-check && make test` all green

### Risks

- **Risk:** `lifespan.py` split may break startup ordering
  (FastAPI lifespan context manager).
  **Mitigation:** S106 W1 pattern — extract helper modules FIRST,
  update lifespan.py to call them, keep public API stable. Add
  integration test for full startup/shutdown sequence.
- **Risk:** TD-004 allowlist may hide real new violations.
  **Mitigation:** Document the 29 entries as "mixin internals —
  S106 W5 dual-emit" in code comments + ADR.

### Rollback strategy

- `s3_delete/s3_list` = 1 atomic commit; revert if e2e test fails
- `lifespan.py` split = 1 atomic commit per phase handler
  (startup, shutdown, signals) + final orchestrator commit;
  revert per-commit if integration test fails
- TD-004 allowlist = 1 atomic commit; revert if linter output
  changes unexpectedly

---

## Sprint 3 — NOT CREATED (per anti-bloat rule)

**Rationale:** Sprint 1 + Sprint 2 cover all P0-P2 items + major P3
items. Remaining backlog (Streamlit feature-grouping, control_flow.py
review, slow ratchet burn-down) is **continuous** — not a sprint.
Adding Sprint 3 = 5 commits for "ongoing maintenance" without a
specific value target. **Per master prompt rule "no preparatory
sprints without useful result"** — we don't create it.

The following items remain as **continuous backlog** (handled in
each future sprint's W4 if/when relevant):

- Streamlit feature-grouping
- `dsl/builders/control_flow.py` (416 LOC) review
- Docstring ratchet continuous -10/sprint
- TD-004 mixin-internal allowlist maintenance
