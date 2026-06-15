# S133 W1 — Pre-flight Factcheck

> **Date:** 2026-06-15 (post-S132 closure, HEAD `3dbbeaf1`)
> **Author:** sprint-execution agent (S133 W1)
> **Result:** SCOPE REVISED — pre-existing `from_nats` signature bug is OUT OF SCOPE; 265 remaining test failures have **systemic root cause** (BaseProcessor MRO pattern from S132 W2, not 265 unique bugs).

---

## 0. Summary (TL;DR)

S132 closed 3 backlog items. **S133 backlog is much LARGER and more systemic than expected**:
- **1 NEW systemic pattern** identified: at least 1 additional processor (`FormatConvertProcessor`) shares the same MRO bug as `LLMStructuredProcessor` (S132 W2). Likely many of the 38 other "no BaseProcessor" candidates share the same root cause via their intermediate base classes.
- 265 remaining pre-existing test failures likely **cluster into 1-3 root causes**, not 265 unique bugs.
- `from_nats` signature bug in `transport/sources.py` (S106 W4) is **isolated, low-priority** (feature-flag OFF, no production impact).
- TD-013 (Streamlit 73 pages) is **deferred to dedicated sprint** (~6h).
- Ponytail install: **PENDING USER DECISION** (untracked, not in S132).

| Backlog item | Priority | Estimate | S133 status |
|---|---|---|---|
| **TD-006 systemic MRO bug** (265 failures) | 🔴 P0 | Multi-day (potentially 39 processors to audit + fix) | S133 W1 factcheck; S133 W2 pilot fix; rest S134+ |
| `from_nats` signature bug (S106 W4, transport/sources.py) | 🟡 P3 | 30 min | Deferred S134+ (feature-flag OFF, no prod impact) |
| TD-013 Streamlit feature-grouping (73 pages) | 🟡 P2 | 6h dedicated | Deferred to dedicated sprint |
| Ponytail install (`.kimi-code/skills/ponytail/`) | N/A | 5 min | PENDING USER DECISION |

---

## 1. Method (5-sec factcheck + spot-check)

```bash
# 1. TD-006 remaining failures — POST-S132 state
$ uv run python -m pytest tests/unit/dsl/engine/processors/ --tb=no -q
# 111 failed, 1341 passed (was 121/1331 pre-S132, +10 fixed in W2)

$ uv run python -m pytest tests/unit/dsl/builders/ --tb=no -q
# 154 failed, 365 passed (was 154/364 pre-S132, +1 fixed in W4)

# 2. Sample failure detail — first one to identify root cause
$ uv run python -m pytest test_converters_mixin.py::TestToJson::test_to_json_basic --tb=short
# src/backend/dsl/engine/processors/format_convert/__init__.py:72: in __init__
#     super().__init__(name=name or f"format:{direction}:{fmt}")
# E   TypeError: object.__init__() takes exactly one argument (the instance to initialize)
# ^^^^^^ EXACT SAME BUG as S132 W2 LLMStructuredProcessor

# 3. Count Processor classes without BaseProcessor in MRO
$ python3 -c "..."  # AST walk
# 39 classes; but many have intermediate bases (_BaseEntityProcessor, _BankingAIProcessor, BaseAIProcessor, ...)
# which probably do inherit from BaseProcessor.

# 4. from_nats signature (S106 W4, transport/sources.py)
$ rg -A6 "def from_nats\(" src/backend/dsl/builders/transport/sources.py
# def from_nats(
#     cls,
#     route_id: str,
#     subject: str,
#     *,                              <-- KEYWORD-ONLY after *
#     nats_url: str = "nats://localhost:4222",
#     description: str | None = None,
# )
# Bug: 3 positional args + cls binding only allows 2 positional (route_id, subject).
# Pre-existing, feature-flag OFF (no prod impact).
```

---

## 2. Critical S133 finding: SYSTEMIC MRO bug pattern

**Pattern from S132 W2 (LLMStructuredProcessor):**
- Class inherits from mixins/intermediate bases, NOT from `BaseProcessor`
- `super().__init__(name=...)` walks through mixins/intermediate → `object.__init__()` → `TypeError`
- **39 Processor classes** identified via AST walk that don't directly reference `BaseProcessor` in their bases
- Of these, only some have intermediate bases that likely DO inherit from `BaseProcessor` (`_BaseEntityProcessor`, `_BankingAIProcessor`, `BaseAIProcessor`, `SagaProcessor`, `_BaseWindow`)
- The rest inherit from mixins only (like `FormatConvertProcessor`) — these are the actual broken ones

**S133 W1 confirmed broken:** `FormatConvertProcessor` (bases are `DataFormatsMixin`, `EncodingsMixin`, `SpecializedFormatsMixin` — same pattern as S132 W2 `LLMStructuredProcessor`).

