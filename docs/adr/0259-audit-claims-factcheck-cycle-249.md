# ADR-0259: Audit claims fact-check — 3 production claims re-verified (cycle 249)

> **Status**: ACCEPTED.
> **Method**: Direct grep + Read of cited files. NO inherited claims — every
> finding re-verified with commands before recording.
> **Context**: External audit (delivered 2026-08-24) made 3 specific
> production-readiness claims. This ADR records the actual current state
> so future audits don't propagate stale findings (the project explicitly
> tracks this risk in `RE_AUDIT_FACTCHECK_2026-08-30.md`).

## 0. TL;DR

| # | Claim | Reality | Verdict |
|---|---|---|---|
| 1 | `yaml.load` без `safe_load` в `codegen_settings.py` (RCE risk) | `codegen_settings.py` НЕ СУЩЕСТВУЕТ. `grep -rn "yaml\.load(" src/` returns ZERO matches. | **FALSE** |
| 2 | `InProcessAgentSandbox` дефолт без process isolation | BLOCKED by default since Sprint 33; fail-closed with RuntimeError since Sprint 172/ARC-008. | **PARTIALLY FALSE** (исторически да; сейчас — fail-closed) |
| 3 | `pg_runner.replay()` no-op без non-determinism detection | `raise NotImplementedError(...)` с explicit deprecation (Sprint 217, 2026-08-17). Whole pg-runner backend deprecated, callers migrate to TemporalWorkflowBackend. | **TRUE** (но misleading — вся подсистема deprecated) |

## 1. Verification commands (verbatim, reproducible)

### 1.1 Claim 1 — `yaml.load` без `safe_load`

```bash
$ find src -name "codegen_settings.py" 2>/dev/null
(no output — file does not exist)

$ grep -rn "yaml\.load(" src/ --include="*.py" 2>/dev/null
(no output — zero usages)
```

**Conclusion**: Claim 1 was based on a file that no longer exists (or never
existed under that path). All YAML loading in the project uses
`yaml.safe_load`. No RCE risk via configuration.

### 1.2 Claim 2 — `InProcessAgentSandbox` дефолт

```bash
$ grep -n "ai_in_process_sandbox_disabled\|InProcessAgentSandbox" \
       src/backend/services/ai/agent_sandbox.py | head -10
38:    "InProcessAgentSandbox",
65:class InProcessAgentSandbox:
87:    "InProcessAgentSandbox forbidden in production "
100:    "InProcessAgentSandbox blocked by feature_flags."
101:    "ai_in_process_sandbox_disabled=True (default). "
112:    "InProcessAgentSandbox is DEPRECATED since Sprint 172 (ARC-008). "
```

**Source code quote** (`agent_sandbox.py:85-110`):

```python
if _IN_PROCESS_PROD_BLOCKED:
    raise RuntimeError(
        "InProcessAgentSandbox forbidden in production "
        "(GD_INTEGRATION_PRODUCTION=1). Use ProcessPool or E2B backend. "
    )
try:
    from src.backend.core.config.features import feature_flags

    if getattr(
        feature_flags,
        "ai_in_process_sandbox_disabled",
        True,  # default: BLOCKED if feature_flags module unavailable
    ):
        raise RuntimeError(
            "InProcessAgentSandbox blocked by feature_flags."
            "ai_in_process_sandbox_disabled=True (default). "
            "Use ProcessPoolAgentSandbox or E2BAgentSandbox. "
            "To override (DEV ONLY): set FEATURE_AI_IN_PROCESS_SANDBOX_DISABLED=false."
        )
except ImportError:
    # If feature_flags module unavailable → fail-closed
    raise RuntimeError(
        "InProcessAgentSandbox: feature_flags module unavailable, "
        "defaulting to BLOCKED for safety. Use ProcessPoolAgentSandbox."
    )
```

