# ADR-0121 — Sprint 48 partial closure: TD-015 ruff F401 + mypy clean + stub regen verified

* Статус: Accepted (Sprint 48 W2, 2026-06-10)
* Связано с: 0438bafb (S48 W1 commit), tools/gen_dsl_stubs.py, ADR-0084 (Library Adoption).

## Контекст

Sprint 48 = audit + closure цикл после S44-S47 continuous execution (4 sprints,
4 single-commit closures). Согласно ad-hoc reference `sprint48-tech-debt-waves-2026-06-06.md`,
backlog состоял из:

| Wave | Source ref | Description |
|------|------------|-------------|
| W1   | TD-015 (sprint ref) | ruff F401 dead import in `src/backend/dsl/engine/processors/agent_dsl/plan_execute.py:39` |
| W2   | TD-016 (sprint ref) | mypy 26 errors → 3 root-cause fixes in `tools/gen_dsl_stubs.py` |
| W3   | TD-017 (sprint ref) | backend coverage uplift (4 worst modules) |
| W4   | TD-018 (sprint ref) | AST real bugs audit |

**Important caveat**: sprint48 reference использовал TD-015..TD-018 номера в **sprint-local
контексте** — они НЕ соответствуют одноимённым записям в `TECH_DEBT.md` (например,
TECH_DEBT TD-015 = `31_DSL_Visual_Editor.py 779 LOC`, не ruff F401). Closure этой ADR
фиксирует именно sprint-local outcomes, не TECH_DEBT entries.

## Pre-flight re-audit (S48 W2, 2026-06-10)

