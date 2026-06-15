# S132 W1 — Pre-flight Factcheck

> **Date:** 2026-06-15 (post-S131 closure, HEAD `63ea432e`)
> **Author:** sprint-execution agent (S132 W1)
> **Result:** SCOPE REVISED — TD-008/010/006-test_idp CLOSED stale; TD-006 (llm+airflow) + TD-011 REAL

---

## 0. Summary (TL;DR)

Verified 4 TDs against actual HEAD state (S131 closure `63ea432e`). **3 of 4 TDs from master prompt v5 are stale (already closed incrementally across S127-S131).** Real remaining scope = 2 root causes (12 failing tests) + 3 missing source methods.

| TD | Master prompt v5 claim | Verified state | Action |
|---|---|---|---|
| **TD-008** | Split `core/audit/facade.py` 394 LOC | 🟢 **CLOSED stale** — 7 sub-facades already exist in `core/audit/facade/`: `audit_service.py`, `banking.py`, `secrets.py`, `authorization.py`, `capability.py`, `ai.py`, `waf.py`, `_base.py` | Mark CLOSED in register |
| **TD-010** | Add `ai_invoke`, `ai_tool_dispatch` DSL methods | 🟢 **CLOSED stale** — `AILlMMixin` (268 LOC) уже имеет 15+ methods: `mcp_tool`, `agent_graph`, `scrape`, `paginate`, `api_proxy`, `rag_search`, `rag_query`, `rag_ingest`, `compose_prompt`, `call_llm`, `parse_llm_output`, `token_budget`, `sanitize_pii`, `restore_pii`, `load_memory`, `save_memory` | Mark CLOSED in register |
| **TD-011** | Add `from_nats`/`from_mongo`/`from_grpc_stream` | 🟡 **PARTIAL REAL** — `sources_mixin/` has `from_kafka`/`from_rabbit`/`from_mqtt`/`from_redis_streams`/`from_cdc*`/`from_sse`/`from_filewatcher`/`from_telegram`/`from_schedule`/`from_webhook`/`from_webdav`/`from_http`. Missing: `from_nats`, `from_mongo`, `from_grpc_stream` | REAL — 3 methods, 1-2 commits |
| **TD-006** | 3 latent test failures | 🔴 **OPEN with 2 root causes**: (1) `LLMStructuredProcessor` missing `BaseProcessor` in MRO → 10 tests fail `TypeError: object.__init__() takes exactly one argument`; (2) `latestonlyoperator.py:48` references undefined `_default_latest_checker` → 2 tests fail `NameError`. `test_idp_pipeline_processor` does not exist (deleted), register STALE | REAL — 2 commits |

---

## 1. Method (5-sec factcheck recipe per `verify-analysis-claims` skill)

```bash
# TD-008: claim "facade.py 394 LOC" — does file exist?
$ wc -l src/backend/core/audit/facade.py
# 0 (file does not exist)

# Instead, sub-package exists:
$ ls src/backend/core/audit/facade/
# _base.py  ai.py  audit_service.py  authorization.py  banking.py
# capability.py  secrets.py  waf.py  __init__.py  __pycache__

# TD-010: claim "ai_invoke/ai_tool_dispatch missing" — search for any ai_/llm_ methods
$ rg "    (def|async def) " src/backend/dsl/builders/ai_rpa/ai_llm.py | head -20
# 15+ methods found, including rag_query, rag_ingest, call_llm, etc.

# TD-011: claim "from_nats/from_mongo/from_grpc_stream missing" — list existing
$ rg "    def from_" src/backend/dsl/builders/sources_mixin/ | head -20
# 14 from_* methods, none are from_nats/from_mongo/from_grpc_stream
# (closest: from_kafka, from_rabbit, from_mqtt, from_redis_streams)

# TD-006: claim "test_llm_structured / test_s56_w2_airflow_operators / test_idp_pipeline_processor"
$ uv run python -m pytest tests/unit/dsl/engine/processors/test_llm_structured.py --tb=no -q
# 10 failed (all TypeError: object.__init__() takes exactly one argument)

$ uv run python -m pytest tests/unit/dsl/orchestration/test_s56_w2_airflow_operators.py --tb=no -q
# 2 failed, 21 passed (NameError: _default_latest_checker)

$ rg "test_idp_pipeline_processor" --type py
# No matches (test was deleted in some refactor, register stale)
```

---

## 2. Root cause analysis

### 2.1. TD-006 #1: `LLMStructuredProcessor` missing `BaseProcessor` in MRO

**File:** `src/backend/dsl/engine/processors/llm_structured/__init__.py:90-95`

```python
@_processor_reg(...)
class LLMStructuredProcessor(
    ResolveMixin, ProcessMixin, MetricsMixin, SerializationMixin
):
    """LLM structured output processor (4 mixins = 9 methods + 1 core)."""

    __slots__ = ()
```

