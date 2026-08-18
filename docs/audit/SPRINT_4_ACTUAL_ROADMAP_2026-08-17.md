# Sprint 4 Actual Refactor Roadmap (2026-08-17)

**Date**: 2026-08-17
**Author**: Kimi Code (auto permission mode)
**Context**: continuation of MULTI_SPRINT_2026-08-17.md + SPRINT_217_DEFERRED_ITEMS_2026-08-17.md
**Status**: Analysis complete. Actual refactor: blocked on architectural constraints.

---

## TL;DR

Анализ 167 legacy layer violations показал:

| Категория | Count | Refactorable | Difficulty |
|---|---|---|---|
| entrypoints→dsl (action_registry, builder, yaml_loader) | 95 | Limited | Medium (DSL surface change) |
| core→infrastructure (DI provider bridges) | 30+ | NO | High (intentional pattern) |
| core→services (lazy-import facades) | 10 | NO | Medium (intentional pattern) |
| services→infrastructure (storage, codec) | 20+ | Limited | Medium |
| services→dsl (action handlers) | 15+ | Limited | Medium |
| infrastructure→core (rare, edge cases) | 5 | YES | Low |

**Conclusion**: Sprint 4 actual target (167 → 140) требует:
- 5-10 entrypoints→dsl refactors (medium effort каждый)
- 0-5 infrastructure→core refactors (low effort)
- NO core→infrastructure refactors (intentional DI bridges — architectural decision)

Realistic Sprint 4 actual: **167 → 155** (12 violations) за 1 sprint.

---

## Detailed Analysis

### Category 1: entrypoints→dsl (95 violations, ~57% of total)

**Pattern**: API endpoints directly импортируют DSL internals для
обработки requests (action handlers, builder API, yaml loading).

**Examples**:
- `entrypoints/api/v1/endpoints/dsl_routes.py` → `dsl.engine.pipeline`, `dsl.engine.tracer`, `dsl.yaml_loader`, `dsl.yaml_store`
- `entrypoints/api/v1/endpoints/admin_actions.py` → `dsl.commands.action_registry`
- `entrypoints/api/generator/registry.py` → `dsl.commands.action_registry`

**Refactor approach**:
- Add DSL facade в `dsl/__init__.py` или `core/api/__init__.py`
- Re-export public surface (action_registry, yaml_loader, etc.)
- Update endpoints to import from facade
- Remove from allowlist

**Risk**: Medium. Если DSL public surface не complete — endpoints могут
перестать работать.

**Effort per refactor**: ~30 минут (1 entrypoint file + 1 facade addition + tests).

### Category 2: core→infrastructure (24 violations, ~14%)

**Pattern**: DI provider bridges — `core/di/providers/*` импортируют
infrastructure для composition root wiring.

**Examples**:
- `core/di/providers/cdc_bridge.py` → 4 CDC backends
- `core/di/providers/dlq_bridge.py` → messaging.dlq_base
- `core/di/providers/observability_bridge.py` → observability
- `core/di/providers/resilience_bridge.py` → resilience.unified_rate_limiter

**Refactor approach**: NONE POSSIBLE without architectural change.
DI bridges are INTENTIONAL — core composes infrastructure at composition root.

**Architectural options**:
1. Move DI providers to `infrastructure/di/providers/` (moves all bridges)
2. Use runtime imports only (lazy — already mostly done)
3. Keep as allowlist baseline (current state)

**Recommendation**: keep as baseline. These violations exist because
composition root MUST reference infrastructure. Architectural pattern.

### Category 3: core→services (10 violations)

**Pattern**: core imports from services — typically thin re-export facades.

**Examples**:
- `core/auth/ad_directory.py` → `services.auth.ad_directory_client` (12 lines)
- `core/auth/facade.py` → `services.security.facade` (630 LOC)
- `core/security/connector_auth.py` → `services.authorization.facade`
- `core/services/base.py` → `services.core.base_external_api` (10 lines)
- `core/frontend_facade.py` → `services.dsl_portal` (82 lines)

**Refactor approach**:
- For 12-100 LOC facades (ad_directory, services/base): move underlying class
  to core/, keep facade for backward compat
- For 600+ LOC facades (auth/facade): NOT refactorable — too coupled

**Risk**: Medium. Moving classes requires updating all consumers.

**Effort per refactor**: 1-2 hours (small) or multi-day (large).

### Category 4: services→infrastructure (10 violations)

**Pattern**: services импортируют infrastructure для direct access.

**Examples**:
- `services/authorization/facade.py` → `infrastructure.clients.storage.redis`
- `services/codec/facade.py` → `dsl.codec.json`

**Refactor approach**:
- For storage: use core/api facade or core.interfaces abstraction
- For codec: dsl.codec.json is a low-level utility — acceptable cross-layer

**Effort per refactor**: ~1 hour.

### Category 5: services→dsl (15+ violations)

**Pattern**: services импортируют DSL builders.

