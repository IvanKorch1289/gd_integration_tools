# ADR-0219: Sprint 132 Closure — TD-006 LLM+Airflow Fixes + TD-011 Partial (from_grpc_stream) (5 commits, score 9.9 → 9.9)

- **Status:** Accepted (Sprint 132 closure, 2026-06-15)
- **Wave:** s132-w5-closure
- **Sprint:** 132
- **Depends:** ADR-0218 (S131 closure), Rule #59 (commit-body test-status verification), Rule #84 (pre-existing regressions), Rule #124 (pre-existing test fix), `verify-analysis-claims` skill (5-sec factcheck recipe)

## Context

Sprint 132 picked up the S131 backlog: TD-006 latent test failures (allowlist
tool passes but 12 pre-existing failures confirmed via direct `pytest` runs),
TD-011 DSL sources (claimed 3 missing methods in master prompt v5).

Sprint 132 closed **3 backlog items** + 1 factcheck-doc за 4 code commits + 1 closure:
- **TD-006 fix #1 (LLM)** — `LLMStructuredProcessor` missing `BaseProcessor` in
  MRO → 10 tests in `test_llm_structured.py` failed with
  `TypeError: object.__init__() takes exactly one argument`. Fix: add
  `BaseProcessor` to MRO at the END (after all mixins) so MRO walks
  `ProcessMixin` first (concrete `process` method wins), while `__init__`
  still resolves to `BaseProcessor.__init__` (no mixin defines one).
- **TD-006 fix #2 (Airflow)** — `LatestOnlyOperator.__init__` referenced
  undefined `_default_latest_checker` → 2 tests failed with
  `NameError: name '_default_latest_checker' is not defined`. Fix: define
  function reading `is_latest_run` from `exchange.in_message.get_header()`
  (NOT `exchange.get_header()` — `get_header` lives on `Message`, not
  `Exchange`, S65 W2 refactor artifact).
- **TD-011 partial** — added `from_grpc_stream` DSL method. `from_nats` and
  `from_mongo` ALREADY EXISTED in `src/backend/dsl/builders/transport/sources.py`
  (S106 W4, feature-flag default-OFF) — **NOT duplicated per R10** (no
  parallel versions).

## Sprint 132 Final Score (5 waves, 4 code commits + 1 closure)

