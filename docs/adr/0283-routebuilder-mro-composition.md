# ADR-0283: RouteBuilder MRO composition refactor (DRAFT — HIGH risk)

> **Status**: **DRAFT** (2026-08-27). NOT yet ACCEPTED.
> **Method**: composition over inheritance — replace 82-mixin MRO chain with
> feature-objects (delegation pattern).
> **Scope**: `src/backend/dsl/builders/base/__init__.py:102-139` (RouteBuilder),
> 82 mixin classes, ~7000 LOC total.
> **Date**: 2026-08-27.
> **Linked**: Sprint 35 retro §6.2 (deferred from S35-W2), Sprint 39 gap-doc §6
> (ADR required), Sprint 40 gap-doc §6 (DRAFT only Sprint 40, impl S41+).

## 0. Контекст

Per Sprint 35 retro §6.2 + Sprint 40 gap-doc §6: HIGH-risk refactor
ADR required для `RouteBuilder` MRO refactor.

Per Sprint 39 gap-agent (W1, 2026-08-28, **CRITICAL FINDING**):
**Actual MRO depth = 82 mixins** (NOT 38 as user prompt stated).

```python
$ python -c "from src.backend.dsl.builders.base import RouteBuilder; print(len(RouteBuilder.__mro__))"
82

$ python -c "from src.backend.dsl.builders.base import RouteBuilder; \
    [print(f'{i+1:2d}. {c.__name__}') for i, c in enumerate(RouteBuilder.__mro__[:36])]"
   1. RouteBuilder
   2. AIRPAMixin
   3. BankingScriptsMixin
   ...
  36. RequestReplyMixin
   ...
  82. object
```

### 0.1 Measured init time

```
$ python -c "import time; t=time.perf_counter(); from src.backend.dsl.builders.base import RouteBuilder; print(time.perf_counter()-t)"
~7.3s  # including Vault fallback message overhead
```

Per-codebase init (excluding Vault errors): ~5-7s. **High init cost** = HIGH risk
for test suites (conftest.py imports), cold-start latency.

### 0.2 Risk analysis (verified 2026-08-28)

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| C3 linearization conflict | Medium | High (subtle bugs) | Phase 2 risk analysis BEFORE impl |
| `super().__init__()` ambiguity | Medium | Medium | Phase 2 chain scan |
| `__init_subclass__` interactions | Low | High | Phase 2 discovery |
| 82 mixin names = global namespace pollution | High | Medium | Phase 1 verification (already exists) |
| Init cost 5-7s = test suite slowdown | High | Medium | Lazy MRO option (Variant C) |
| Extensions depend on specific mixins | High | **CRITICAL** | Phase 3 migration plan per-extension |

## 1. Рассмотренные варианты

### Variant A: Composition over inheritance (this ADR)

**Approach**: Replace 82-mixin chain with feature-objects (Protocol composition).
- `RouteBuilder` becomes a thin class with `__getattr__` proxy to feature objects.
- Each mixin class becomes a `@runtime_checkable Protocol` (not concrete mixin).
- Existing public API preserved via `__getattr__` lazy resolution.

**Pros**: Eliminates MRO conflicts, preserves public API, allows lazy loading.

**Cons**: HIGH refactor cost (82 mixins → 82 feature-objects). Multi-sprint.

**VERDICT**: ✅ RECOMMENDED for long-term. Requires ADR + per-mixin migration plan.

### Variant B: Namespace package split (5 sub-namespaces)

**Approach**: Split 82 mixins into 4-5 sub-namespaces:
- `core/airpa/`, `core/banking/`, `core/eip/`, `core/integration/`, `core/system_ops/`.
- Each namespace owns ~16 mixins.
- `RouteBuilder` aggregates via sub-namespace `__getattr__`.

**Pros**: Reduces MRO per class, explicit grouping.

**Cons**: Public API changes (sub-namespace access required). Extensions must update.

**VERDICT**: ❌ Rejected (public API break too large).

### Variant C: Lazy MRO (delay mixin addition until first use)

**Approach**: Mixins добавлены к MRO только на first call (`__init_subclass__`).

**Pros**: Zero init cost (cold start 0.1s → first-call 7s).