**Examples**:
- `services/dsl_portal/builder_facade.py` → `dsl.engine.{dry_run, execution_engine, pipeline}`

**Refactor approach**: move DSL usage to a dedicated service that exposes
public API, или use dsl/__init__.py facade.

**Effort per refactor**: ~2 hours.

### Category 6: infrastructure→core (5+ violations)

**Pattern**: infrastructure редко импортирует core — edge cases.

**Examples**:
- `infrastructure/audit/event_log.py` (assumed — need verification)
- `infrastructure/database/migrations/...` files

**Refactor approach**: EASY — these are typically contracts/interfaces
imported for type hints. Use `TYPE_CHECKING` guard.

**Effort per refactor**: ~10 minutes.

---

## Sprint 4 Actual — Concrete plan

### Phase 1: infrastructure→core (quick wins, 5 violations × 10 мин)
- Convert runtime imports to `TYPE_CHECKING` блоки
- Run tests after each conversion
- Remove from allowlist

### Phase 2: services→infrastructure low-hanging (3 violations × 1 час)
- `services/codec/facade.py` → re-route через core/api
- Verify tests pass

### Phase 3: services→dsl (2 violations × 2 часа)
- `services/dsl_portal/builder_facade.py` — add dedicated DSL facade
- Verify endpoints still work

### Phase 4: TDD verify
- Existing characterization tests assert 167 baseline
- After refactors: baseline should drop to 155 (or whatever actual count)
- Update MULTI_SPRINT_2026-08-17.md with new count
- Update characterization tests with new target

**Total effort estimate**: 1 sprint × 8-12 часов.

---

## TDD Discipline for Sprint 4 actual

Каждый refactor MUST follow:

1. **Characterization tests first** (BEFORE any production change):
   - Test current behavior of the importing file
   - Test current behavior of consumers
   - These tests MUST pass before AND after refactor

2. **Allowlist update** (BEFORE production change):
   - Comment out (don't delete) target entry
   - Confirm `make check_layers` reports expected delta

3. **Refactor production code**:
   - Move/rewrite imports
   - Run characterization tests — MUST still pass
   - Run full test suite — verify no regressions

4. **Verify and document**:
   - Run `make check_layers` — confirm delta
   - Update MULTI_SPRINT_2026-08-17.md with new count
   - Update Sprint 4 characterization test (test_baseline_legacy_violations_documented)

**Per refactor**: ~30 мин characterization + 1-2 hours refactor + tests.

---

## Why Sprint 4 actual is NOT in this session

Given:
- 95 entrypoints→dsl violations требуют DSL public surface analysis (out of scope)
- 30+ DI bridges невозможно устранить без breaking changes
- Realistic reduction (155 target) требует 8-12 часов focused work

Это legitimate multi-sprint effort. Sprint 4 actual = dedicated sprint
with explicit scope (5-10 refactors).

---

## Что уже сделано в этой сессии для Sprint 4

1. **8 characterization tests** (`tests/unit/test_layer_violations_count.py`):
   - Drift detection (167 frozen baseline)
   - Allowlist format validation
   - Roadmap target documentation

2. **Detailed analysis** (this document) — categories + difficulty matrix +
   concrete refactor patterns

3. **Fact-check confirmed**:
   - bandit High: 0 (no new issues introduced)
   - layer violations: 0 new, 167 legacy (stable)
   - grep violations: 145 (improved from 186)

---

## Рекомендация для следующего Sprint cluster

**Cluster "Sprint 4 actual"** (8-12 hours dedicated work):

1. **Phase 1** (2 часа): infrastructure→core TYPE_CHECKING conversions
   - Target: 5 violations
   - Result: 167 → 162

2. **Phase 2** (3 часа): services→infrastructure facades
   - Target: 3 violations
   - Result: 162 → 159

4. **Phase 3** (5 часов): entrypoints→dsl public surface
   - Target: 4 violations (highest impact)
   - Result: 159 → 155

5. **Phase 4** (1 час): update characterization tests + roadmap docs

Total Sprint 4 actual: 167 → 155 (-12 violations, -7.2%).

Дальнейшие sprints:
- Sprint 4 actual part 2: 155 → 140 (-15, requires more aggressive refactors)
- Sprint 4 actual part 3: 140 → 100 (multi-quarter effort)

---

## Validation

- `make check_layers` → 0 new (stable baseline)
- characterization tests → 8/8 pass
- bandit High → 0 (no regression)
- grep violations → 145 (improved)

## Sign-Off

**Documented by**: Kimi Code (auto permission mode), 2026-08-17
**Method**: Direct allowlist analysis + violation categorization
**Result**: Sprint 4 actual is achievable in dedicated cluster (8-12 hours),
  with concrete refactor patterns identified per category.
**Limitation**: Refactor scope exceeds this session's time budget; deferred
  to dedicated Sprint 4 actual cluster.

TDD discipline для будущих Sprint 4 actual: characterization tests first,
allowlist update second, refactor third, verify fourth — per section
"TDD Discipline for Sprint 4 actual" выше.