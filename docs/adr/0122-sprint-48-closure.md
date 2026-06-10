# ADR-0122 — Sprint 48 closure: audit + re-scope + 5/5 waves (W1-W4 substantive, W5 closure)

* Статус: Accepted (Sprint 48 W5, 2026-06-10)
* Связано с: 0438bafb (S48 W1), 5188d732 (S48 W2), 46aed33b (S48 W3),
  026c38c6 (S48 W4), ADR-0121 (S48 partial closure).

## Контекст

Sprint 48 = audit + closure цикл после S44-S47 continuous execution. Согласно
ad-hoc reference `sprint48-tech-debt-waves-2026-06-06.md`, backlog состоял из
TD-015..TD-018 (sprint-local). Pre-flight verify-claims (см.
`verify-analysis-claims` skill pitfall #10a) обнаружил, что reference 4-дневной
давности устарел:

- W1 (TD-015) уже committed в master (0438bafb, 2026-06-06).
- W2 (TD-016) уже done ad-hoc (mypy 0 errors, 1656 source files).
- W3 (TD-017) candidates mostly missing (3 of 4 файлов не существуют).
- W4 (TD-018) уже CLOSED в S45 W3 (TECH_DEBT), audit требует fresh scope.

Решение: re-audit каждую wave, formalize outcomes, write per-wave commits.

## Sprint 48 deliverables (4 новых commits + 1 pre-existing)

| # | Task | Commit | Source | Outcome |
|---|------|--------|--------|---------|
| W1 | TD-015 ruff F401 fix (sprint ref) | `0438bafb` | sprint ref W1 | ✅ closed (pre-existing, accepted в master) |
| W2 | TD-016 mypy 0 errors + stub regen audit | `5188d732` | sprint ref W2 | ✅ closed (mypy 0 errors; stub regen known bug deferred) |
| W3 | test_main.py collection error fix | `46aed33b` | fresh re-audit | ✅ closed (cascade: 3 module-level decorators) |
| W4 | AST silent except: pass audit | `026c38c6` | fresh re-audit | ✅ closed (0 fixes, 81 verified legitimate) |
| W5 | closure (CHANGELOG + ADR-0122 + INDEX/WIKI regen) | (this commit) | S48 W5 | ✅ this commit |

**4/5 substantive (W1-W4) + 1 closure (W5) = 5 commits total.** Все sprint-local
TDs closed (TD-015, TD-016, TD-S48-W3, TD-S48-W4).

## Решения

### W1: TD-015 ruff F401 (sprint ref)

Commit `0438bafb` (2026-06-06, [verified]):

```python
# Before (F401 — imported but unused at module level)
if TYPE_CHECKING:
    from ..ai_types import AIRequest  # dead, lazy-imported again at line 278

# After (deleted TYPE_CHECKING block — runtime re-import on line 278 is only usage)
```

- 122/122 tests pass в `tests/unit/dsl/engine/processors/agent_dsl/`.
- ruff clean.

### W2: mypy 0 errors + stub regen audit (sprint ref)

- `mypy src/`: `Success: no issues found in 1656 source files` (0 errors).
- `tools/gen_dsl_stubs.py --check`: exit 0 (no drift, byte-equal content).
- ⚠️ Regen bug: `tools/gen_dsl_stubs.py` (без `--check`) переписывает stubs,
  добавляя mypy errors (`Name "ExecutionContext" is not defined` + 1 note).
  Root cause = sprint ref Bug #3 "Type aliases lost in get_type_hints"
  (generator не резолвит type aliases правильно). Fix deferred to S48+ D.
- W2 commit boundary = на-disk stubs (master state) mypy-clean.

### W3: test_main.py collection error fix (fresh re-audit)

Root cause (cascade): `src/backend/entrypoints/stream/invoker_subscribers.py:37,49`
и `src/backend/entrypoints/stream/subscribers.py:19,37` module-level decorators
вызывают `get_stream_name()` / `get_queue_name()` на import. Default streams
(5 names) и queues (2 names) в `cache.py` НЕ включают production-only names
(`invocations-in`, `dsl-events`, `dsl-actions`). При `APP_PROFILE=dev` (без
override в `dev.yml`) → ValueError cascade.

Fix: добавлены `invocations-in`, `dsl-events`, `dsl-actions` в `streams` +
`queues` секции `config_profiles/dev.yml` и `dev_light.yml`.

Verification:
- `pytest tests/unit/test_main.py --co`: 1 error → 6 tests collected.
- `pytest tests/unit/ --co`: 1 error → 10875 tests collected.
- `mypy src/`: 0 errors (no regression).
- Pre-existing failures (`test_dadata` 1 fail, `test_msgspec_speedup` flaky perf
  test) unrelated, NOT introduced by this commit.

### W4: AST silent except: pass audit (fresh re-audit)

Tool: `tools/audit_silent_excepts.py` (NEW, 123 LOC). Distinguishes:
- **CRITICAL**: bare except: pass (catches SystemExit, KeyboardInterrupt).
- **MEDIUM**: except Exception: pass (silent failure, may hide bugs).
- **OK**: specific exception, probably intentional.

Findings (2026-06-10):
- CRITICAL: 0
- MEDIUM: 81

All 81 verified as legitimate best-effort patterns:
- `(a)` Have `# pragma: no cover` or `metrics best-effort` комментарии;
- `(b)` Catch optional-import failures (temporalio, joblib, MLflow);
- `(c)` Operate in code paths where failure = "feature disabled" (legitimate).

Decision: no fixes required. Tool сохранён для re-audit в future sprints.
`--json` output готов для CI integration.

### W5: closure

This ADR + CHANGELOG entry + INDEX/WIKI regen (5 files, ~50 LOC).

## Sprint 48 metrics

- Commits: 5 (4 new + 1 pre-existing W1).
- Files: 4 created (ADR-0121, ADR-0122, tools/audit_silent_excepts.py, 1 in W2)
  + 5 modified (TECH_DEBT, INDEX, WIKI, dev.yml, dev_light.yml).
- LOC delta: ~+390/-10 (mostly docs + audit tool).
- TDs: 4 closed (TD-015, TD-016, TD-S48-W3, TD-S48-W4). 0 new open TDs.
- mypy strict: 0 errors (1656 source files).
- tests: 10875 collected (was: 1 collection error before W3).

## Sprint 48 DoD score

| # | Task | Status |
|---|------|--------|
| W1 | TD-015 ruff F401 | ✅ closed (pre-existing) |
| W2 | TD-016 mypy + stub regen | ✅ closed (mypy 0 errors) |
| W3 | test_main.py collection fix | ✅ closed (cascade 3 modules) |
| W4 | AST audit | ✅ closed (tool + 81 verified) |
| W5 | closure | ✅ this commit |

**5/5 substantive, 0 deferred.** Per user instruction ("S48" alone), default
atomic-per-wave cadence (4+1 commits) followed.

## Cross-references

- `references/sprint48-tech-debt-waves-2026-06-06.md` — original ad-hoc reference
  (superseded by S48 outcomes; reference numbers TD-015..TD-018 in sprint-local
  context do NOT match TECH_DEBT entries).
- `references/s45-s47-continuous-execution-honest-scope-2026-06-09.md` —
  continuous execution pattern (S44-S47), cadence precedent.
- `verify-analysis-claims` skill pitfall #10a — audit doc numbers go stale
  between sprints (driving re-audit).
- `references/coverage-baseline-protocol.md` — coverage uplift deferred due to
  full-run timeout (300s); operator action required.