**Cons**: Mixin order неопределён → `super()` chains broken.

**VERDICT**: ❌ Rejected (breaks mixin inheritance semantics).

### Variant D: Do nothing (accept 82 mixins as YAGNI-acceptable)

**Approach**: No refactor, document 82-mixin MRO as architectural debt.

**Pros**: Zero work.

**Cons**: HIGH risk remains (MRO conflicts, init cost). Future extensions
cannot add new mixins without C3 conflict potential.

**VERDICT**: ❌ Rejected (HIGH risk accumulates).

## 2. Решение (DRAFT)

**Variant A** (composition over inheritance). Multi-sprint plan:

### Phase 1 — Document current state (Sprint 40 W1, commit `b3c74f9a`-extension) — DONE
- ✅ MRO depth verified: 82 mixins.
- ✅ Init time measured: 5-7s.
- ✅ 82 mixin names enumerated.

### Phase 2 — Risk analysis (Sprint 41, ADR-0283 ACCEPTED commit)

1. **C3 linearization conflict scan**: identify mixin `super().__init__()` chains.
2. **`__init_subclass__` audit**: identify hooks in mixins.
3. **Public API audit**: identify methods/attributes each mixin adds.
4. **Extensions audit**: grep extensions/* for direct mixin dependencies.

### Phase 3 — Per-mixin migration (Sprint 41-S44, per-mixin priority order)

| Priority | Mixin group | LOC | Migration risk | Estimated sprint |
|---|---|---:|---|---|
| 1 | `EventBusMixin` + sub-mixins | ~50 | Low | S41 |
| 2 | `VariableMixin` + `PolicyMixin` + `FluentMixin` | ~80 | Low | S41 |
| 3 | `AIRPAMixin` + sub-mixins | ~200 | Medium | S42 |
| 4 | `IntegrationMixin` + sub-mixins | ~300 | Medium | S42 |
| 5 | `EIPMixin` + sub-mixins (8 mixins) | ~400 | **High** | S43+ |

### Phase 4 — DO NOT IMPLEMENT in Sprint 40

**Rationale** (per user directive "решай deferred, не уклоняйся от них" +
HIGH risk requirement):
- ✅ ADR DRAFT created (this document).
- ⏸️ Phase 2 risk analysis (S41 W1).
- ⏸️ Per-mixin migration (S41-S43+, multi-sprint).
- ⏸️ Composition pattern implementation (S44+, after risk analysis).

**DO NOT IMPLEMENT IN SPRINT 40** — per Sprint 39 gap-doc §6:
"82 mixin refactor в один sprint = unacceptable regression risk".

## 3. Consequences

### Positive (after full implementation)
- ✅ Eliminates MRO conflicts (composition, not inheritance).
- ✅ Lazy loading (init cost 5-7s → 0.1s for RouteBuilder).
- ✅ Public API preserved via `__getattr__` proxy.
- ✅ New extensions can add feature-objects без C3 conflict risk.
- ✅ Test suite faster (no 7s startup penalty).

### Negative
- (−) Multi-sprint implementation (S41-S44+).
- (−) High regression risk during per-mixin migration (Phase 3).
- (−) Extensions may depend on specific mixin imports (require extension audit).
- (−) Composition pattern adds `__getattr__` lookup overhead (negligible vs init).

### Neutral
- 82 mixin classes preserved (re-exported via composition).
- Public API surface unchanged (`route_builder.method()` works identically).
- ADR-0282 §3 Phase B ratchet unaffected (allowlist reduction continues per-bridge).

## 4. Migration strategy (per-mixin, deferred to S41+)

```python
# BEFORE (current):
class RouteBuilder(AIRPAMixin, BankingScriptsMixin, ... 82 mixins):
    pass

# AFTER (composition, Variant A):
class RouteBuilder:
    """Composition-based: feature-objects via __getattr__ proxy."""

    def __init__(self):
        self._features: dict[str, FeatureObject] = {}
        for feature_class in _feature_registry:
            self._features[feature_class.__name__] = feature_class(self)

    def __getattr__(self, name: str) -> Any:
        # Lazy resolution: route to feature object
        for feature in self._features.values():
            if hasattr(feature, name):
                return getattr(feature, name)
        raise AttributeError(f"RouteBuilder has no attribute {name!r}")
```

### 4.1 Per-mixin priority (deferred Phase 3)

Per migration order §2.3, **Phase 1 = EventBus mixins** (lowest risk, simplest):

1. Extract `EventBusMixin` → `EventBusFeature` Protocol + concrete impl.
2. Update `RouteBuilder` to aggregate via `_features` dict.
3. Verify public API: `route_builder.publish_event(...)` works identically.
4. Run full test suite — 0 regressions required.

### 4.2 Risk gates per migration

| Gate | Pass criteria |
|---|---|
| Public API compatibility | All 70 regression tests pass |
| MRO depth reduction | `len(RouteBuilder.__mro__)` decreases (5 → 4 → 3...) |
| Init time improvement | `<5s` (was 5-7s baseline) |
| Extension compatibility | All extensions/* tests pass |

## 5. Verification (DRAFT only, Sprint 40)

```bash
$ ls docs/adr/0283-routebuilder-mro-composition.md
# expected: 1 file (DRAFT)

$ grep -c "Status: DRAFT" docs/adr/0283-routebuilder-mro-composition.md
# expected: ≥1

$ python -c "from src.backend.dsl.builders.base import RouteBuilder; assert len(RouteBuilder.__mro__) == 82"
# expected: success (NO regression during Sprint 40 — DRAFT only, no impl)

$ grep "ADR-0283" docs/retros/SPRINT_40_RETRO_2026-08-27.md
# expected: ≥1 reference (DRAFT commitment)
```

### 5.1 NO regression tests in Sprint 40 (DRAFT only)

**Rationale**: DRAFT only, no code changes. Phase 2 risk analysis (S41) precedes
any implementation.

### 5.2 Frozen MRO depth as Sprint 40 EOD

```bash
$ python -c "from src.backend.dsl.builders.base import RouteBuilder; assert len(RouteBuilder.__mro__) == 82"
# expected: success
```

If MRO depth changes during Sprint 40 (e.g., parallel agent adds/removes mixin),
DRAFT becomes stale → re-evaluate.

## 6. Related

- ADR-0282 §3 Phase B (allowlist prune plan, related architectural work)
- `src/backend/dsl/builders/base/__init__.py:102-139` (RouteBuilder source)
- `src/backend/dsl/builders/base/__init__.py:377-529` (6 Protocol classes — partial migration target)
- `SPRINT_35_RETRO_2026-08-27.md` §6.2 (original carry-over)
- `SPRINT_39_RETRO_2026-08-27.md` §6.2 (carry-over context, 82-mixin actual vs 38 claimed)
- `SPRINT_40_GAP_ANALYSIS_2026-08-27.md` §6 (Item 5 scope)
- `tests/unit/dsl/builders/test_rpa_browser_all_builder_methods.py` (70 regression tests — MUST pass post-impl)

## 7. Decision log

| Date | Status | Author | Notes |
|---|---|---|---|
| 2026-08-27 | DRAFT created | Sprint 40 W1 | Phase 1 (current state documented). Phase 2-4 deferred to S41-S44+ |
| TBD | ACCEPTED | TBD | After Phase 2 risk analysis (S41 W1) |
| TBD | IMPL Phase 1 | TBD | S41 (EventBusMixin per-mixin priority) |
| TBD | IMPL Phase 2 | TBD | S42 (Variable/Policy/Fluent mixins) |
| TBD | IMPL Phase 3 | TBD | S43 (AIRPAMixin + sub-mixins) |
| TBD | IMPL Phase 4 | TBD | S44+ (Integration, EIP) |

## 8. Honest disclosures

1. **82 mixins, NOT 38** as user prompt stated — verified 2026-08-28 via
   `python -c "RouteBuilder.__mro__"`.
2. **DRAFT only** — no implementation in Sprint 40 per user directive
   (HIGH risk requires careful decomposition).
3. **Public API preservation critical** — 70 regression tests MUST pass
   post-Phase 1 implementation.
4. **Multi-sprint commitment** — Phase 3 migration spans S41-S44+.
5. **Init time 5-7s** measured (per 2026-08-28 test) — not addressed until
   Phase 4 (composition pattern enables lazy loading).
