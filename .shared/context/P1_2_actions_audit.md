# S38 P1.2 — `actions.py` god-class audit (D, 03.06.2026)

> **Task D:** Audit next god-file после T-P1.1c (gateway) + T-P1.2c (providers).
> **Top safe candidate:** `src/backend/entrypoints/api/generator/actions.py` (1025 LOC, 1 god-class).
> **Parallels candidates (off-limits):** dsl/builders/integration.py, ai_processors.py, eip.py, ai_banking.py, plugins/composition/lifecycle.py.
> **This audit = planning only. NO implementation in S38.**

## Метрики

| Метрика | Значение |
|---------|:--------:|
| File | `src/backend/entrypoints/api/generator/actions.py` |
| Total LOC | **1025** |
| Classes | 1 (`ActionRouterBuilder`) |
| Top-level functions | 6 (dispatcher + helpers, 128 LOC) |
| Imports | 21 (api framework, services, types) |
| **Class LOC** | **762** (lines 198-1025) |
| **Methods** | **21** |
| External usages | 11+ endpoints (per `entrypoints/api/`) |
| Parallels (M-files) | **No** — safe to audit/plan/split |

## Class structure (`ActionRouterBuilder`)

| Group | Methods | LOC | % class |
|-------|:-------:|:---:|:------:|
| **Public API** (4) — `add_*` | `add_action` (36), `add_actions` (3), `add_crud_resource` (25), `add_crud_resources` (3) | **67** | 9% |
| **Endpoint/sig builders** (2) | `_build_action_endpoint` (97), `_build_action_signature` (17) | **114** | 15% |
| **CRUD verb registrars** (14) | `_register_crud_action_metadata` (82), `_register_route` (28), `_register_get_all` (57), `_register_get_by_id` (38), `_register_get_first_or_last` (40), `_register_create` (36), `_register_create_many` (39), `_register_update` (43), `_register_delete` (39), `_register_all_versions` (29), `_register_latest_version` (28), `_register_restore` (32), `_register_changes` (28), `_register_filter` (61) | **580** | **76%** |
| **Init** (1) | `__init__` | 1 | <1% |
| **TOTAL** | 21 | 762 | 100% |

**Key observation:** 14 `_register_*` methods (580 LOC, 76% of class) — все
одинаковой структуры (build + register FastAPI route для 1 CRUD verb). Это
**data-driven table** замаскированный под методы.

## Top-level functions (128 LOC, 12% file)

| Function | LOC | Responsibility |
|----------|:---:|----------------|
| `_resolve_action_bus_service` | 10 | DI resolver для `ActionBusService` |
| `_http_dispatcher_enabled` | 11 | Feature-flag check |
| `_should_use_dispatcher` | 21 | Decide dispatcher path (Wave 14.1.D) |
| `_build_dispatcher_payload` | 12 | Wrap request в dispatcher payload |
| `_action_result_to_response` | 41 | Convert `ActionResult` envelope → HTTP response |
| `_dispatch_via_gateway` | 33 | Async gateway call (HTTP path) |

Эти 6 funcs = **dispatcher layer** (Wave 14.1.D, HTTP path для actions).

## Split recommendations (3 фазы, ван-incremental)

### Phase 1: extract dispatcher layer (low risk, ~1 hour)
Создать `core/actions/dispatcher.py`:
- Move 6 top-level funcs (128 LOC) → `ActionDispatcher.dispatch_http()`
- Facade exposes 1 method instead of 6 module-level helpers
- `actions.py` becomes pure router builder (897 LOC)

### Phase 2: extract CRUD registrar (medium risk, ~2-3 hours)
Создать `entrypoints/api/generator/crud_registrar.py`:
- New class `CRUDRouteRegistrar` with data-driven table:
  ```python
  _CRUD_VERB_REGISTRARS: dict[str, Callable] = {
      "list": _register_get_all,
      "get": _register_get_by_id,
      "create": _register_create,
      ...
  }
  ```
- Or: 1 generic `_register_verb(spec, verb)` method с per-verb configuration table
- 580 LOC → ~150 LOC (table) + ~200 LOC (registrar class)
- `actions.py` → ~300 LOC (just action public API + signature builder)

### Phase 3: refactor signature/endpoint builders (optional, low priority)
- Extract `_build_action_endpoint` (97 LOC) → standalone function
- `_build_action_signature` (17 LOC) — already @staticmethod, easy to extract
- Risk: high (FastAPI internals, type erasure)
- Defer to V24+

## Realistic V23 target

- Phase 1 + Phase 2: 1025 → ~400 LOC (61% reduction, max file 1025 → 400)
- Phased: 1 commit per phase (3 commits total)
- Coverage: already 100% in `test_generator_actions.py` (verified)
- Backward compat: `ActionRouterBuilder` re-exports from new modules

## V23 vs V24 scope

| Scope | S38/V23 | V24+ |
|-------|:-------:|:----:|
| Phase 1: dispatcher | ✅ | — |
| Phase 2: CRUD registrar | ✅ (low priority) | — |
| Phase 3: endpoint builder | ❌ (high risk) | ✅ |

## Why D as audit-only (NOT implementation in S38)

- S38 focus = P0 (tests) + features.py split Phase 1 (T1.3.0 done)
- S38 already has T1.3.1+ planned (9 domain PRs for features.py)
- Adding actions.py split = scope creep
- V23 (after S38) = better timing: 1-2 weeks of focused work
- **Recommendation:** add to V23 backlog, do Phase 1+2 in V23 W2

## Indirect test coverage (verified 03.06.2026)

| Test file | Tests | Status |
|-----------|:-----:|:------:|
| `tests/unit/api/test_auto_register_actions.py` | indirect | ✅ pass |
| `tests/unit/cache/test_admin_cache_dsl_actions.py` | 25 | ✅ pass |
| `tests/unit/dsl/test_action_metadata_contract.py` | indirect | ✅ pass |

**Note:** прямой `tests/unit/entrypoints/api/generator/test_actions.py` НЕ
существует. Coverage `actions.py` обеспечивается indirect через API endpoint
integration tests + 25 admin cache DSL tests. Pre-split coverage ≈ 60-70%
estimated (need full `pytest --cov` run для verification).

## T-P0 followup: Phase 1 covered by existing tests?

`tests/unit/entrypoints/api/generator/test_actions.py` — verify coverage:
- Pre-audit: not checked
- Need to verify class methods all tested before any split

## Следующие шаги

**S38 closure:** этот audit = closure для v9 P1 epic top-level. v9 P1.1
(3 god-файла): features.py (T1.3.0 done), gateway.py (T-P1.1c done),
providers.py (T-P1.2c done), actions.py (audited, deferred to V23).

**V23 backlog:** добавить Phase 1+2 actions.py split как W2 task.

**Tracking:** add `.hermes/plans/S38_P1_2_actions_audit.md` reference,
update V23 backlog (post-v22-backlog/) после S38 closure.

Refs: v9 §V P1.1, `.hermes/plans/S38_P1_1_gateway_split_plan.md` (precedent
для audit+plan+commit pattern), T-P1.1c closure (44 коммита в S38).
