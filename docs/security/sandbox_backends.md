# Agent Sandbox Backends (S172 M5 — ARC-008)

**Status**: SHIPPED 2026-06-30. **Breaking change**: minimal (DeprecationWarning для InProcessAgentSandbox).

## TL;DR

Agent sandbox теперь поддерживает **3 runtime backends** через единый
:class:`AgentSandboxSelector` factory. Default = `process_pool`
(process-isolated через stdlib ProcessPoolExecutor). Новый opt-in `e2b`
для cloud-isolated execution. `InProcessAgentSandbox` помечен
`DeprecationWarning` — fail-loud в production env.

## Backend matrix

| Backend | `kind` | Sandbox isolation | Dep | Production-ready |
|---|---|---|---|---|
| `InProcessAgentSandbox` | `in_process` | None (same memory + fds) | stdlib only | ⚠️ **DEPRECATED** |
| `ProcessPoolAgentSandbox` | `process_pool` | Separate Python process | stdlib only | ✅ yes (default) |
| `E2BAgentSandbox` | `e2b` | Cloud VM per invocation | `e2b-code-interpreter>=1.0,<3.0` (opt-in `[ai]`) | ✅ yes (opt-in, requires `E2B_API_KEY`) |

## Files

| Path | LOC | Purpose |
|---|---|---|
| `src/backend/services/ai/agent_sandbox.py` | 420 | Multi-backend support, selector, prod-gate |
| `tests/unit/services/ai/test_sandbox_backends.py` | 280 (NEW) | 16 unit tests |

## API

### Selector (S172 M5 ARC-008 NEW)

```python
from src.backend.services.ai.agent_sandbox import (
    AgentSandboxSelector,
    resolve_agent_sandbox,
    AgentSandboxConfigError,
    AgentSandboxTimeoutError,
)

# Direct construction
selector = AgentSandboxSelector(
    default_kind="process_pool",  # or "in_process" / "e2b"
    e2b_api_key="e2b_...",          # optional override для E2B
)

sandbox = selector.select()                    # default
sandbox = selector.select(kind="e2b")          # explicit
sandbox = resolve_agent_sandbox(
    default_kind="e2b",
    e2b_api_key="e2b_...",
)
```

### Default-migration impact (D274 follow-up)

Settings flag `AIWorkspaceSettings.default_agent_sandbox` — управляется
через YAML profiles. По умолчанию `process_pool`.

## Production gate (defense-in-depth)

`InProcessAgentSandbox` raises `:class:`RuntimeError`` при
`os.environ["GD_INTEGRATION_PRODUCTION"] == "1"` (per D65 / D270
rationale). Belt-and-suspenders против silent regressions:

1. `DeprecationWarning` при construction (любой caller, любой env).
2. RuntimeError при production env (defense layer 2).

Production deploys устанавливают `GD_INTEGRATION_PRODUCTION=1` через
YAML profile — это standard contract через CI/CD pipeline.

## Security considerations

### Threat model

| Threat | Mitigation |
|---|---|
| **RCE в agent code → host compromise** | `InProcessAgentSandbox` (zero isolation) — DEPRECATED + RuntimeError в production. Используем `ProcessPool` или `E2B`. |
| **ProcessPool escape** | Process isolation — отдельный Python worker не имеет доступа к memory parent. FS escape ограничено `os.chroot()` если activated. |
| **E2B cloud compromise** | Per-call sandbox destroy → zero state-leak. Cloud kernel полностью изолирован по design E2B infra. |
| **Self-DoS через estimated_tokens inflation** | M4 (TokenBudget) hard_limit перехватывает на gateway level (defense-in-depth). |

### Audit trail

Каждый sandbox invocation:
- `ai.budget.exceeded.pre` / `.post` (M4) — token budget enforcement.
- `agent.sandbox.zero_isolation_opted` (historical, D16) — при explicit `isolated=False`.
- E2B-specific: cloud kernel start/destroy logs (CloudTrail equivalent).

## E2B backend configuration

```bash
# 1. Install opt-in dep
uv pip install '.[ai]'

# 2. Set API key
export E2B_API_KEY="e2b_..."

# 3. Configure per-tenant policy
# AIWorkspaceSettings.default_agent_sandbox = "e2b"
```

## Backward compatibility

| Caller | Pre-M5 | Post-M5 |
|---|---|---|
| `InProcessAgentSandbox()` | ok | DeprecationWarning, RuntimeError если prod |
| `get_process_pool_agent_sandbox()` | ok | unchanged |
| `ProcessPoolAgentSandbox()` | ok | unchanged |
| `AgentSandboxSelector()` | N/A (NEW) | new API |
| `resolve_agent_sandbox(...)` | N/A (NEW) | new API |

Никаких breaking changes для существующих callers — InProcess deprecated
soft (warning), Production-hardened (RuntimeError).

## Migration path (per-tenant rollout)

1. **Deploy**: ARC-008 SHIPPED, default = `process_pool`.
2. **Per-tenant opt-in E2B**:
   - Tenant поддерживает untrusted-code workflows → set `default_agent_sandbox = "e2b"`.
   - Provision API key через Vault rotation.
3. **Phase-out InProcess** (2-sprint overlap):
   - Sprint 173: логируем InProcess usage per tenant.
   - Sprint 175: удалить InProcessAgentSandbox полностью.

## Test matrix (16 tests)

| # | Test | What it covers |
|---|---|---|
| 1-3 | DeprecationWarning emits alternatives | in_process deprecation message |
| 4 | `test_in_process_hard_gate_in_production` | GD_INTEGRATION_PRODUCTION=1 → RuntimeError |
| 5 | `test_get_process_pool_returns_singleton` | backward-compat singleton |
| 6-10 | E2B config tests | API key handling, lazy validation, missing dep |
| 11-15 | Selector tests | kind routing, unknown kind error |
| 16 | resolve_agent_sandbox convenience | wrapper API |

## References

* `core/tenancy/token_budget.py` — `TokenBudget` primitive (Sprint 9)
* `services/ai/gateway/budget_facade.py` — `LiteLLMBudgetFacade` (M4 ARC-007)
* `services/jupyter/execution_service/e2b_backend.py` — `E2BExecutionBackend` reference (S75 W1)
* Plan: `.mimocode/plans/1782802381991-proud-garden.md`
* Audit: `docs/audit/AUDIT_2026-06-30.md`
