# ADR-0161 — Sprint 79 closure: CapabilityGate ↔ AIPolicySpec.tools two-layer integration (FINAL_REPORT_V2 направление #4 closure, 16 NEW tests) (6 commits)

* Статус: Accepted (Autonomous work cycle S79, 2026-06-12)
* Связано с: S76 (ToolsSpec), S36/S54 (CapabilityGate),
  FINAL_REPORT_V2 направление #4 ("CapabilityGate не ограничивает
  конкретные инструменты")

## Контекст

S79 = **направление #4 closure** (FINAL_REPORT_V2 #4: "CapabilityGate
не ограничивает конкретные инструменты"). Pre-S79: AIPolicySpec.tools
(S76 W1) и CapabilityGate.check (S36/S54) — две SEPARATE системы, не
интегрированные. Агент мог declare capability в gate, но AIPolicySpec
tools whitelist bypass'ил.

**S79 fix**: two-layer enforcement:
1. `check_tool_with_policy(gate, plugin, tool, scope, policy)` —
   per-invoke check (raise on violation).
2. `filter_tools_with_gate(gate, plugin, tool_names, scope, policy)` —
   pre-init filter (drop disallowed tools silently).

## Команда результаты (6 commits)

### W1: design (commit `38d1d55c`)
- File: `src/backend/core/security/capabilities/tool_policy_integration.py` (NEW, 139 LOC)
- `ToolCapabilityCheckError` (PermissionError subclass)
- `check_tool_with_policy(gate, plugin, tool, scope, policy)` — per-invoke
- Two-layer invocation order: gate first, then AIPolicySpec.tools

### W2: build_default_vocabulary import fix (commit `c9d7cfc3`)
- File: `src/backend/core/security/capabilities/gate/__init__.py` (+3, -0)
- S54 W4 decomp forgot to import `build_default_vocabulary` — fixed
- Same recurring pattern as `__slots__=()` bugs (S54, S60, S67, S72, S74, S76)

### W2 follow-up: __slots__() fix (commit `0770e311`)
- File: `src/backend/core/security/capabilities/gate/__init__.py` (+3, -2)
- Removed `__slots__ = ()` (same pattern as S74 W4, S76 W3)
- 4th occurrence в 6 sprints — pre-S80 checklist MUST include
  `git grep -n '__slots__ = ()' src/`

### W3: filter_tools_with_gate (commit `ebbed36d`)
- File: `tool_policy_integration.py` (+79, -0)
- Pre-init filter helper for fail-closed defense
- Silently drops tools failing either layer (vs raise)
- Order preserved

### W4: Tests (commit `1d7481c0`)
- File: `tests/unit/core/security/capabilities/test_tool_policy_integration.py` (NEW, 237 LOC)
- 15 NEW tests + 1 pre-existing = 16 passing
- MockGate helper (avoids complex vocabulary/scope matching)

### W5: Closure (this commit)

## Final state vs FINAL_REPORT_V2 направление #4

| Component | Before S79 | After S79 |
|---|---|---|
| AIPolicySpec.tools (S76) | ✅ exists | ✅ |
| CapabilityGate.check (S36/S54) | ✅ exists | ✅ |
| **Two-layer integration** | ❌ not connected | ✅ **S79 W1+W3** |
| Per-invoke check (raise) | ❌ | ✅ **S79 W1** |
| Pre-init filter (drop) | ❌ | ✅ **S79 W3** |
| Pre-existing decomp bugs | ❌ broken | ✅ **fixed (W2)** |

**Status vs FINAL_REPORT_V2 #4**: CLOSED.

## Pre-existing bugs fixed in S79

1. `CapabilityGate.__init__`: `NameError: name 'build_default_vocabulary' is not defined`
   - Root cause: S54 W4 decomp forgot to import
2. `CapabilityGate.__init__`: `AttributeError: no attribute '_vocabulary'`
   - Root cause: `__slots__ = ()` blocking instance attrs
   - Same pattern recurring: S60 NotebookExecutionService (S74 W4),
     S67 AIPolicyEnforcer (S76 W3+W4), S54 CapabilityGate (S79 W2)

## Recurring decomp bug pattern (S80+ recommendation)

**4th occurrence в 6 sprints** of:
* `__slots__ = ()` left in decomp output → instance attrs blocked
* Required imports forgotten in decomp output → NameError

**Recommendation (S80+ epic candidate)**: add `tools/check_decomp_bugs.py`:
```python
# Scan for `__slots__ = ()` followed by `self.X = Y` in same class
# Scan for module-level function calls with undefined names
# Run в pre-commit hook
```

## Use case (S79 integration pattern)

**Pre-init filter** (W3 approach, fail-closed):
```python
gate = CapabilityGate()
gate.declare("credit", [CapabilityRef(name="db.read", scope="*")])
policy = ToolsSpec(whitelist=["db.read"])
agent_tools = filter_tools_with_gate(
    gate=gate, plugin="credit",
    tool_names=["db.read", "ai.invoke", "fs.write"],
    scope="tenant_abc", policy=policy,
)
# agent_tools = ["db.read"] (others dropped silently)
```

**Per-invoke check** (W1 approach, dynamic policy):
```python
def dispatch(tool, *args, **kwargs):
    check_tool_with_policy(
        gate=gate, plugin="credit", tool_name=tool,
        scope="tenant_abc", policy=current_policy,
    )
    return original_dispatch(*args, **kwargs)
```

## Files changed summary

- W1: 1 file (+139, -0) — tool_policy_integration.py (initial)
- W2: 1 file (+3, -0) — import fix
- W2 follow-up: 1 file (+3, -2) — __slots__ fix
- W3: 1 file (+79, -0) — filter_tools_with_gate
- W4: 1 file (+237, -0) — 15 NEW tests
- W5: 3 files (closure, this commit)
- **Total: 8 files, NET +540 LOC**

## S80+ epic candidates

1. **S80: PoolHealthMonitor + LiteLLM Gateway pool** (P1 направление #3)
2. **S81: CircuitBreakerMiddleware restoration** (P1 направление #16)
3. **S82: docs/cookbooks/** (P1 направление #13)
4. **S83+: tools/check_decomp_bugs.py** (recurring pattern fix)
5. **S83+: 196 layer violations** (направление #2 — class moves)
6. **S83+: AI stack consolidation** (5 frameworks → 2-3)
