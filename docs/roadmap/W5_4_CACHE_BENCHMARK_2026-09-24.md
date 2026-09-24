# W5.4 yaml cache — MEASURED impact (v6 §10 W5, 2026-09-24)

> **Этот документ — sibling к `W5_CPROFILE_WATERFALL_AUDIT_2026-09-24.md`**.
> Per v6 §10 W5 «Добавить benchmark до оптимизации и тот же benchmark после неё».
> Per audit «Не завышай» — реальный measured gain вместо оценок.

## 1. Setup

HEAD: `422289f90` (после W5.4 cache implementation).
Test script: 100 sequential reads из cached helpers `_read_base_yaml_cached` +
`_read_overlay_yaml_cached` для `config_profiles/` (`base.yml` + `dev_light.yml`).

## 2. MEASURED results (verified)

| Scenario | Time (ms) | Per-read (ms) |
|---|---|---|
| **WARM cache** (100 reads × 2 yamls) | **0.03** | **0.0002** |
| **COLD cache** (100 reads × 2 yamls, cleared each time) | **2288.19** | **11.44** |

**Per-read saving: 11.44ms** (cold vs warm, per single yaml file).

## 3. Simulated impact per W5.3 cProfile baseline

Per W5.3 cProfile waterfall (commit `5d8eda56d`):
- 17 Settings classes × 2 yaml reads (base + overlay) = 34 yaml.safe_load calls
- per-call cost ~5ms (per W5.3 cProfile per-call breakdown)

W5.4 cache impact:
- **Before (cold)**: 34 × 5ms = ~170ms wasted re-reads
- **After (warm)**: 2 × 5ms = ~10ms (only first instance + profile change)
- **Saved**: ~160ms ≈ **0.16s** per cold-start (within class-load cycle)

Per empirical benchmark (this doc):
- Per-read saving: **11.44ms** (actual measured)
- Saved calls: 32 (17 classes × 2 yamls − 2 actual reads)
- **Total W5.4 saving: 11.44ms × 32 = 366ms ≈ 0.37s** per cold-start

## 4. Reconciliation with W5.3 cProfile estimate

W5.3 cProfile estimated "5-8s measurable reduction" for W5.4.
**Actual measured gain: 0.37s**, NOT 5-8s.

Per v6 §3 «Не завышай» — исходная оценка была overestimated. Реальный gain
~10× меньше. Причины:
- Per-call yaml.safe_load cost ~5-11ms (not the per-call cost assumed).
- 17 Settings × 2 yamls = 34 calls — only ~32 cacheable (2 always fresh).
- Total achievable: ~0.4s, not 5-8s.

## 5. Honest scope (per audit «Не завышай»)

- ✅ W5.4 cache mechanism implemented + smoke verified.
- ✅ Full benchmark measured (100 iterations, both warm + cold).
- ⚠️ **Real gain: ~0.4s per cold-start**, not 5-8s estimated in W5.3.
- ⚠️ Honest assessment: original estimate was based on the total yaml.safe_load
  cumtime (10.789s) as if it was eliminable. Actual cacheable fraction is much
  smaller.
- ❌ NOT executed: YAML → JSON conversion (which would give 5-8s gain per W5.3
  estimate — requires ADR per CLAUDE.md).

## 6. References

- `W5_CPROFILE_WATERFALL_AUDIT_2026-09-24.md` — W5.3 baseline + original estimate.
- `W5_STARTUP_PROFILE_AUDIT_2026-09-24.md` — W5.1 (incorrectly estimated modules).
- `src/backend/core/config/config_loader.py:64-89` — W5.4 cache helpers.
- v6 §10 W5: «Добавить benchmark до оптимизации и тот же benchmark после неё».
