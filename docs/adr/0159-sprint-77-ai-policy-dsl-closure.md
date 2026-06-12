# ADR-0159 — Sprint 77 closure: P0-C AI Policy Spec DSL (hot-reload + JSON-Schema + specificity, 20 NEW tests) (5 commits)

* Статус: Accepted (Autonomous work cycle S77, 2026-06-12)
* Связано с: S25 W2 (AIPolicySpec scaffold, ADR-NEW-20), ADR-0067,
  FINAL_REPORT_V2 P0-C, S76 (ToolsSpec)

## Контекст

S77 = **P0-C closure** (FINAL_REPORT_V2 P0-C "Реализовать ADR-0067 —
AI Policy Spec DSL"). ADR-0067 уже существует (`docs/adr/0067-ai-policy-spec-dsl.md`),
spec и resolver уже реализованы (S25 W2). Чего не было:
1. **Hot-reload через watchfiles** — `reload()` method existed but
   no actual file watcher.
2. **JSON-Schema export** — Pydantic validation only, no external
   schema для admin UI / MCP docs / IDE autocomplete.
3. **Specificity-based resolution** — `resolve()` used first-match-wins,
   not most-specific-match (per-tenant override с non-trivial layers
   могла дать wrong policy).

## Команда результаты (5 commits)

### W1: Hot-reload через watchfiles (commit `d38859f3`)
- File: `src/backend/core/ai/policy/hotreload.py` (NEW, 182 LOC)
- `PolicyReloadAction` enum: ADDED / MODIFIED / DELETED
- `PolicyReloadEvent` dataclass: (path, action), frozen
- `watch_policy_files(resolver, paths, stop_event, on_reload)`:
  - Async generator using `watchfiles.awatch`
  - `watch_filter` → только `*.policy.yaml` files
  - `debounce=1600ms` (reduces flapping на rapid saves)
  - На каждый event: `resolver.reload()` + yield event
  - `stop_event` для graceful shutdown
  - `on_reload` callback для metrics/audit

### W2: JSON-Schema export (commit `3ef24dad`)
- File: `src/backend/core/ai/policy/jsonschema_export.py` (NEW, 156 LOC)
- `export_aipolicy_json_schema()` → JSON Schema dict (Pydantic v2 built-in)
- `validate_aipolicy_dict(data)` → AIPolicySpec (model_validate wrapper)
- `export_default_policy_yaml()` → starter template для admin docs

### W3: Specificity-based resolution (commit `8c27a753`)
- File: `src/backend/core/ai/policy/specificity.py` (NEW, 152 LOC)
- `compute_specificity(pattern, value) → int`:
  - Exact match → `len(pattern)`
  - Wildcard match → `len(non-wildcard prefix)`
  - No match → -1
- `find_specific_match(policies, workflow_id, tenant_id)` →
  most specific (tenant > workflow > list order)
- `PolicyResolver.resolve_specific(workflow_id, tenant_id)`:
  - NEW method, uses find_specific_match
  - Separate `_specific_cache` (no conflict с `_cache`)
- `reload()` clears both caches

### W4: Tests (commit `ba0f9922`)
- File: `tests/unit/core/ai/policy/test_hotreload_jsonschema_specific.py` (NEW, 339 LOC)
- 20 NEW tests (6 JSON-Schema + 9 specificity + 3 resolver integration + 2 hot-reload)

### W5: Closure (this commit)

## Final state vs FINAL_REPORT_V2 P0-C

| ADR-0067 element | Before S77 | After S77 |
|---|---|---|
| AIPolicySpec data model | ✅ S25 W2 | ✅ (S76 added tools) |
| PolicyResolver.resolve | ✅ first-match-wins | ✅ unchanged (backward-compat) |
| PolicyResolver.resolve_specific | ❌ | ✅ **NEW S77 W3** (most-specific) |
| YAML loader | ✅ S25 W2 | ✅ unchanged |
| Hot-reload method (manual) | ✅ S25 W2 | ✅ unchanged |
| Hot-reload через watchfiles | ❌ | ✅ **NEW S77 W1** |
| JSON-Schema export | ❌ | ✅ **NEW S77 W2** |
| Default policy template | ❌ | ✅ **NEW S77 W2** |

**Status vs FINAL_REPORT_V2 P0-C**: CLOSED (3 missing features added).

## Use case (P0-C resolution flow)

```yaml
# global policy (all tenants)
name: credit_check_global
workflow_pattern: credit_*
tenant_pattern: "*"
budget: {max_cost_usd: 0.50}

# premium override (specific tenant)
name: credit_check_premium
workflow_pattern: credit_*
tenant_pattern: premium_*
budget: {max_cost_usd: 2.00}
```

**С `resolve()`**: depends on roots order, may be wrong.
**С `resolve_specific()`**: premium_* always wins (most specific).
+ JSON-Schema exportable для admin UI form generation.
+ Hot-reload через `watchfiles.awatch` для live config updates без restart.

## Files changed summary

- W1: 1 file (+182, -0) — hotreload.py
- W2: 1 file (+156, -0) — jsonschema_export.py
- W3: 2 files (+179, -0) — specificity.py + resolver.py changes
- W4: 1 file (+339, -0) — 20 NEW tests
- W5: 3 files (closure, this commit)
- **Total: 8 files, NET +856 LOC**

## S78+ epic candidates

1. **P0-D: CORS/XSRF в Streamlit** (FINAL_REPORT_V2 P0)
2. Per-invoke tool enforcement (PydanticAI dispatch hook, S76 stub)
3. Hub-based kernelspec API (S75 stub)
4. PoolHealthMonitor registration
5. CircuitBreakerMiddleware restoration

## Verification

- 20 NEW tests passing
- JSON-Schema exportable (tested roundtrip в YAML)
- Specificity-based resolution works (premium_* wins over *)
- Hot-reload filter (только `*.policy.yaml`, not `*.yaml` — confirmed
  via W3 test bug fix: required correct extension)
- Backward-compat: `resolve()` unchanged
