# ADR-0151 — Sprint 69 closure: 2nd SWARM (3 teams) — 1 violation closed + 2 style cleanups (3 commits, 3/3 substantive, scope discipline)

* Статус: Accepted (Autonomous work cycle S69, 2026-06-12)
* Связано с: S68 (1st SWARM, 4 violations), S69 W1-W3 (this sprint)
* Context: пользователь подтвердил SWARM pattern ("также дорабатывай
  в помощью агентов") + push permission

## Контекст

S69 = **2nd SWARM EXECUTION** (3 parallel subagent teams, user continuation).
Subagent results:
- **Команда A (W1, s3.py base64)**: ⚠️ PARTIAL — created `_base64_codec.py`,
  ruff fix done, but **DID NOT update s3.py import** (subagent thought it
  did, but git diff shows the change wasn't applied to disk)
- **Команда B (W2, pydantic_ai_client)**: ⚠️ TIMEOUT at 600s (36 calls)
  — partial work: refactor done + staged in git
- **Команда C (W3, graphql/schema)**: ⚠️ TIMEOUT at 600s (31 calls)
  — partial work: refactor done, unstaged

Per `subagent-parallel-coverage-batch` skill, pitfall #49 (PIVOT RULE):
**3 subagents timeout → orchestrator finishes execution**.

**SCOPE CORRECTION в S69 W2/W3** (важная honest discovery):
- W1 — REAL violation fix (allowlist -1)
- W2/W3 — "import style cleanup" (lazy → top-level, **NOT** violation
  closure). Reason: tools/check_layers.py considers ANY import from
  reverse layer as violation (lazy or top-level, doesn't matter). Top-level
  refactor improves code quality but doesn't close the allowlist entry.

## Команда результаты (3 commits, scope-honest)

### W1: infrastructure/external_apis/s3.py base64 codec (REAL FIX)
- Commit: `f522df27`
- File: `src/backend/infrastructure/external_apis/_base64_codec.py` (NEW, 66 LOC) —
  verbatim copy of `decode_base64`/`encode_base64` from dsl/codec/base64.py
- File: `src/backend/infrastructure/external_apis/s3.py:7-12` — import
  re-redirected to local `_base64_codec` (replaces dsl reverse-dep)
- File: `tools/check_layers_allowlist.txt` — **1 stale entry REMOVED (197 → 196)**
- File: `tests/unit/infrastructure/external_apis/test_local_base64_codec.py` (NEW, 11 tests):
  basic, roundtrip, unicode, emoji, padding, API parity
- **Orchestrator fix**: subagent claimed "import updated" but git diff showed
  no change. Manually applied patch + ruff --fix + 11 tests + commit
- Verified: 11/11 NEW pass, ruff clean

### W2: core/ai/pydantic_ai_client.py gateway exceptions (STYLE CLEANUP)
- Commit: `73965cd9`
- File: `src/backend/core/ai/pydantic_ai_client.py:32-35` — added top-level
  `from src.backend.services.ai.gateway.exceptions import (GatewayRateLimited,
  GatewayUnavailable)`
- Removed 2 lazy imports ВНУТРИ `_reraise_normalized()` method
- File: `tests/unit/core/ai/test_pydantic_ai_client_exceptions.py` (NEW, 6 tests):
  exceptions raised, case-insensitive, AST verify no lazy imports
- **Honest scope**: top-level import наружу всё ещё counts as violation.
  0 stale entries удалено. Code quality improvement, not violation closure.
- **Orchestrator fix**: 3 test failures fixed (method name was
  `_normalize_litellm_exception` → actual `_reraise_normalized`; missing
  `pytest.raises` wrapper on first test)
- Verified: 6/6 NEW pass, 8/8 pre-existing pass, 0 regressions

### W3: entrypoints/graphql/schema.py 4 dsl imports (STYLE CLEANUP)
- Commit: `471e04e0`
- File: `src/backend/entrypoints/graphql/schema.py:20-23` — added 3 top-level
  dsl imports (route_registry, action_handler_registry, get_tracer)
- Removed 4 lazy imports ВНУТРИ resolver methods
- File: `tests/unit/entrypoints/graphql/test_schema_imports_top_level.py`
  (NEW, 5 tests): AST verify no lazy imports, top-level section, no
  duplicates, all names callable, get_dsl_service works
- **Honest scope**: same as W2 — 0 stale entries, code quality only
- **Pre-existing failures** в test_schema.py (8 fails) — verified NOT
  caused by W3 (git stash baseline check)
- **Orchestrator fix**: 5 NEW tests + commit (subagent already did refactor)
- Verified: 5/5 NEW pass, 0 regressions

## Fact-check: scope discipline lesson (S69 W2/W3)

**Discovery**: tools/check_layers.py treats lazy and top-level reverse
imports the same way — both count as layer violations. The "lazy → top-level"
refactor is a code quality improvement, NOT a violation fix.

**Implication for S70+**:
- Don't waste subagent effort on lazy→top-level moves if goal is "close
  violations". Need to either (a) actually remove the reverse-dep (move
  classes), or (b) accept the violation as legacy (allowlist).
- Code quality refactors have value, but should be tracked as "tech debt
  cleanup" not "violation closure".

## S69 Quality gates

- **3 substantive commits** (W1, W2, W3)
- **Allowlist**: 197 → 196 (only 1 entry closed — W1)
- **NEW tests**: 22 total (11 W1 + 6 W2 + 5 W3)
- **NEW ADR docs**: 1 (this one, 0151)
- **Subagent completion rate**: 0/3 clean (0%), 3/3 partial/timeout (100%) — even worse than S68
- **Orchestrator fix rate**: 3 fixes (W1: import not applied, W2: 3 test failures, W3: nothing — subagent done)
- **0 production regressions**

## S70+ backlog (S69 honest scope)

- **TD-S65-W4 remaining 121 dsl/workflow violations** (L, S70+ P1 epic):
  - **REAL closure strategy**: move classes из dsl/ в core/infrastructure,
    либо accept as legacy (allowlist)
  - **Style cleanup strategy**: lazy → top-level (zero value for violation
    closure, but improves code quality)
- **TD-S65-W2 remaining 33 core→other violations** (M, S70+)
- **Pre-existing bugs** (XS): event_log.py:164 Python 2 syntax (TD-S68)
- **Stale-allowlist cleanup** (S): проверять при каждом refactor

## Lessons learned

1. **2nd SWARM pattern activation** — пользователь продолжил pattern
   (S68 → S69), subagent completion rate ещё хуже (0/3 vs 1/3 в S68).
   **Рекомендация**: для лучшего success rate делать SAMPLE refactor
   tasks smaller (1 file max, <5 LOC change). Большие SAMPLE tasks
   exhausted budget на pre-work.

2. **Subagent "claimed done" vs actually done** — W1 subagent сказал
   "import updated" в summary, но git diff не показал изменений. **Verify
   via `git diff` BEFORE trusting subagent's verbal claim**. Это частный
   случай pitfall #13 (sibling untracked files).

3. **Top-level vs lazy import equivalence для layer check** — W2/W3
   discovery: top-level imports наружу всё ещё count as violations.
   Re-define "violation closure" как "remove reverse-dep" not
   "change import style".

4. **Soft reset + re-commit pattern** — после messy commits (W1 overreach
   в original sequence), `git reset --soft HEAD~N` + careful `git add`
   files gives clean atomic commits. Лучше чем amending multiple times.

5. **Method name guess failures** — W2 subagent (и мой orchestrator
   follow-up) guessed `_normalize_litellm_exception`, но actual name
   was `_reraise_normalized`. **Always read source file before writing
   tests** (pitfall #54 from skill). AST-based introspection safer.

6. **Subagent 0/3 clean rate** — все 3 subagents в S69 exhausted budget.
   Pattern: при увеличении sprint number, subagent success rate
   падает (предположительно, более сложные tasks). Возможный fix:
   ещё более narrow scope, OR direct orchestrator execution for
   "known trivial" tasks.
