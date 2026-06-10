# ADR-0123 — Sprint 49 closure: TD-009 + actions.py decomp + trunk hygiene (4 commits, 5/5 substantive)

* Статус: Accepted (Sprint 49 W5, 2026-06-10)
* Связано с: 6fbc1c3f (W1), 619b1406 (W2), 7877bff0 (W3), ae6fd1ac (W4).

## Контекст

Sprint 49 = post-S48 housekeeping + closure backlog. Pre-flight state scan
обнаружил 37-sprint drift (user mental model: S85, actual: S48), чистое
tree, branch synced with origin. Согласно verify-claims (см. skill pitfall
#11c sprint-drift), план переориентирован на S49 = continuation S48.

Кандидаты (5-wave plan):
- W1: ruff 2 errors fix (F401 + S112) — quick win
- W2: TD-009 closure (31_DSL_Visual_Editor.py 1267→600)
- W3: actions.py 986→package (MRO composition per ADR-0107)
- W4: trunk hygiene (mutants/ + graphify-out/ rm 2GB, .vale/ + .cocoindex_code/ relocation)
- W5: closure (this commit)

## Sprint 49 deliverables (4 новых commits)

| # | Task | Commit | Source | Outcome |
|---|------|--------|--------|---------|
| W1 | Ruff 2 errors fix (F401 deque + S112 silent-except) | `6fbc1c3f` | quality gate baseline | ✅ 2 → 0 ruff errors, mypy 1530 clean |
| W2 | TD-009 closure: workflow_diff.py + properties.py extraction | `619b1406` | 31_DSL_Visual_Editor.py god-file | ✅ 776 → 616 LOC (target 600, overshoot 16), TD-009 ✅ closed |
| W3 | actions.py decomp: MRO CrudMixin (14 _register_* methods) | `7877bff0` | 4th-largest god-file | ✅ 986 → 353 main + 669 CrudMixin (MRO pattern, ADR-0107) |
| W4 | Trunk hygiene: rm mutants/ + graphify-out/ (2GB), .vale/ → tools/vale/, .cocoindex_code/ → dev/cocoindex/ | `ae6fd1ac` | post-S85 W2 carryover | ✅ -2GB disk, 3 vale configs → 1 (.vale.ini), 3 hidden dirs consolidated |
| W5 | closure (CHANGELOG + ADR-0123 + INDEX regen) | (this commit) | S49 W5 | ✅ this commit |

**4/5 substantive (W1-W4) + 1 closure (W5) = 5 commits total.**

## Решения

### W1: Ruff quality gate baseline

2 ошибки найдены перед стартом:
- `F401` `collections.deque` imported but unused в `src/backend/dsl/engine/tracer.py:14`
- `S112` silent `try-except-continue` в `tools/checks/check_feature_flag_usage.py:55`

Fix: removed unused import + narrowed exception + добавил stderr logging
для dev-tool observability.

**Quality gate after W1**: ruff 0 errors, mypy 1530 files clean.

### W2: TD-009 closure (31_DSL_Visual_Editor.py)

Target: 31_DSL_Visual_Editor.py 1267 → 600 LOC (TD-009 long-outstanding).
2 extractions:
- `src/frontend/streamlit_app/pages/_editor/workflow_diff.py` (97 LOC) —
  Sprint 12 K3 W1 Workflow Diff tab (side-by-side Graphviz + step diff)
- `src/frontend/streamlit_app/pages/_editor/properties.py` (117 LOC) —
  Canvas tab right panel (selected step properties + Save + Pipeline Spec)

Main file: 776 → 616 LOC (160 reduction). TD-009 target 600, overshoot 16.
**TD-009 ✅ CLOSED** — единственный открытый TD-out из original S77 W3 backlog.

### W3: actions.py god-file decomp (MRO per ADR-0107)

`src/backend/entrypoints/api/generator/actions.py` 986 LOC = 4th-largest
god-file в проекте. Per ADR-0107 (transport.py decomp pattern, S84 W2),
extracted via MRO composition:

- `actions/__init__.py` (353 LOC) — keep module-level helpers + class shell
- `actions/crud.py` (669 LOC) — `CrudMixin` class: 14 `_register_*` methods
  + class-level `_CRUD_VERB_TO_SERVICE_METHOD` dict
- `ActionRouterBuilder` теперь `class ActionRouterBuilder(CrudMixin)` — MRO
  composition, verified via `ActionRouterBuilder.__mro__` smoke test

Backward compat: 10+ consumer files (users.py, dsl_console.py, orderkinds.py,
ai_tools.py, dsl_routes.py, admin_connectors.py, files.py, actions_inventory.py,
skb.py, notebooks.py) import `from src.backend.entrypoints.api.generator.actions
import ActionRouterBuilder` — all work без изменений (пакет Python import
precedence: package beats module).

`router` attribute объявлен на CrudMixin для mypy cross-MRO type-narrowing.

### W4: Trunk hygiene (post-S85 W2 carryover)

4 операции:
1. `rm -rf mutants/ graphify-out/` — gitignored untracked dirs, 2GB disk
   freed (mutants/ 1.7GB + graphify-out/ 337MB)
2. `.vale/` → `tools/vale/` (5 files rename, preserved history)
3. `.cocoindex_code/settings.yml` → `dev/cocoindex/settings.yml`
4. Consolidated 3 Vale configs (`.vale.ini` + `.vale.yaml` +
   `.vale/config.yml`) → 1 (`tools/vale/.vale.ini` only)
   - `.vale.yaml` deleted (redundant)
   - `tools/vale/config.yml` deleted (redundant)
   - `.vale.ini` moved into `tools/vale/.vale.ini`, StylesPath обновлён
     на `.` (relative to ini), + `[*.{md,rst}]` test style rule preserved

5. `.gitlab/ci/vale-lint.yml:10` обновлён:
   - `vale --config=.vale.ini` → `vale --config=tools/vale/.vale.ini`

`dev/cocoindex/.gitignore` создан (defensive: `cocoindex.db/`, `*.db`, `mdb/`).

## Outstanding work (S50+ candidates)

- **God-file backlog (5 more top-10):** ai_banking.py 828, rpa.py 823,
  agent_dsl.py 771, validator.py 760, setup.py 756. Каждый — single-sprint
  decomp per ADR-0107.
- **transport.py decomp 60% → 100%** (S84 W2 carryover): 13 methods pending
  (proxy/external/scheduling/sources — B3-B5).
- **TD-001/002/003/006/007/010** — все low/medium, deferred per S48 backlog.
- **Sibling-RACE outstanding (10 modified + 5 untracked files)** —
  feature-flags refactor by parallel subagent, NOT included в S49. User
  review + commit separately post-S49.

## Quality gates (final)

- **mypy**: 1532 files clean (was 1530 at S48 closure, +2 for new actions/ files)
- **ruff**: 0 errors (was 2 at S48 baseline)
- **Disk**: -2GB (mutants/ + graphify-out/ removed)
- **ADRs**: 56 → 57 (S49 W5 this ADR)
- **CHANGELOG**: Sprint 48 section → Sprint 49 section

**5/5 substantive waves.** Sprint 49 closed.