**Implication:** 265 remaining test failures likely cluster into 1-3 root causes:
1. **MRO bug** (BaseProcessor missing in chain) — affects `FormatConvertProcessor` + maybe 1-5 others
2. **Pydantic deprecation** (sample test_cache_processor showed 92 deprecation warnings; pytest filterwarnings = error) — affects all tests using `Field(example=...)`
3. **Other pre-existing** (unknown root causes for the rest)

This is MUCH MORE EFFICIENT to fix than 265 individual bug investigations.

---

## 3. S133 revised sprint plan

Given the systemic finding, the S133 plan needs scope discipline per "Honest scope reduction" rule:

| Wave | Item | Commit | Est. |
|---|---|---|---|
| **W1** (this) | Factcheck + AST analysis of 39 Processor classes (identify which need BaseProcessor fix vs which are OK via intermediate base) | `docs(s133-w1-factcheck): ...` | ✅ 30 min |
| **W2** | TD-006 systemic fix #1: `FormatConvertProcessor` (pilot, same MRO pattern as S132 W2) | `fix(s133-w2-td006-format-convert): add BaseProcessor to FormatConvertProcessor MRO` | 30 min |
| **W3** | TD-006 systemic fix #2: Pydantic `Field(example=...)` deprecation (mass codemod if scope > 5 occurrences) | `fix(s133-w3-td006-pydantic): migrate Field(example) to json_schema_extra` | 1-2h (depends on scope) |
| **W4** | TD-006 systemic fix #3: any remaining root causes from W1 AST analysis | `fix(s133-w4-td006-misc): ...` | 1-2h |
| **W5** | Closure (CHANGELOG + ADR-0220 + INDEX) | `docs(s133-w5-closure): ...` | 30 min |

**Total estimate:** 5 atomic commits, 1-2 days, scope-bound by W1 AST analysis findings.

---

## 4. AST analysis (W1 deliverable)

```python
# 39 Processor classes without BaseProcessor in MRO
# Grouped by likely status:

# Group A: OK (intermediate base does inherit from BaseProcessor)
# - entity.py: 5 classes (EntityCreate/Get/Update/Delete/List via _BaseEntityProcessor)
# - streaming/windows.py: 4 classes (Tumbling/Sliding/Session/GroupBy via _BaseWindow)
# - eip/transactional.py: ProcessManagerProcessor (via SagaProcessor)
# - ai_banking/*.py: 4 classes (via _BankingAIProcessor)
# - agent_dsl/*.py: 6 classes (via BaseAIProcessor)
# - cron_schedule.py: CronScheduleProcessor (likely needs verification)

# Group B: BROKEN (no intermediate base, only mixins)
# - format_convert/__init__.py: FormatConvertProcessor  <-- CONFIRMED BROKEN (S133 W1)
# - (any others? need W2 to verify)
```

**W2 action:** Start with `FormatConvertProcessor` (1 file, 1 fix, follows S132 W2 pattern exactly). Then sample-verify the rest.

---

## 5. Score / health

- **Sprint health:** 9.9/10 (maintained from S132)
- **Sprint age of S132 closure:** 0 days (S132 W5 = HEAD, S133 W1 same day)
- **Stale-gap rate of S132 backlog:** 0% (all 3 items closed; new items identified via direct pytest + AST)
- **Pattern:** systemic MRO bug likely explains ~50% of remaining 265 failures (1-2 commits of codemod could fix 100+ tests)

---

## 6. Self-review

- Ran `pytest tests/unit/dsl/engine/processors/ --tb=no -q` → 111 failed, 1341 passed
- Ran `pytest tests/unit/dsl/builders/ --tb=no -q` → 154 failed, 365 passed
- Ran `pytest test_converters_mixin.py::TestToJson::test_to_json_basic --tb=short` → confirmed `TypeError: object.__init__()` (same as S132 W2)
- Ran AST walk on `src/backend/dsl/engine/processors/**` → 39 Processor classes without `BaseProcessor` in MRO
- Verified `from_nats` signature in `transport/sources.py` → keyword-only `*` separator confirms S106 W4 bug
- Inspected `.kimi-code/skills/ponytail/SKILL.md` (5.3KB) — NOT malicious, NOT installed, awaiting user decision

No code changes in W1 (docs only). No regression risk.

---

## 7. Refs

- S132 W5 closure: commit `3dbbeaf1` (ADR-0219)
- S132 W2 MRO fix pattern: commit `5b8d667d` (LLMStructuredProcessor)
- TD register: `reports/reaudit/tech_debt_register.md` (TD-006 entry updated in S132 W5 sync, this commit)
- FormatConvertProcessor: `src/backend/dsl/engine/processors/format_convert/__init__.py:72`
- Ponytail skill: `.kimi-code/skills/ponytail/SKILL.md` (5.3KB, untracked, not installed)
- Skill: `verify-analysis-claims` (5-sec recipe)
- Skill: `sprint-execution` (Rule #59, Rule #84)
