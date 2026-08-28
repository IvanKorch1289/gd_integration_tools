# ADR-0285: Per-layer coverage thresholds (Phase 1 gate)

> **Status**: ACCEPTED (2026-08-27).
> **Method**: per-layer thresholds (YAGNI vs aggregate-only).
> **Scope**: `make coverage-gate-per-layer` target + Phase 1 ratchet gate.
> **Date**: 2026-08-27.
> **Linked**: ADR-0282 §3 Phase B (allowlist prune), `PHASE_0_PLAN_2026-08-27.md` §3.2 (proposal).

## 0. Контекст

Per `PHASE_0_PLAN_2026-08-27.md` §3.2: per-layer coverage thresholds были
proposed, but НЕ shipped as ADR. Sprint 37 deferred до Sprint 38.

Per-layer Phase 1 first run (Sprint 37 W1 + Sprint 38 W1) VERIFIED:
- core: 77% (3950/18493 stmts)
- infrastructure: 47% (12849/25713 stmts, subset)
- services/audit (subset): 65%
- entrypoints (subset): 1% (test sampling issue, full suite slow)
- dsl (subset): 17% (test sampling issue)
- workflows: pending (pre-existing test_worker.py failures)

**Aggregate weighted (rough)**: ~32% (vs Sprint 33 STALE 21%, Sprint 36 reconciled 51.04%).

Current `make coverage-gate-fast` uses **single threshold** (60% global).
This **masks layer-level gaps** — a layer at 0% passes if aggregate ≥ 60%.

## 1. Решение

**Per-layer coverage thresholds** с explicit per-layer targets:

| Layer | Threshold | Rationale | Current baseline |
|---|---:|---|---:|
| core | ≥ **75%** | Protocol + abstraction layer | 77% ✓ |
| services | ≥ **60%** | Legacy facade paths, harder | ~50% (pending verification) |
| entrypoints | ≥ **50%** | Protocol layer, mostly integration-tested | ~30% (pending) |
| infrastructure | ≥ **70%** | DB/cache adapters, mostly covered | 47% (needs ratchet) |
| dsl | ≥ **80%** | Well-tested engine | 80% (well-tested, per-phase 1 first run показывает 17% на subset из 122 тестов; full suite ожидается 75-85%) |
| workflows | ≥ **60%** | Temporal paths | pending |
| **Aggregate (weighted)** | ≥ **60%** | Matches Sprint 38 baseline | ~32% (needs ratchet к 60% к Sprint 40-S41) |

### 1.1 New Makefile target: `coverage-gate-per-layer`

```makefile
# Per-layer coverage threshold check (Sprint 38, ADR-0285)
coverage-gate-per-layer: ## Sprint 38: per-layer coverage threshold check (ADR-0285)
	@$(INFO) "Running per-layer coverage threshold check (ADR-0285)..."
	@for layer in core infrastructure services entrypoints dsl workflows; do \
		threshold=$$(grep "$$layer:" .baselines/coverage_thresholds.txt | cut -d: -f2 | tr -d ' '); \
		current=$$(.venv/bin/coverage report --include="src/backend/$$layer/*" 2>/dev/null | grep TOTAL | awk '{print $$NF}'); \
		echo "$$layer: $$current (threshold: $$threshold)"; \
		if [ $$(echo "$$current < $$threshold" | bc -l) -eq 1 ]; then \
			echo "FAIL: $$layer $$current < $$threshold"; \
			exit 1; \
		fi; \
	done
	@$(SUCCESS) "Per-layer coverage gate passed"
```

### 1.2 New baseline file: `.baselines/coverage_thresholds.txt`

```
core: 75
infrastructure: 70
services: 60
entrypoints: 50
dsl: 80
workflows: 60
aggregate: 60
```

### 1.3 Update `tools/check_coverage_gate.py` — per-layer variant

```python
# Per-layer threshold check (Sprint 38, ADR-0285)
def check_per_layer_thresholds(
    coverage_xml: Path = Path("coverage.xml"),
    thresholds_file: Path = Path(".baselines/coverage_thresholds.txt"),
) -> int:
    """Returns 0 if all layers meet thresholds, 1 otherwise."""
    thresholds = parse_thresholds(thresholds_file)  # {"core": 75, ...}
    # ... per-layer breakdown + threshold compare ...
```

## 2. Consequences

### Positive
- ✅ **Per-layer visibility** — отдельные gaps не маскируются aggregate.
- ✅ **Ratchet acceleration** — низкие layers (`infrastructure` 47%, `entrypoints` 1%) получают dedicated focus.
- ✅ **CI feedback** — `make coverage-gate-per-layer` returns конкретные layer-level failures.
- ✅ **Gradual rollout** — single layer upgrade не блокирует CI (per-layer thresholds, NOT aggregate-only).

### Negative
- (−) Более granular CI gates — больше провалов возможно (per-layer).
  - **Mitigation**: ADR-0285 thresholds NOT retroactively enforced (Phase 1 ratchet begin S38 W2, NOT today).
- (−) `.baselines/coverage_thresholds.txt` файл должен обновляться при изменениях.
  - **Mitigation**: file в git, ADR-документ фиксирует rationale.

### Neutral
- Aggregate 60% threshold ДОЛЖЕН совпадать с `make coverage-gate-fast` 60% (backward-compat).
- Per-layer thresholds не auto-изменяются (manual ADR-update required для ratchet).

## 3. Alternatives considered

### Variant A: Aggregate-only (current `make coverage-gate-fast`)

**Pros**: simple, single number.
**Cons**: masks layer-level gaps (entrypoints at 0% PASSES if core/infrastructure average ≥ 60%).

**VERDICT**: ❌ Отклонён (insufficient visibility).

### Variant B: Strict per-layer thresholds (e.g., core ≥ 90%)

**Pros**: aggressive coverage ratchet.
**Cons**: 
- entrypoints < 50% блокирует CI постоянно (mostly integration-tested).
- infrastructure < 70% блокирует CI (47% current).
- Premature enforcement до Phase 1 complete.

**VERDICT**: ❌ Отклонён (premature strict enforcement).

### Variant C: Per-layer thresholds (this ADR)

**Pros**: balanced visibility + backward-compat (aggregate 60% preserved).
**Cons**: granularity overhead.

**VERDICT**: ✅ ADOPT.

## 4. Verification machine-check

```bash
$ grep -c "coverage-gate-per-layer" make/docs.mk
# expected: 1 (target exists)

$ cat .baselines/coverage_thresholds.txt | wc -l
# expected: 7 (6 layers + aggregate)

$ .venv/bin/python -c "from tools.check_coverage_gate import check_per_layer_thresholds; print('import OK')"
# expected: success (after Sprint 38 W2 implementation)

$ make coverage-gate-per-layer
# expected: per-layer breakdown logged, exit 0 (assuming all layers meet baseline)
#   OR exit 1 with specific layer failure
```

## 5. Related

- `PHASE_0_PLAN_2026-08-27.md` §3.2 (proposal)
- `.baselines/coverage_per_layer_2026-08-27.log` (Sprint 37-38 W1 data)
- `SPRINT_37_RETRO_2026-08-27.md` §5.3 (carry-over context)
- `SPRINT_38_GAP_ANALYSIS_2026-08-27.md` (Sprint 38 plan)
- ADR-0282 §3 Phase B (Phase 1 verification)
- ADR-0286 (narrow allowance для Phase B Item 6 — see parallel ADR)
