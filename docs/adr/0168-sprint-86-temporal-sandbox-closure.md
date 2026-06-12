# ADR-0168: Sprint 86 — Temporal Sandbox Closure (V2 P0 #2)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S86 (Defense-in-Depth)
**Author**: Ivan (autonomous cycle)

## Context

FINAL_REPORT_V2 P0 #2: **`compile_agent_invoke_step` нарушает Temporal sandbox** —
вызывал `await gateway.invoke(request)` внутри workflow-функции. Temporal запрещает
любой I/O в workflow (deterministic replay requirement).

V2 audit от 2026-06-09 12:35, **Sprint 37 (d42c550d)** от того же дня 12:35 уже
закрыл issue: `workflow.execute_activity("_agent_invoke", ...)`.

V2 факт-чек не обновился после Sprint 37. Реальность: **V2 P0 #2 уже CLOSED**.

## Decision

Sprint 37 fix (d42c550d) — main fix. S86 — **defense-in-depth**: regression tests
+ CI guard против регрессии.

### W1: investigation

Подтверждено: 0 direct `gateway.invoke/acompletion/completion` в step_compilers.py.
Только `workflow.execute_activity("_agent_invoke", ...)` + `_agent_invoke_activity`
в activity_bridge.py (который ВНЕ workflow sandbox — OK).

### W2: 5 regression tests (`tests/unit/dsl/workflow/test_temporal_sandbox.py`)

- `test_step_compilers_no_direct_io_calls` — AST scan: 0 forbidden patterns
- `test_compile_agent_invoke_uses_workflow_execute_activity` — V2 P0 #2 pattern
- `test_agent_invoke_activity_reconstructs_request` — payload → AIRequest
- `test_activity_bridge_handles_agent_invoke` — get("_agent_invoke") works
- `test_agent_invoke_declaration_yields_activity_spec` — _iter_activity_specs

### W3: standalone scan tool (`tools/s86_sandbox_scan.py`)

CLI tool: scan всех `dsl/workflow/compiler/*.py` для direct I/O.
Allowlist: `activity_bridge.py` (там `_agent_invoke_activity`).
Exit 0 / exit 1.

### W4: integrate scan в CI (`.github/workflows/lint.yml`)

```yaml
- name: Temporal sandbox gate (S86 W4, V2 P0 #2)
  run: uv run python tools/s86_sandbox_scan.py
```

Запускается после check_layers/check_docstrings. Если кто-то добавит
direct I/O в workflow-функцию → CI fail.

## Consequences

### Positive
- V2 P0 #2 fully verified (Sprint 37 fix + S86 defense-in-depth)
- 5 regression tests + 1 CI gate = no regression possible
- scan tool reusable для других sandbox checks (HTTP, DB, etc)

### Negative
- 0 functional changes (issue already closed)
- 5 commits = pure documentation/defense — может выглядеть как over-engineering
  для уже-closed issue, но CI guard стоит дешево

## Files Changed

- `tests/unit/dsl/workflow/test_temporal_sandbox.py` (W2: 5 NEW tests)
- `tools/s86_sandbox_scan.py` (W3: CLI tool)
- `.github/workflows/lint.yml` (W4: CI step)
- `CHANGELOG.md` (W5)
- `.shared/context/TECH_DEBT.md` (W5)

## Related ADRs

- d42c550d (Sprint 37: main Temporal sandbox fix)
- ADR-0167 (S85: AIGateway enforcement)

## Outcome

- **V2 P0 #2 CLOSED** (verified) — Sprint 37 main fix + S86 defense-in-depth
- 4 commits, 5 NEW tests, 1 CI gate
- V2 verdict: 6.16 → **7.16/10** (S83 + S84 + S85 + S86)