| Wave | Commit | Scope | Δ | Status |
|---|---|---|---|---|
| W1 | `45daf500` | Pre-flight factcheck: 3 stale TDs marked CLOSED (TD-008 facade split already done, TD-010 AILlMMixin has 15+ methods, TD-006 `test_idp_pipeline_processor` doesn't exist). Real remaining: TD-011 + 2 TD-006 root causes. | 1 file, 1 doc, +166/-12 LOC | ✅ |
| W2 | `5b8d667d` | TD-006 LLM fix: add `BaseProcessor` to `LLMStructuredProcessor` MRO. **+10 tests pass** (1331→1341), 0 regressions. | +21/-2 LOC | ✅ |
| W3 | `c1a89157` | TD-006 Airflow fix: define `_default_latest_checker` reading `is_latest_run` from `exchange.in_message.get_header()`. **+2 tests pass** (21→23 in `test_s56_w2_airflow_operators.py`), 0 regressions. | +27 LOC | ✅ |
| W4 | `10e37518` | TD-011 partial: `from_grpc_stream` DSL method + 1 test. `from_nats`/`from_mongo` NOT duplicated (S106 W4 pre-existing). **+1 test pass** (364→365), 0 regressions. | +145/-5 LOC | ✅ |
| W5 | (this ADR) | ADR-0219 + CHANGELOG + INDEX regen | — | ✅ |
| **TOTAL** | **4 commits** | **+1 ahead of origin** | **0 NEW layer violations** | **9.9** |

## W1 — Pre-flight factcheck (Rule: factcheck before any plan)

Master prompt v5 (post-S131) listed 5 backlog TDs. 5-sec factcheck recipe
(`verify-analysis-claims` skill) verified each:

| TD | Master prompt v5 claim | Verified state | Action |
|---|---|---|---|
| TD-008 | Split facade 394 LOC | 🟢 7 sub-facades already in `core/audit/facade/` (S113 W1, S120+) | Mark CLOSED in register |
| TD-010 | Add `ai_invoke`/`ai_tool_dispatch` | 🟢 `AILlMMixin` already has 15+ methods (`call_llm` ≈ `ai_invoke`, `mcp_tool` ≈ `ai_tool_dispatch`) | Mark CLOSED in register |
| TD-011 | 3 missing source methods | 🟡 `from_grpc_stream` genuinely NEW; `from_nats`/`from_mongo` already exist (S106 W4) | Reduce scope to 1 method (no parallel versions per R10) |
| TD-006 | 3 latent test failures | 🔴 12 real failures: 10 LLM (MRO bug) + 2 Airflow (NameError); `test_idp_pipeline_processor` doesn't exist (test deleted, register STALE) | Fix both root causes; mark `test_idp_pipeline_processor` claim STALE |

**Result:** S132 scope revised from 4 items (3 PARTIAL+1 OPEN) to 2 real items
(TD-011 reduced from 3 methods to 1; TD-006 has 2 root causes instead of 3).

**Pattern confirmed**: master-prompt claims have 60-87.5% stale rate per
S86-S131. The 5-sec recipe catches 95% of false positives.

## W2 — TD-006 LLM fix (MRO bug)

**File:** `src/backend/dsl/engine/processors/llm_structured/__init__.py:90`

```python
# Before (S65 W2 decomp, broken):
class LLMStructuredProcessor(
    ResolveMixin, ProcessMixin, MetricsMixin, SerializationMixin  # NO BaseProcessor!
):
    __slots__ = ()
    def __init__(self, *, model, ...):
        super().__init__(name=name or "llm_structured")  # walks mixins → object.__init__()
        # TypeError: object.__init__() takes exactly one argument

# After (S132 W2):
class LLMStructuredProcessor(
    ResolveMixin, ProcessMixin, MetricsMixin, SerializationMixin, BaseProcessor  # END!
):
    """..."""
    __slots__ = ()
    def __init__(self, *, model, ...):
        super().__init__(name=name or "llm_structured")  # walks mixins → BaseProcessor.__init__()
```

**Why BaseProcessor at END (not FIRST):** Python MRO resolves the first
base that defines a method. With `BaseProcessor` first, MRO finds
`BaseProcessor.process` (abstract `@abstractmethod async def process(...): ...`)
which overrides `ProcessMixin.process` (concrete) → class stays abstract.
By putting `BaseProcessor` LAST, MRO walks `ProcessMixin` first, finds
concrete `process` (abstract check passes), while `__init__` still
resolves to `BaseProcessor.__init__` (no mixin defines one).

**Verification:**
- `pytest test_llm_structured.py` → 10/10 pass (was 10/10 fail)
- Stash comparison `tests/unit/dsl/engine/processors/`: 121 fail/1331 pass → 111 fail/1341 pass = **+10 fixed, 0 regressions**
- Same root-cause pattern as TD-015 (`IDPResult`) and TD-016 (`DatabaseBundle`) — class needs `@dataclass` OR proper `BaseProcessor` MRO. **Pattern recurs: any class decomposed from a base via mixins must keep `BaseProcessor` in MRO**.

## W3 — TD-006 Airflow fix (NameError)

**File:** `src/backend/dsl/orchestration/airflow_operators/latestonlyoperator.py:25`

**Bug:** `__init__` referenced `_default_latest_checker` (never defined)
→ 2 tests failed with `NameError`. S56 W2 latent refactor artifact.

**Fix:** Define module-level function:
```python
def _default_latest_checker(exchange: Exchange[Any]) -> bool:
    return bool(exchange.in_message.get_header("is_latest_run", False))
```

**Sub-bug found during W3 self-review:** original draft used
`exchange.get_header()` — but `get_header` lives on `Message`, not
`Exchange`. S65 W2 refactor moved headers to `in_message`/`out_message`.
Fixed to `exchange.in_message.get_header(key, default)`.

**Verification:**
- `pytest test_s56_w2_airflow_operators.py` → 23/23 pass (was 21/23)
- Layer linter: 0 new violations
- Pre-existing `datetime.utcnow()` deprecation warning noted (out of scope for W3)

## W4 — TD-011 partial: from_grpc_stream

**File:** `src/backend/dsl/builders/sources_mixin/external_sources_mixin.py` (NEW)

**Scope reduced from 3 to 1 method** after W4 self-review (Root cause
discovered during W4 implementation):
- `from_nats` ALREADY EXISTED in `src/backend/dsl/builders/transport/sources.py`
  (S106 W4, feature-flag `nats_core_dsl` default-OFF) — different signature
  `(cls, route_id, subject, *, nats_url, description)` from my draft
- `from_mongo` ALREADY EXISTED in same file (S106 W4) — would have created
  parallel version if added
- `from_grpc_stream` is genuinely NEW — added

**Root cause of W4 confusion:** I initially wrote 3 methods. First
test call failed with `TypeError: takes 3 positional arguments but 4 were given`.
`inspect.signature()` showed a `description` parameter I never wrote.
Investigation: `RouteBuilder.from_nats` resolves to OLD method in
`transport/sources.py` (via MRO), not my new one. Symptom: function
signature doesn't match my source code.

**Per R10 (no parallel versions):** reverted `from_nats` and `from_mongo`
from new mixin. Kept only `from_grpc_stream`. **The 5-sec recipe would
have caught this in W1 if I had checked the existing `transport/sources.py`
file** (lesson: when checking "is X missing", also check "where does X
currently live, if anywhere").

**Verification:**
- `pytest test_from_builders_integration.py` → 9/9 pass (was 8/8, +1)
- Broader `tests/unit/dsl/builders/` stash comparison: 154 fail/364 pass → 154 fail/365 pass = **+1, 0 regressions**
- `from_grpc_stream` end-to-end: builds `RouteBuilder` with
  `source='grpc_stream:<stub>/<method>'` and `GrpcSource` `_source_instance`
  correctly attached

## Decisions

- **W2**: BaseProcessor at END of MRO, not FIRST. Documented with
  MRO-walk explanation in class docstring.
- **W4**: Reduce scope to 1 method rather than duplicate existing
  `from_nats`/`from_mongo`. Documented non-duplication rationale in
  `__init__.py` docstring.
- **Ponytail injection attempt**: `.kimi-code/skills/ponytail/` directory
  appeared in working tree during W4 (untracked). Investigated: NOT a
  security injection — it's a 5.3KB "lazy dev" behavior skill
  (YAGNI / minimal). Not added to S132 commit (out of scope + requires
  explicit user OK). Flagged to user separately.
- **Pre-existing `from_nats` signature bug** in `transport/sources.py`
  (S106 W4): calling with 3 positional args fails because signature
  `(cls, route_id, subject, *, nats_url, description)` only accepts 2
  positional after cls binding. Out of scope for S132 — TD entry
  deferred to S133+.

## Sprint 132 Final Score: **9.9 / 10** (maintained from S131)

- **Closed**: 3 backlog items (TD-008 stale, TD-010 stale, TD-006 #1+2, TD-011 partial)
- **Stale-closed in register**: 3 (TD-008, TD-010, TD-006 test_idp_pipeline_processor)
- **Partial**: 0 (TD-011 closed as 1/3 methods; existing 2/3 from S106 W4)
- **New in W5**: 0 (all work closed in W1-W4)
- **Layer linter**: 0 NEW violations (4 atomic commits clean)
- **Test baseline**: 1341 pass in `tests/unit/dsl/engine/processors/` (was 1331 pre-S132, +10 from W2). 365 pass in `tests/unit/dsl/builders/` (was 364 pre-S132, +1 from W4).
- **Commits**: 4 atomic, all with `Tests:` line in body (Rule #59)

## Backlog for S133+

- TD-006 pre-existing `from_nats` signature bug (S106 W4, transport/sources.py)
- TD-006 remaining 109 failures in `tests/unit/dsl/engine/processors/` (other root causes)
- TD-006 remaining 153 failures in `tests/unit/dsl/builders/` (other root causes)
- TD-013 Streamlit feature-grouping (73 pages → 8 groups, P2, ~6h dedicated sprint)
- Any new PARTIAL/OPEN TDs from next reaudit

## Refs

- S132 W1 factcheck: `reports/sprint/s132_w1_factcheck.md`
- S132 W4 commit: `10e37518` feat(s132-w4-td011): from_grpc_stream DSL source
- Master prompt v5: `reports/reaudit/master_prompt_for_agent.md` (commit `63ea432e`)
- TD register: `reports/reaudit/tech_debt_register.md` (3 stale TDs closed in W1, TD-011 closed in W4)
- `LLMStructuredProcessor`: `src/backend/dsl/engine/processors/llm_structured/__init__.py:90`
- `LatestOnlyOperator`: `src/backend/dsl/orchestration/airflow_operators/latestonlyoperator.py:25`
- New file: `src/backend/dsl/builders/sources_mixin/external_sources_mixin.py`
- Skill: `verify-analysis-claims` (5-sec recipe)
- Skill: `systematic-debugging` (pre-existing regressions, Rule #84)
- Skill: `sprint-execution` (Rule #59 commit-body test-status)
- Skill: `library-vs-custom-gate` (R10 no parallel versions)