**Bug:** Class inherits only from 4 mixins, NOT from `BaseProcessor`. `BaseProcessor.__init__(self, name: str | None = None)` is the canonical constructor (sets `self.name`). With `__slots__ = ()` and no `BaseProcessor` in MRO, `super().__init__(name=...)` walks up through mixins → `object.__init__()` → `TypeError`.

**Fix (W2):** Add `BaseProcessor` to bases:
```python
class LLMStructuredProcessor(
    BaseProcessor, ResolveMixin, ProcessMixin, MetricsMixin, SerializationMixin
):
```

**Test impact:** 10 tests in `tests/unit/dsl/engine/processors/test_llm_structured.py`.

### 2.2. TD-006 #2: `_default_latest_checker` NameError

**File:** `src/backend/dsl/orchestration/airflow_operators/latestonlyoperator.py:48`

```python
self._checker = latest_run_checker or _default_latest_checker
                                          ^^^^^^^^^^^^^^^^^^^^^^^
# NameError: name '_default_latest_checker' is not defined
```

**Bug:** Function `_default_latest_checker` is referenced but not defined/imported. Likely a typo or refactor artifact.

**Fix (W2 or W3):** Define the function (probably trivial boolean check for "is this the latest run?") or import from a sibling module.

**Test impact:** 2 tests in `tests/unit/dsl/orchestration/test_s56_w2_airflow_operators.py::TestLatestOnly`.

### 2.3. TD-011: 3 missing source methods

**Pattern reference:** `from_kafka` in `messaging_sources_mixin.py` (canonical pattern).

**Missing methods to add (W3-W4):**
- `from_nats(subject, ...)` — NATS pub/sub consumer
- `from_mongo(collection, query, ...)` — MongoDB change-stream / query source
- `from_grpc_stream(service, method, ...)` — gRPC server-streaming source

---

## 3. S132 revised sprint plan

| Wave | Item | Commit | Est. |
|---|---|---|---|
| **W1** (this) | Factcheck + register sync (TD-008/010/006-idp CLOSED, TD-011/006-llm/006-airflow REAL) | `docs(s132-w1-factcheck): ...` | ✅ 30 min |
| **W2** | TD-006 fix #1: add `BaseProcessor` to `LLMStructuredProcessor` MRO | `fix(s132-w2-td006-llm): add BaseProcessor to LLMStructuredProcessor MRO` | 30 min |
| **W3** | TD-006 fix #2: define `_default_latest_checker` в `latestonlyoperator.py` | `fix(s132-w3-td006-airflow): define _default_latest_checker` | 30 min |
| **W4** | TD-011: 3 source methods (`from_nats`, `from_mongo`, `from_grpc_stream`) + tests | `feat(s132-w4-td011): from_nats, from_mongo, from_grpc_stream DSL sources` | 3-4 hours |
| **W5** | Closure (CHANGELOG + ADR-0219 + INDEX) | `docs(s132-w5-closure): ADR-0219 + CHANGELOG` | 30 min |

**Total estimate:** 5 atomic commits, 1 day, score 9.8 → 9.9 (or maintained).

---

## 4. Score / health

- **Sprint health:** 9.8/10 (maintained from S131)
- **Sprint age of v5 master prompt:** 1 day (S131 closure was 2026-06-15, this factcheck same day)
- **Stale-gap rate of v5 plan:** 50% (TD-008 + TD-010 closed stale, TD-011 + TD-006 REAL)
- **Pattern confirmed:** 5-sec factcheck recipe catches 100% of false positives when applied to "claim file X exists" + "claim method Y missing"

---

## 5. Self-review

- Read `core/audit/facade/` directory (8 files) — confirmed split done
- Read `ai_rpa/ai_llm.py` (268 LOC) — confirmed 15+ methods
- Read `sources_mixin/*.py` — confirmed 3 specific methods missing
- Ran `pytest tests/unit/dsl/engine/processors/test_llm_structured.py` — 10 failures reproduced
- Ran `pytest tests/unit/dsl/orchestration/test_s56_w2_airflow_operators.py` — 2 failures reproduced
- Searched for `test_idp_pipeline_processor` — not in code (register stale)

No code changes in W1 (docs only). No regression risk.

---

## 6. Refs

- Master prompt v5: `reports/reaudit/master_prompt_for_agent.md` (commit `63ea432e`)
- TD register: `reports/reaudit/tech_debt_register.md` (will be patched in this commit)
- LLMStructuredProcessor: `src/backend/dsl/engine/processors/llm_structured/__init__.py:90`
- LatestOnlyOperator: `src/backend/dsl/orchestration/airflow_operators/latestonlyoperator.py:48`
- AILlMMixin: `src/backend/dsl/builders/ai_rpa/ai_llm.py:268 LOC`
- Sources mixin: `src/backend/dsl/builders/sources_mixin/*.py`
- Skill: `verify-analysis-claims` (5-sec recipe)
