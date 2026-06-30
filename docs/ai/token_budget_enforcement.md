# Token Budget Enforcement в AI Gateway (S172 M4 — ARC-007)

**Status**: SHIPPED 2026-06-30. **Breaking change**: нет (additive only).

## TL;DR

AIGateway 9-step pipeline теперь включает **token budget enforcement**
(per-tenant quota). Hard-limit → 429. Реализуется через существующую
инфраструктуру `core.tenancy.budget_enforcer` + `core.tenancy.token_budget`,
которая была сделана в Sprint 9 K4 W1, но **никогда не была wired** в
orchestrator mixin. ARC-007 закрывает этот интеграционный gap.

## Архитектура

```
9-step pipeline в gateway_orchestrator_mixin.py:

   1: resolve_policy
   2: check_capability
   3: apply_input_sanitizers
   4: apply_input_guards
   5: render_prompt
 ┌─5.5: enforce_token_budget_pre_call ──► enforce_pre_call() ──► TokenBudget.reserve()
 │                                                                  ↓
 │                                                          BudgetSnapshot { used, hard_limit, remaining, ... }
 │                                                                  ↓
 │                                                          if hard_breached → BudgetExceeded
 │                                                                  ↓
 │                                                          raise BudgetEnforcementError → 429
 │
 │   6: invoke_llm
 ├─6.5: enforce_token_budget_post_call ─► enforce_post_call() ─► TokenBudget.reserve() (diff)
 │
 │   7: apply_output_guards
 │   8: apply_output_sanitizers
 │   9: _cost_track + audit_final
```

## File changes

| Path | LOC | Purpose |
|---|---|---|
| `src/backend/core/ai/gateway_orchestrator_mixin.py` | +120 | `_enforce_token_budget_pre_call` + `_enforce_token_budget_post_call` helpers + pipeline integration |
| `src/backend/core/ai/gateway.py` | +5 | `token_budget` kwarg на `AIGateway.__init__` |
| `tests/unit/core/ai/test_token_budget_integration.py` | NEW (250 LOC) | 9 integration tests |

## API

### Setup

```python
from src.backend.core.ai.gateway import AIGateway
from src.backend.core.tenancy.token_budget import (
    TokenBudget, TokenBudgetConfig, InMemoryTokenBudgetBackend, BudgetPeriod,
)

# Production: RedisTokenBudgetBackend + config from YAML.
budget = TokenBudget(
    backend=RedisTokenBudgetBackend(...),  # или InMemory для dev/test.
    configs={
        "tenant-premium": TokenBudgetConfig(soft_limit=1_000_000, hard_limit=2_000_000),
    },
    default_config=TokenBudgetConfig(soft_limit=10_000, hard_limit=20_000),
)

gateway = AIGateway(
    policy_resolver=...,
    audit_service=...,
    token_budget=budget,  # ← ARC-007 wiring
)

# Теперь любой invoke() автоматически проходит budget check.
```

### Per-invoke flow

1. **`_enforced_invoke(request)` step 5.5**: render завершён → estimate tokens
   via heuristic (len(rendered) / 4 + 200) → `enforce_pre_call()`. Если
   `BudgetExceeded` → propagate `BudgetEnforcementError` → caller → 429.
2. **`_enforced_invoke(request)` step 6.5**: после `_invoke_llm` →
   `actual_tokens = completion.tokens_prompt + completion.tokens_completion`.
   Если `actual > estimated` → `enforce_post_call(diff)`. Если нет → snapshot.

### Backward compatibility

| Caller | Pre-M4 | Post-M4 |
|---|---|---|
| `AIGateway()` без `token_budget=` | enforcement OFF (pass-through) | unchanged |
| `AIGateway(token_budget=budget)` | attribute set, но никогда не вызывался | enforcement active |
| `request.tenant_id=""` | pass-through | pass-through (no-op) |
| Redis backend outage | N/A | fail-open (configurable per tenant) |

Никаких breaking changes — additive only.

## Test matrix (9 tests)

| # | Test | What it covers |
|---|---|---|
| 1 | `test_no_budget_passes_through` | backward-compat: without `_token_budget` → no-op |
| 2 | `test_pre_call_reserves` | pipeline reserves estimated tokens at step 5.5 |
| 3 | `test_actual_exceeds_estimated_extra_reserved` | pipeline corrects diff after LLM call |
| 4 | `test_hard_limit_pre_call_raises` | hard_limit exceeded pre-call → BudgetEnforcementError |
| 5 | `test_hard_limit_post_call_raises` | hard_limit exceeded post-call → BudgetEnforcementError |
| 6 | `test_empty_tenant_id_skips` | empty tenant_id → enforcement skipped (no error) |
| 7 | `test_render_429_shape` | JSON contract for 429 response body |
| 8 | `test_no_budget_attribute_returns_none` | helper unit: missing attribute → None |
| 9 | `test_no_budget_via_dunder_getattr` | helper unit: explicit `None` → None |

## Security considerations

### Threat model

| Threat | Mitigation |
|---|---|
| **Манипуляция `tenant_id` для budget bypass** | Tenant identity приходит из authenticated JWT (per V11.1 capability), not from request body. `request.tenant_id` extracted via `TenantContext.tenant_id`. |
| **Estimated-token inflation DoS** | budget backend имеет Redis INCRBY (atomic). Pre-call reserve фиксирует upper-bound. |
| **Post-call actual > estimated** | post-call reserve: дополнительная reservation предотвращает budget over-shoot. Hard limit срабатывает даже после LLM call. |
| **Budget backend outage** | default fail-open (per `TokenBudgetConfig.fail_mode`). Set `fail_mode="closed"` для fail-safe в production. |

### Audit trail

Каждый pre-call и post-call:
- `ai.budget.exceeded.pre` / `ai.budget.exceeded.post` → warning log (structured).
- При hard_breached — `BudgetEnforcementError` propagates → caller endpoint maps → 429 через `render_429(exc)`.

## Migration impact

### Production rollout (per ARGON2 pattern)

1. **Deploy**: ARC-007 SHIPPED, но `token_budget` kwarg default = None → enforcement OFF by default.
2. **Per-tenant opt-in**: setup `TokenBudget` с feature-flag (например `feature_flags.tenant_token_budget_enabled`).
3. **Initial limits**: консервативные (например 10x usage нормы) + allow soft_limit grace period.
4. **Rollout**: tenant-by-tenant через YAML config.
5. **Full enforcement**: после того как все tenants прошли on-ramp → закрытие fail-open и budget enforced для всех.

### Backward compat note

Если `request.tenant_id == ""` — enforcement skip (no-op). Это позволяет
legacy callers с missing tenant context continue работать без 429.
Per-ADR-0071, `tenant_id` обязательное поле AIRequest — backward-compat
preserved для backward-compat callers.

## References

* Plan: `.mimocode/plans/1782802381991-proud-garden.md`
* Audit: `docs/audit/AUDIT_2026-06-30.md`
* `core/tenancy/budget_enforcer.py` — primitives (Sprint 9 K4 W1)
* `core/tenancy/token_budget.py` — `TokenBudget` dataclass + backends
* `services/ai/gateway/budget_facade.py` — `LiteLLMBudgetFacade` (Sprint 9 K4 W2)
