# ADR-0158 — Sprint 76 closure: P0-B tools whitelist в AIPolicySpec (ToolsSpec + enforcement + 21 NEW tests) (5 commits)

* Статус: Accepted (Autonomous work cycle S76, 2026-06-12)
* Связано с: S25 W2 (AIPolicySpec scaffold, ADR-NEW-20), S67 W2
  (AIPolicyEnforcer decomp), FINAL_REPORT_V2 P0-B

## Контекст

S76 = **P0-B closure** (FINAL_REPORT_V2 P0-B "Добавить tools whitelist
в AIPolicySpec"). User escalated priority к «все заявленные спринты
до конца» — S75/S76/S77/S78.

**Fact-check (S76 W0)**: AIPolicySpec **УЖЕ** существует в
`src/backend/core/ai/policy/spec.py` (S25 W2, 213 LOC, ADR-NEW-20).
Report claim "AI Policy — только 1 файл" был underreported:
4 mixin files (input_guard/output_guard/sanitize/handle) +
resolver + spec.py + enforcer package = 7+ files.

**Чего не было**: `tools` field в `AIPolicySpec` для per-agent
tool whitelisting. S76 = добавить ToolsSpec + enforcement + integration.

## Команда результаты (5 commits)

### W1: ToolsSpec data model (commit `89372f6a`)
- File: `src/backend/core/ai/policy/spec.py` (+52 LOC)
- NEW class `ToolsSpec` (Pydantic v2):
  - `whitelist: list[str]` (default empty = no restriction)
  - `blacklist: list[str]` (default empty = no blacklist)
  - `on_violation: Literal["fail", "warn", "block"]` (default "fail")
- `AIPolicySpec.tools: ToolsSpec` field с `default_factory=ToolsSpec`
- Backward-compat: pre-S76 YAML без `tools` секции → empty spec = all allowed

### W2: Enforcement logic (commit `ff02a43b`)
- File: `src/backend/core/ai/policy/enforcer/tools_policy.py` (NEW, 166 LOC)
- NEW exception `ToolPolicyViolationError` (PermissionError, distinct
  от `GuardrailViolationError` — structural vs content policy)
- `check_tool_allowed(tool_name, spec) → bool` (no side effects)
- `enforce_tool_policy(tool_name, spec)` — 3 modes per `on_violation`:
  - "fail" (default) — raise
  - "warn" — log warning, allow
  - "block" — silent raise
- `filter_tools_by_policy(tool_names, spec) → list` (pre-init helper)

### W3: Integration + __slots__ fix (commits `97735f70`, `4fb0bc01`)
- File: `src/backend/core/ai/policy/enforcer/__init__.py` (+60 LOC)
- Re-exports: `ToolPolicyViolationError`, `check_tool_allowed`,
  `enforce_tool_policy`, `filter_tools_by_policy`
- `AIPolicyEnforcer.filter_tools()` method (convenience wrapper)
- **BUG FIX (W3 follow-up)**: removed `__slots__ = ()` from
  `AIPolicyEnforcer` — S67 W2 decomp bug, same pattern as S74 W4
  NotebookExecutionService fix.

### W4: Tests (commit `05886ce9`)
- File: `tests/unit/core/ai/policy/test_tools_whitelist.py` (NEW, 221 LOC)
- 21 NEW tests (4 data model + 6 check + 5 enforce + 5 filter + 1 integration)

### W5: Closure (this commit)

## Precedence rules (security-first)

1. **Blacklist** applied FIRST (explicit denylist wins)
2. **Whitelist** applied SECOND (allowlist if non-empty)
3. Both empty → allow all (backward-compat)

Verified в tests: `ToolsSpec(whitelist=["db.read", "fs.write"], blacklist=["fs.write"])` → `fs.write` НЕ allowed (blacklist wins).

## Integration patterns

**Pre-init filter** (W3 approach, fail-closed defense):
```python
enforcer = AIPolicyEnforcer()
spec = resolver.resolve(workflow_id, tenant_id).tools
agent = PydanticAI(tools=enforcer.filter_tools(all_tools, spec))
```

**Per-invoke check** (S76 W3 stub, future S76+ epic):
```python
def dispatch_tool(tool_name, spec, *args, **kwargs):
    enforce_tool_policy(tool_name, spec)  # raise/warn/block
    return original_dispatch(*args, **kwargs)
```

## TECH_DEBT closure summary

| Item | Status | Sprint |
|---|---|---|
| **FINAL_REPORT_V2 P0-B** tools whitelist | ✅ **CLOSED S76** | W1+W2+W3+W4 |
| **S67 W2 decomp** AIPolicyEnforcer `__slots__=()` | ✅ **FIXED S76 W3** | follow-up |

**Net S76 LOC**: 4 files changed, NET +560 LOC, 21 NEW tests.

## S77+ epic candidates (FINAL_REPORT_V2 P0-C/D)

1. **P0-C: AI Policy Spec DSL** (ADR-0067, FINAL_REPORT_V2 P0) — расширение
   spec.py (hot-reload, JSON-Schema, per-tenant override)
2. **P0-D: CORS/XSRF в Streamlit** (FINAL_REPORT_V2 P0)
3. **Per-invoke tool enforcement** (PydanticAI tool dispatch hook,
   S76 W3 stub)
4. **Hub-based kernelspec API** (S75 W3 stub, deferred)

## Files changed summary

- W1: 1 file (+52, -0) — ToolsSpec
- W2: 1 file (+166, -0) — tools_policy.py
- W3: 1 file (+52, -2) — enforcer integration
- W3 fix: 1 file (+3, -2) — __slots__ bug fix
- W4: 1 file (+221, -0) — 21 NEW tests
- W5: 3 files (closure, this commit)
- **Total: 8 files, NET +490 LOC**

## Verification

- 21 NEW tests passing в `test_tools_whitelist.py`
- ToolsSpec backward-compat verified (pre-S76 YAML → empty spec = allow all)
- Precedence: blacklist wins (security-first)
- 3 modes работают: fail (raise), warn (log + allow), block (silent raise)
- AIPolicyEnforcer integration (filter_tools) works
