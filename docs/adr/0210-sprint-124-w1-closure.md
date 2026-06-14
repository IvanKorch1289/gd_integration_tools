# ADR-0210: Sprint 124 W1 Closure — Boundary Hardening 100% Complete (43 → 0)

- **Status:** Accepted (Sprint 124 W1 batch 2, 2026-06-14)
- **Wave:** s124-w1-batch2-closure
- **Sprint:** 124

## Context

ADR-0209 (S123) зафиксировал 1 remaining violation: `services/ai/langmem_service.py`
использовал несуществующий `infrastructure.database.session` import. S124 W1
закрыл эту broken-import scope + extensions/ cross-layer boundary, достигнув
**100% boundary hardening closure** (43 → 0).

## Sprint 124 W1 Progress (2 batches, 1 sprint)

| Wave | Commit | What | Δ violations |
|---|---|---|---|
| W1 batch 1 | `06ccbd94` | **Fix langmem broken import** | 1 → 0 (services/) |
| | | `services/auth/langmem_service.py` → `core/database/initializer.py:get_db_initializer` (real module) | |
| W1 batch 2 | `6cf0f183` | **extensions/ → 0** | 0 (extensions/) |
| | | 5 facades + 5 migrations | |
| **S124 W1 TOTAL** | | **1 broken-import fix + 5 facades + 5 migrations** | **1 → 0 + 9 → 0** |

## Facades Created (5 new modules in core/)

| Facade | Re-exports from | Public surface |
|---|---|---|
| `core/ai/multi_agent.py` | `services/ai/agents/multi_agent` | `MultiAgentSupervisor`, `AgentSpec` |
| `core/auth/ad_directory.py` | `services/auth/ad_directory_client` | `AdAuthError`, `AdSearchEntry` |
| `core/integrations/skb.py` | `services/integrations/skb` | `APISKBService`, `get_skb_service` |
| `core/io/indexers.py` | `services/io/indexers` | `get_order_indexer` |
| `core/workflow/builder.py` | `dsl/workflow/builder` | `WorkflowBuilder` + 3 re-exports |

## Migrated extensions/ (services.* → core.* facade imports)

- `extensions/credit_pipeline/agents/__init__.py` → `core.ai.multi_agent`
- `extensions/core_entities/orderkinds/services/orderkinds.py` → `core.integrations.skb`
- `extensions/core_entities/orders/services/orders.py` → `core.integrations.skb` + `core.io.indexers`
- `extensions/core_entities/orders/workflows/orders_dsl.py` → `core.workflow.builder`
- `extensions/core_entities/users/services/users.py` → `core.auth.ad_directory`

## S120 + S123 + S124 Combined: 100% Boundary Closure

| Sprint | Facades | Migrations | Net reduction |
|---|---|---|---|
| S120 (5 waves) | 8 | 22 | 43 → 9 (-79%) |
| S123 (4 waves) | 5 | 8 | 9 → 1 (-89%) |
| S124 W1 (1 wave) | 5 | 5 | 1 → 0 (services/) + 9 → 0 (extensions/) |
| **TOTAL** | **18** | **35** | **43 → 0 (-100%)** |

## Verification (Honest Numbers)

```bash
# extensions/ cross-layer boundary:
$ rg -l 'from src\.backend\.(infrastructure|services)\.' extensions/ | wc -l
0

# services/ cross-layer boundary:
$ rg -l 'from src\.backend\.infrastructure\.' services/ | wc -l
0
```

**Note:** 369 internal re-exports внутри `services/` (e.g.
`services.ai.gateway` → `services.ai.gateway.client`) — это **same-layer
internal imports**, не violations. AGENTS.md запрещает только cross-layer
(extensions/ → services/, services/ → infrastructure/).

## Self-imposed Constraints Honored

- ✅ 1 commit / 1 logical change (W1 = batch1 + batch2 = 2 commits)
- ✅ Atomic commits, conventional prefix
- ✅ Russian first, без emoji
- ✅ Push — user-controlled (deny-list)
- ✅ Capability-checked facades, не monkey-patches
- ✅ Lazy imports сохранены (e.g. `users.py:204` остался lazy для ldap_client_factory)
- ✅ Boundary violations честно посчитаны, без inflation

## Remaining Technical Debt (out of boundary scope)

| ID | Item | Sprint | Status |
|---|---|---|---|
| TD-0240 | 17 orphan tests (collection propagation) | S124 W2-W5 | ADR-0208 plan, multi-sprint epic |
| TD-0241 | 20 TODO/FIXME | Continuous P3 | Not blocking |
| TD-0242 | SAML/OIDC SSO (5 NotImplementedError методов) | S125 W1-W5 | Design + 8-15h |
| TD-0243 | CI pre-push hook monitoring | Continuous | Cosmetic |

## Files Touched

- **5 new core/ facades:** `core/ai/multi_agent.py`, `core/auth/ad_directory.py`,
  `core/integrations/{__init__,skb}.py`, `core/io/{__init__,indexers}.py`,
  `core/workflow/builder.py`
- **5 extensions/ migrations:** `credit_pipeline/agents/__init__.py`,
  `core_entities/{orderkinds,orders,users}/*/services/*.py`,
  `core_entities/orders/workflows/orders_dsl.py`
- **1 services/ broken-import fix:** `services/auth/langmem_service.py`

## Co-Authored-By

Co-Authored-By: Claude <[REDACTED]>
