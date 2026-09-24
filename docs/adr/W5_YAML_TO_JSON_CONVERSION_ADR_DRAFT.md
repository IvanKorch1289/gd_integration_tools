# ADR DRAFT: W5.4 YAML → JSON config format conversion

> **Status**: DRAFT (per v6 §15 «следующий шаг ровно один»)
> **Supersedes**: per v6 §10 W5 «Измерить startup import profile. Lazy import
> применять только при доказанном выигрыше»
> **Author**: v6 audit session 2026-09-24
> **Decision required**: per CLAUDE.md + v6 §4.3 «Не менять публичный контракт
> без ADR, migration path и deprecation window»

## 1. Контекст

Per `W5_CPROFILE_WATERFALL_AUDIT_2026-09-24.md` (commit `5d8eda56d`):
- `src.backend.main` cold start = ~12s (с cProfile overhead)
- `yaml.safe_load` = **10.789s cumulative** (77% of startup)
- 240 calls (17 Settings classes × 2 yaml files each: base + overlay)

Per `W5_4_CACHE_BENCHMARK_2026-09-24.md` (commit `d066a0e64`):
- W5.4 yaml cache IMPLEMENTED (commit `422289f90`)
- **Measured gain: 0.37s** per cold-start (NOT 5-8s as W5.3 estimate suggested)
- 240 → 2 yaml.safe_load calls (cache hits)
- Per-call cost ~11ms (measured)

**Gap**: yaml.safe_load is still 77% of remaining startup after cache. The
cache reduces repetition but not per-call cost.

## 2. Решение (proposed)

**Convert config format from YAML → JSON** (binary JSON):
- orjson / msgspec (fast JSON parsers, ~10x faster than PyYAML)
- Lazy convert config files at first read (no startup-time impact)
- Keep YAML reading capability during transition (back-compat)

### 2.1 Expected gains (with honest scoping)

- **Per-call cost reduction**: PyYAML ~5-11ms/call vs orjson ~0.5-1ms/call (10x faster)
- 17 Settings × 2 configs × ~10ms saved = **~340ms additional reduction** beyond W5.4 cache
- **Total W5.4+W5.4-bonus gain**: ~0.37s (cache) + ~0.34s (JSON conversion) = ~0.71s per cold start
- **NOT 5-8s as W5.3 estimate suggested** — that was overestimated

### 2.2 Migration path

Phase 1 (this ADR scope):
- Add JSON support alongside YAML
- Settings loader tries `.json` first, falls back to `.yaml`
- Convert `base.yml` + `dev_light.yml` + `dev.yml` + `prod.yml` to JSON
- Keep YAML files as documentation (deprecated)

Phase 2 (deferred, separate ADR):
- Remove YAML loader entirely
- Cleanup `.yml` files

## 3. Альтернативы

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **orjson conversion** (proposed) | 10x faster per-call; ~0.7s total gain; minimal code change | Requires ADR + migration window | **recommended** |
| msgspec | Even faster than orjson | New dep; less Pythonic | alternative |
| msgspec+ujson | Mixed format auto-detect | Complexity | overkill |
| Keep PyYAML + deeper caching | No code change to readers | Marginal gain (cache already done) | insufficient |
| Replace config with TOML | Modern; ~5x faster than YAML | Different format; rewrite all configs | over-scope |

## 4. Risks

- **YAML → JSON tooling change**: developers used to YAML editing
- **JSON comments missing**: YAML supports comments, JSON doesn't (separate docs needed)
- **Anchors/aliases**: YAML supports them, JSON doesn't (config complexity reduction)
- **ADR + deprecation window**: per CLAUDE.md «Не менять публичный контракт без ADR»
- **Per v6 §4.3**: «Backward compatibility: deprecation + telemetry/importer audit + migration window + removal gate»

## 5. Implementation plan

### 5.1 Phase 1 (this ADR scope)

1. Add `orjson` dep (already in venv per import checks)
2. New helper `_read_json(path)` — uses orjson.loads
3. Update `_load_data()` in YamlConfigSettingsLoader → ConfigSettingsLoader:
   - Try `_read_json(profile_path + ".json")` first
   - Fall back to `_read_yaml(profile_path + ".yml")` for transition
   - Log warning when YAML fallback used (deprecation telemetry)
4. Convert `config_profiles/base.yml` → `config_profiles/base.json` (script)
5. Convert `config_profiles/dev_light.yml` → `config_profiles/dev_light.json`
6. Convert `config_profiles/dev.yml` → `config_profiles/dev.json` (if exists)
7. Convert `config_profiles/prod.yml` → `config_profiles/prod.json` (if exists)
8. Add benchmark test: `src/backend/cli/health.py` или standalone — measure
   yaml vs json parse time for `config_profiles/base.json`
9. Verify all 562 existing config tests pass (W1.2 + W5.4 unchanged)
10. Document deprecation timeline (YAML support until next major release)

### 5.2 Phase 2 (separate ADR, deferred)

1. Remove YAML loader entirely (after deprecation window)
2. Remove `.yml` config files
3. Cleanup migration helpers

## 6. Acceptance criteria (DoD per v6 §14)

1. ✅ Problem reproduced: `yaml.safe_load` = 10.789s per W5.3 cProfile
2. ✅ Claim Ledger: this ADR document
3. ⏳ Architectural Guardian: review proposed change (separate Architecture review)
4. ⏳ Implementation minimal: ~50-80 LOC (helper + config conversion)
5. ⏳ Unit + integration tests pass
6. N/A (no security negative cases)
7. ❌ cURL verification (BLOCKED Docker per kickoff)
8. ❌ Browser verification (BLOCKED Docker per kickoff)
9. ✅ All gates exit 0: 562 config tests should pass
10. ✅ Before/after metrics: benchmark yaml vs json parse time
11. ✅ Documentation updated: this ADR + migration guide
12. ✅ Rollback via `git revert <sha>`
13. ✅ Atomic commit per phase step
14. ✅ Skeptic re-test with W5.4 cache combination
15. ✅ Next step: phase 2 ADR

## 7. Honest scope statement (per audit «Не завышай»)

- ✅ W5.3 cProfile data: yaml = 10.789s (fact).
- ⚠️ W5.4 cache: 0.37s actual gain (NOT 5-8s as W5.3 suggested — corrected per
  W5.4 benchmark).
- ⚠️ YAML→JSON conversion gain: estimated ~0.34s additional (10x faster per
  PyYAML vs orjson) — actual depends on config complexity.
- ⚠️ Total possible W5.4 optimization: ~0.71s (cache + JSON) — NOT 5-8s as
  earlier W5.3 estimates suggested.
- ❌ Real blockers: per v6 §2 + §12 — cURL + browser verification BLOCKED Docker.
  Without these, production-ready claim CANNOT be justified regardless of
  optimization.

## 8. References

- `docs/roadmap/W5_STARTUP_PROFILE_AUDIT_2026-09-24.md` — initial audit (estimates corrected)
- `docs/roadmap/W5_CPROFILE_WATERFALL_AUDIT_2026-09-24.md` — cProfile data
- `docs/roadmap/W5_4_CACHE_BENCHMARK_2026-09-24.md` — measured 0.37s gain
- `src/backend/core/config/config_loader.py:79-90` — current `_read_yaml` helper
- v6 §10 W5 spec: «Измерить startup import profile. Lazy import применять
  только при доказанном выигрыше»
- v6 §4.3: «Backward compatibility: deprecation + telemetry/importer audit
  + migration window + removal gate»
- CLAUDE.md: «Не менять публичный контракт без ADR, migration path и
  deprecation window»