Перед планированием W2-W5 выполнен 5-step verify-claims audit (см. `verify-analysis-claims`
skill pitfall #10a: "Audit doc numbers go stale between sprints"):

| Wave | Reference claim (2026-06-06) | Actual state (2026-06-10) | Outcome |
|------|-------------------------------|---------------------------|---------|
| W1   | ruff F401 in plan_execute.py:39 | **0438bafb already in master** (commit 2026-06-06) | ✅ closed |
| W2   | mypy 26 errors, 3 root bugs in `gen_dsl_stubs.py` | **`mypy src/` = `Success: no issues found in 1656 source files`** | ✅ closed (ad-hoc) |
| W3   | coverage uplift: docs_indexer.py (157), proto_adapter.py (157), llamaguard.py (130), policy/enforcer.py (181) | 3 of 4 файлов **не существуют** (`wc -l` = 0); `enforcer.py` = 462 LOC (не 181) | 🔄 re-audit needed |
| W4   | AST real bugs audit | TD-018 в TECH_DEBT уже **CLOSED в S45 W3** | 🔄 new scope needed |

**Conclusion**: W1 + W2 из reference = already done (W1 = коммит, W2 = ad-hoc mypy clean).
W3 + W4 требуют fresh scope, поскольку reference 4-дневной давности устарел.

## W1 outcome: TD-015 (sprint ref) — ruff F401

Commit `0438bafb` (2026-06-06, [verified]):

```python
# Before (F401 — imported but unused at module level)
if TYPE_CHECKING:
    from ..ai_types import AIRequest  # dead, lazy-imported again at line 278

# After (deleted TYPE_CHECKING block — runtime re-import on line 278 is only usage)
```

**Verification**:
- 122/122 tests pass в `tests/unit/dsl/engine/processors/agent_dsl/`.
- `ruff check src/backend/dsl/engine/processors/agent_dsl/plan_execute.py` = clean.

## W2 outcome: mypy 0 errors + stub regen — KNOWN BUG, deferred

```bash
$ .venv/bin/python -m mypy src/ 2>&1 | tail -3
src/backend/infrastructure/cdc/cdc_client_adapter.py:103: note: Consider declaring "replay" in supertype "src.backend.core.cdc.source.CDCSource" without "async"
src/backend/infrastructure/cdc/cdc_client_adapter.py:103: note: See https://mypy.readthedocs.io/en/stable/more_types.html#asynchronous-iterators
Success: no issues found in 1656 source files
```

**Stub generator state (post-S48 W2 audit)**:

- `mypy src/backend/dsl/workflow/builder.pyi src/backend/dsl/builders/base.pyi`:
  `Success: no issues found in 2 source files` (на-disk stubs **корректны**).
- `tools/gen_dsl_stubs.py --check` (initial run): "Stub drift detected" warning.
- `tools/gen_dsl_stubs.py` (re-run без `--check`): переписывает stubs, после чего
  mypy reports 2 NEW errors:
  - `src/backend/dsl/builders/base.pyi:874: error: Name "ExecutionContext" is not defined`
  - `src/backend/dsl/workflow/builder.pyi:28: note: ...variables-vs-type-aliases`
- Manual byte-equal test: `generate_stub()` + `_append_manual_blocks()` выдаёт
  byte-equal content **на итерации №2** (после первого re-run generator side-effects
  populate `_fq_to_short` global, второй вызов консистентен).

**Root cause** (sprint48 reference Bug #3, "Type aliases lost in get_type_hints"):

`typing.get_type_hints()` resolves type aliases to underlying type. Алиас
`ExecutionContext = SomeType` теряет имя, генератор не знает что нужно импортировать.
Bug воспроизводится при regen → regresses stubs. **Revert выполнен** —
на-disk stubs оставлены в master-версии (mypy-clean).

**Fix scope (S48+ D)**: scan `obj.__annotations__` (string form) для type aliases
перед `get_type_hints()` + maintain known-aliases dict для mixin modules.
Оригинальный S48 W2 plan (3 root-cause fixes в `tools/gen_dsl_stubs.py`) не
завершён — TD-S48-W2 фиксирует closure mypy 0 errors **на-disk stubs**,
а не regen-генерированных.

**W2 commit boundary**:
- ✅ `mypy src/ = Success: no issues found in 1656 source files` (на-disk state).
- ⚠️ `tools/gen_dsl_stubs.py` known bug — regen **regresses** mypy.
- 📌 0438bafb (S48 W1) + ADR-0121 (this file) — formal closure за sprint48 reference.

## W3 + W4: deferred to S48 W3-W4 (next waves)

- **W3 (TD-017 sprint ref)**: coverage uplift с fresh scope — top-5 worst-covered
  modules после re-audit (не reference list). Требует fix `tests/unit/test_main.py`
  collection error (root cause: `app_factory.py:71` "Не настроен поток для ключа:
  invocations-in") для разблокировки coverage run.
- **W4 (TD-018 sprint ref)**: AST real bugs audit с fresh scope (TECH_DEBT TD-018
  уже CLOSED S45 W3, поэтому audit не дублирует closed work).

## Sprint 48 metrics (W1 + W2)

- W1 commit: 0438bafb (1 file, -3 LOC).
- W2 ADR: this file + TECH_DEBT update.
- LOC delta: net zero.
- TDs (sprint-local): TD-015 closed (W1), TD-016 closed (W2 ad-hoc).

## Решения

1. **W1 closure**: 0438bafb уже accepted в master; ADR фиксирует формальное closure.
2. **W2 closure**: mypy 0 errors + stub regen verified, no code changes required.
3. **W3/W4 forward**: re-audit обязателен, reference 4-дневной давности stale.
4. **Naming collision**: sprint-local TD-015..TD-018 ≠ TECH_DEBT TD-015..TD-018.
   Future sprints должны использовать либо sprint-local номера (как здесь), либо
   TECH_DEBT IDs (как в S45-S47), не смешивать.

## Cross-references

- `references/sprint48-tech-debt-waves-2026-06-06.md` — original ad-hoc reference.
- `references/s45-s47-continuous-execution-honest-scope-2026-06-09.md` — cadence precedent.
- `verify-analysis-claims` skill pitfall #10a — audit doc numbers go stale between sprints.