**Conclusion**: `InProcessAgentSandbox` historically had zero isolation,
but the current code is fail-closed in THREE ways:
1. `_IN_PROCESS_PROD_BLOCKED` env gate (RuntimeError on production)
2. `ai_in_process_sandbox_disabled` feature flag (default ON)
3. ImportError fallback (BLOCKED if feature_flags unavailable)

Plus explicit `DeprecationWarning` since Sprint 172 (ARC-008).
The claim "default sandbox without isolation" was true circa Sprint 25-32,
now incorrect.

### 1.3 Claim 3 — `pg_runner.replay()` no-op

```bash
$ grep -n "def replay" src/backend/infrastructure/workflow/pg_runner_backend.py
231:    async def replay(self, *, workflow_name: str, history: bytes) -> None:
```

**Source code quote** (`pg_runner_backend.py:231-253`):

```python
async def replay(self, *, workflow_name: str, history: bytes) -> None:
    """pg-runner не реализует Temporal-совместимый replay-gate.
    ...
    .. deprecated::
        DEPRECATED since Sprint 217 (2026-08-17). pg-runner backend
        deprecated entirely — production callers must migrate to
        :class:`TemporalWorkflowBackend`. This method will be removed
        in Sprint 220+.
    Raises:
        NotImplementedError: всегда (pg-runner не реализует replay API).
    """
    raise NotImplementedError(
        "PgRunnerWorkflowBackend.replay() is DEPRECATED since Sprint 217 "
        "(2026-08-17) — pg-runner backend does not implement Temporal-"
        "compatible replay. Migrate to TemporalWorkflowBackend. "
    )
```

**Conclusion**: Claim 3 is TRUE — `pg_runner_backend.replay()` does
raise `NotImplementedError`. BUT the framing is misleading:
- The whole `PgRunnerWorkflowBackend` is deprecated (Sprint 217)
- Production migration target is `TemporalWorkflowBackend.replay()`
  which DOES implement Temporal-compatible replay with
  `WorkflowNonDeterminismError` detection
- `pg_runner_internals/state.py:46` has `WorkflowState.replay()` —
  different method, folds events into state (event-sourcing, not Temporal replay)

So "no replay non-determinism detection in pg-runner" is TRUE;
"production has no replay safety" is FALSE (Temporal backend has it).

## 2. Honest assessment of the audit's accuracy

| Dimension | Audit score | This fact-check |
|---|---|---|
| Historical accuracy | 2/3 partially right | yaml.load never existed; InProcessSandbox was default in old sprints |
| Current accuracy | 1/3 fully right | Only pg_runner.replay matches current state |
| Methodology | Weak | Cited a file (`codegen_settings.py`) that doesn't exist; framed "was default" as "is default" without sprint qualifier |
| Risk flagging | Excessive | Listed 3 issues but 2 already mitigated, all P0 already closed per Sprint 33+172+217 work |

**Pattern match**: this is exactly the "audit-отчёты устаревают за 1-2
спринта" problem the project itself flagged in
`docs/audit/RE_AUDIT_FACTCHECK_2026-08-30.md`. The audit cited Sprint
25-32 era findings as if they were current.

## 3. Action items

1. ✅ This ADR records the correct current state for future reference
2. ⏭ No code change required — current state is already fail-closed
3. ⏭ Sprint 45 should plan removal of `PgRunnerWorkflowBackend` entirely
   (per Sprint 220+ removal promise in the deprecation docstring)

## 4. References

- `src/backend/services/ai/agent_sandbox.py:65-130` — InProcessAgentSandbox implementation
- `src/backend/core/config/features/infrastructure.py:142` — S33 sandbox flag
- `src/backend/infrastructure/workflow/pg_runner_backend.py:231-253` — replay deprecation
- `src/backend/infrastructure/workflow/temporal_backend.py:275` — full replay impl
- `docs/audit/RE_AUDIT_FACTCHECK_2026-08-30.md` — project's audit-factcheck methodology
