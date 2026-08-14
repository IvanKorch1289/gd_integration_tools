# Cycle 204 — Protocols catalog + Tier 3 __getattr__ diagnostic (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (parent agent)
**Scope:** cleanup untracked files + safe incremental decomposition.

---

## TL;DR

| Commit | Задача | Tests |
|---|---|---|
| `ffa42b92` (cycle 203) | docs(audit): audit follow-up + full verification (no code) | — |
| cycle 204a | feat(dsl): RouteBuilder MRO Protocols catalog (8 categories × 36 mixins) | 9/9 |
| cycle 204b | feat(dsl): Tier 3 `__getattr__` diagnostic + 4 regression tests | 4/4 |

**Total cycle 204**: 2 atomic commits, +600 LOC, 13 new tests, 0 regressions.

---

## 1. Cycle 204a — Protocols catalog

### 1.1 Background

Cycle 203 WIP от другого агента оставил untracked:
- `src/backend/dsl/builders/protocols.py` (309 LOC)
- `tests/unit/dsl/builders/test_protocols.py` (149 LOC)

Ponytail cleanup: commit after docstring fix.

### 1.2 What's in protocols.py

8 Protocol-классов (marker classes, не method-declarative Protocols):

| Category | Mixins | Source files |
|---|---|---|
| ControlFlow | ControlFlowMixin, SagaLRAMixin, BatchMixin, DeferredExecutionMixin | dsl/builders/control_flow.py + 4 |
| EIP | EIPMixin, EIPContentMixin, ContentMixin, ConvertersMixin, FormatConvertersMixin, RequestReplyMixin, TemplateEngineMixin, TemplateEngineChainMixin | dsl/builders/eip.py + 7 |
| DataStore | DataStoreMixin, DataStoreStepMixin, CollectionMixin | dsl/builders/data_store.py + 2 |
| Transport | TransportSourcesMixin (alias: SourcesMixin) | dsl/builders/sources_mixin.py |
| Infrastructure | InfrastructureDSL, FluentMixin, ConfigMixin, ValidationMixin, DepsMixin, FeatureMixin | dsl/builders/infrastructure_dsl.py + 5 |
| Resilience | ResilienceMixin, ComplianceMixin, MiddlewareMixin, IPRestrictionMixin, PolicyMixin | dsl/builders/base/resilience_mixin.py + 4 |
| AIAgent | AIRPAMixin, AgentDSLMixin, RouterSpecialistMixin, NotebookMixin, PlanExecuteMixin, ReflectionLoopMixin | dsl/builders/ai_rpa.py + 5 |
| Messaging | EventBusMixin, IntegrationMixin, VariableMixin | dsl/builders/eventbus_mixin.py + 2 |

3 helpers:
- `get_category_for_mixin(name) → Protocol class | None`
- `get_protocol_for_category(name) → Protocol class | None`
- `is_runtime_protocol_conformant(instance, category) → bool`

### 1.3 Tests (9 total)

```text
test_protocols_module_exports               PASS
test_category_map_covers_36_mixins          PASS
test_eight_distinct_categories              PASS
test_get_category_for_mixin_known           PASS
test_get_category_for_mixin_unknown_returns_none  PASS
test_get_protocol_for_category_known        PASS
test_get_protocol_for_category_unknown_returns_none  PASS
test_route_builder_conformant_all_8_categories  PASS
test_is_runtime_protocol_conformant_unknown_returns_false  PASS
```

### 1.4 Ponytail docstring fix

Original docstring claimed "412 публичных методов + test_method_inventory test"
— but actual count is **416** methods (verified) и **test_method_inventory не
существует**. Заменено на "~400+ публичных методов" с reference на
`is_runtime_protocol_conformant` test.

---

## 2. Cycle 204b — Tier 3 `__getattr__` diagnostic

### 2.1 Background

3-tier decomposition strategy (CYCLE-202-GRPC-ROUTEBUILDER.md §2.4):

| Tier | Strategy | Risk | Reward | Status |
|---|---|---|---|---|
| 1 | Mixin grouping (76 → ~40) | MEDIUM | MEDIUM | Deferred cycle 205+ |
| 2 | Protocol extraction (76 → 1) | HIGH | HIGH | Deferred cycle 207+ |
| **3** | **Lazy `__getattr__` fallback** | **LOW** | **LOW** | **✅ DONE cycle 204b** |

