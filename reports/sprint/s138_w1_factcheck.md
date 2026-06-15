# S138 W1 — Pre-flight Factcheck (comprehensive state assessment)

> **Date:** 2026-06-15 (post-S137 W3, sibling massive parallel work)
> **Author:** sprint-execution agent (S138 W1)
> **Result:** COMPREHENSIVE TECH DEBT. State is heavily in-flight (sibling
> WIP). 192+ test failures + 1 layer violation + 1 OPEN TD + 1 PARTIAL
> TD + 2 collection errors. Ponytail: stop here, ask user to define
> scope before W2.

---

## 0. Online verification (cross-check with data)

**Pydantic v2 docs (verified via context7 2026-06-15)**:
- `Field(example=...)` deprecation → use `json_schema_extra={"example": ...}` ✅
- `json_schema_extra` merging: additive across `Annotated[Type, Field(...)]`
- `min_items` → `min_length` (Pydantic v2 standard rename) ✅
- `Field(env=...)` deprecation → use `validation_alias=AliasChoices(...)`
  OR rely on `env_prefix` (our approach: removed redundant `env=` since
  `env_prefix="FS_"` already maps bucket → FS_BUCKET automatically) ✅

**Verdict**: Our S136 W4 Pydantic migration is correct per official Pydantic v2 migration guide.

---

## 1. Test baseline (post-sibling-circuit-breaker-removal, 2026-06-15)

| Directory | Failed | Passed | Errors | Skipped | Warnings |
|---|---|---|---|---|---|
| `tests/unit/dsl/engine/processors/` | 98 | 1374 | 19 | 17 | 17 |
| `tests/unit/dsl/builders/` | 8 | 523 | 0 | 7 | 1 |
| `tests/unit/services/` | 86 | 1421 | 19 | 1 | 43 |
| `tests/unit/core/` | N/A | N/A | **2 collection** | 2 | 2 |
| `tests/unit/infrastructure/` | (running, partial) | — | — | — | — |
| **Combined estimate** | **~192** | **~3318+** | **~38+** | ~27 | ~63 |

Sibling WIP modified 11+ files, deleted 2 (circuit_breaker.py + its test). Test deltas: +36 pass, -13 fail, -23 errors from sibling's circuit_breaker removal (replaced with `purgatory` lib).

---

## 2. Tech debt inventory

### 2.1. CRITICAL (1)
- **Layer violation**: `src/backend/services/io/external_database/facade.py` → `src.backend.infrastructure.database.session_manager` (services→infrastructure forbidden). Sibling W3, uncommitted. Blocks CI.

### 2.2. Test failures (HIGH)
- 98 `tests/unit/dsl/engine/processors/` — mixed root causes (need classification)
- 86 `tests/unit/services/` — likely related to dedupe/redis/store changes
- 8 `tests/unit/dsl/builders/` — mostly saga LRA + format converters
- 19 errors in engine/processors + 19 in services — collection/setup issues
- 2 collection errors in `tests/unit/core/` — likely test file structure issues

### 2.3. Pydantic v2 (DONE, 0 NEW)
- All `Field(example=...)`, `Field(env=...)`, `Field(min_items=...)` migrated (S136 W4)
- ✅ Verified against Pydantic v2 migration docs (context7)

### 2.4. TD register (1 OPEN, 1 PARTIAL, 12 CLOSED)
- 1 OPEN (TD-006: test baseline, 192+ failures)
- 1 PARTIAL (TD-013: Streamlit feature-grouping, deferred S137+)
- 12 CLOSED (sibling + my work)

### 2.5. Documentation/docstring debt
- 1,641 functions without docstrings (per old analysis, may be stale)
- 2 doc-only commits this sprint (S136 W1, S136 W5) — minor progress

### 2.6. Tooling (DONE)
- `tools/check_layers.py` — working, caught 1 NEW violation
- `tools/build_adr_index.py` — 171 ADRs
- `tools/check_test_baseline.py` — known stale (reports 0 but 192 fail)

---

## 3. Multi-sprint plan (post-W1)

Ponytail: **I CANNOT do all of this in one session.** Honest scope:

| Sprint | Scope | Estimate |
|---|---|---|
| S138 | Factcheck (this) + 1 layer violation fix + 2 collection errors | 1 day |
| S139 | 8 builders failures (small, targeted) | 1-2 days |
| S140 | 86 services failures (classification + 1-2 fix commits) | 2-3 days |
| S141 | 98 engine/processors failures (multi-day classification) | 3-5 days |
| S142 | Streamlit TD-013 (6h dedicated, P2) | 1 day |
| S143+ | Docstring coverage, security audit, etc. (backlog) | TBD |

**S138 W2 candidate**: 1 layer violation fix (sibling's external_database facade, but the fix is mine to do as regression).

---

## 4. Online resources cross-checked

- **Pydantic v2** (context7 `/pydantic/pydantic`): ✅ confirmed our migration
- **Pydantic Settings** (context7 `/pydantic/pydantic-settings`): ✅ confirmed `env_prefix` covers redundant `env=`

Not yet checked (potential W2+ work):
- FastStream 0.6+ NATS docs (S106 W4 era — verify current API)
- Purgatory library docs (replaced circuit_breaker)
- aiohttp/httpx CircuitBreakerMiddleware (replacement)
- Ponytail skill: just verified

---

## 5. Self-review

- 5-sec recipe applied (`verify-analysis-claims` skill)
- Online cross-check via context7 Pydantic docs (2026-06-15)
- Sibling WIP identified but not touched (their territory)
- No code changes in W1 (docs only)
- Layer check: 1 NEW violation (sibling, not mine)
- Ponytail: 'Did the lazy factcheck; do NOT do all 192 fixes in one
  session. Ask user to scope S138 W2.'

---

## 6. Refs

- S137 W3: `49395c6` (SagaStep @dataclass)
- S137 W2: `797a7b9d` (PriorityEnqueueProcessor)
- S136 W4: `a425af85` (Pydantic v2 migration)
- Sibling WIP: 11+ files modified, 2 deleted (circuit_breaker)
- TD register: `reports/reaudit/tech_debt_register.md`
- Pydantic v2 docs: context7 verified
- Ponytail skill (active, level full)
- Skill: subagent-driven-development (loaded, for potential W2 dispatch)
- Skill: verify-analysis-claims (loaded, 5-sec recipe applied)