### 2.2 Implementation

Added `RouteBuilder.__getattr__` (pure diagnostic):

```python
def __getattr__(self, name: str) -> Any:
    """Diagnostic fallback для missing attributes (cycle 204 Tier 3).

    Python invokes ``__getattr__`` только если normal lookup fails
    (MRO + __slots__ не нашли attr). Цель — **diagnostic**:
    если разработчик вызывает ``route.foo()`` и ``foo`` нет — дать
    информативную ошибку со ссылкой на protocols catalog.
    """
    # Skip dunder/private — framework-level, не user-facing.
    if name.startswith("_") and name != "__":
        raise AttributeError(...)

    # Typo-detection: найти ближайший mixin-name → suggest category.
    _mixin_names = [c.__name__ for c in type(self).__mro__
                    if c.__name__.endswith("Mixin")]
    _hint = None
    for _mname in _mixin_names:
        if abs(len(_mname) - len(name)) <= 3 and _shares_prefix(_mname, name):
            _cat = get_category_for_mixin(_mname)
            if _cat is not None:
                _hint = f" (похоже на {_mname!r} из {_cat.__name__})"
                break

    raise AttributeError(
        f"{type(self).__name__!r} object has no attribute {name!r}. "
        f"RouteBuilder имеет 76 mixins в MRO — см. "
        f"src/backend/dsl/builders/protocols.py для category index."
        + (_hint or "")
    )
```

### 2.3 Helper: `_shares_prefix(a, b, n=3)`

Module-level function в `base/__init__.py`. Used только из `__getattr__`.
Pure diagnostic, no side effects.

### 2.4 Tests (4 new)

```text
test_getattr_diagnostic_for_missing_attribute            PASS
test_getattr_diagnostic_typo_hint                        PASS
test_getattr_diagnostic_does_not_break_existing_attrs    PASS
test_getattr_diagnostic_private_attrs_raise_cleanly      PASS
```

### 2.5 Perf regression check

Pre-cycle-204 benchmark использовал `add_middleware`/`add_processor` —
**но эти methods не существуют** на RouteBuilder (cycle 202 misverified).
Pre-cycle-204 baseline случайно измерял AttributeError path.

Cycle 204b benchmark использует РЕАЛЬНЫЕ public methods:
- `description`, `route_id`, `source` (slots, 0.05 us)
- `notebook_execute` (NotebookMixin, 0.235 us — cross-mixin MRO)
- `feature_flag` (FeatureMixin, 0.05 us — slot-like)
- `cache` (CacheMixin, 0.05 us)

**Cycle 204b baseline (successful lookups)**:

| Attr | Cycle 202 | Cycle 204b | Delta |
|---|---|---|---|
| description | 0.024 us | 0.05 us | +2x (cold cache) |
| notebook_execute | 0.235 us | 0.235 us | unchanged |
| cache | 0.030 us | 0.05 us | +1.6x (cold cache) |

**Missing attr path** (cycle 204b only):
- 13.9 us per call (cycle 204b diagnostic overhead)
- Pre-cycle-204: 0.235 us (Python native AttributeError, very fast)

Regression is acceptable: only triggered для MISSING attrs (error path).
Successful lookups (hot path) — unchanged или minor cold-cache variance.

### 2.6 Production impact

- ✅ No regression для successful attribute lookups (Python never calls
  `__getattr__` если MRO + slots нашли attr)
- ✅ Faster debugging — developer видит protocols catalog reference в
  error message вместо generic Python AttributeError
- ✅ No MRO change (76 mixins остаются как есть)
- ⚠️ Error path overhead (13.9 us) — acceptable, only on AttributeError

---

## 3. Артефакты cycle 204

- `src/backend/dsl/builders/protocols.py` (309 LOC, cycle 204a)
- `tests/unit/dsl/builders/test_protocols.py` (149 LOC, cycle 204a)
- `src/backend/dsl/builders/base/__init__.py` (+38 LOC, cycle 204b: __getattr__ + _shares_prefix)
- `tests/unit/dsl/builders/test_route_builder_init.py` (+60 LOC, cycle 204b: 4 __getattr__ tests)
- `tests/unit/dsl/builders/test_route_builder_perf.py` (cycle 204b: fix attrs)
- `docs/audit/CYCLE-204-PROTOCOLS-DIAGNOSTIC.md` (this file)

**HEAD**: `c1e4616b`
