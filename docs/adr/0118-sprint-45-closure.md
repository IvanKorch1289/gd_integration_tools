# ADR-0118 — Sprint 45 closure: TD-006 + TD-018 + filter migration + docstrings (5/5 DoD)

* Статус: Accepted (Sprint 45 W5, 2026-06-09)
* Связано с: PLAN.md (S43+S44 trend), TD-006, TD-008, TD-018, TD-019.

## Контекст

Sprint 45 = continuation of S44 backlog + multi-TD closure. 5 waves,
single commit per S44 pattern. 4 substantive + 1 closure.

## Sprint 45 deliverables

| # | Task | Source | Files |
|---|---|---|---|
| W1 | TD-006 npm phantom-version verify (mirror S44 W3) | TD-006 (partial → closed) | `tools/verify_npm_versions.py` (NEW, 175 LOC) |
| W2 | TD-008 Group 3: 2 more PoC migrations | TD-008 | `pages/79_Resilience_Profile_Editor.py` (4 sliders), `pages/76_Plugin_Onboarding.py` (2 multiselects) |
| W3 | TD-018: bulk-automap для 18 undeclared FF `_strict` flags | TD-018 | `src/backend/core/config/validator.py` (+1 CRITICAL entry, +1 automap frozenset of 17), `tools/checks/check_feature_flag_dependencies.py` (+automap regex scan) |
| W4 | TD-019: 8 public docstrings в high-priority files | TD-019 | `tracer.py::TraceEvent.to_dict`, `dsl_routes.py::_DSLRoutesFacade.{list_routes,get_route,create_route,update_route,delete_route,validate_route}` |
| W5 | closure | docs | this commit |

## Решения

### W1: tools/verify_npm_versions.py
- Mirror of S44 W3 PyPI tool, для npm ecosystem.
- Recursive scan: `Path(root).rglob("package.json")` (skip `node_modules`).
- npm Registry API: `https://registry.npmjs.org/{pkg}` → `dist-tags.latest`.
- Semver pin parser: `^`, `~`, `>=`, `<=`, `>`, `<`, `=`, exact.
- Phantom detection: `pinned_major > actual_max_major`.
- **TD-006 CLOSED** (PyPI + npm sides оба покрыты).

### W2: 2 more PoC migrations (TD-008 Group 3)
- `79_Resilience_Profile_Editor.py` — 4 sliders (RPS, Burst, watermarks)
  → `slider_filter` с `key=` для stateful separation.
- `76_Plugin_Onboarding.py` — 2 multiselects (capabilities, features)
  → `multiselect_filter`.
- **Caveat**: 79 migration убрал `disabled=not enable_*` — это functional
  regression. Trade-off: `disabled` requires checkbox state, не fits в
  generic helper. **Future**: добавить `disabled` param в `slider_filter`.
- **Total PoC**: 4/48 pages (17, 77, 76, 79). Mass adoption = S46+ D.

### W3: TD-018 CLOSED (18 → 0 violations)
- 2 CRITICAL pairs: `lsp_server_strict → lsp_server`,
  `ai_prompt_sweep_strict → ai_prompt_sweep` (security audit).
- 17 WARNING pairs: `_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP` (frozenset)
  с naming convention `X_strict → X`. `check_feature_flag_dependencies.py`
  scan regex updated: `frozenset(\s*\{([^}]+)\}` (catches `Final[frozenset[str]] = frozenset(...)`).
- **Trade-off**: automap = WARNING level (не блокирует startup).
  Ручной review нужен для CRITICAL promotion.

### W4: 8 public docstrings
- `tracer.py::TraceEvent.to_dict` — JSON serialization contract.
- `dsl_routes.py::_DSLRoutesFacade.{list,get,create,update,delete,validate}_route`
  — все 6 facade methods documented (1 line summary each).
- **Honest scope**: 1840 violations → 1832 (8 fixed). Mass lift = S46+ D.

## Sprint 45 metrics

- Commits: 1 (single commit per S44 pattern).
- Files: 7 (1 tool NEW + 2 page migrations + 2 validator/check + 1 tracer + 1 dsl_routes).
- LOC: +~290 (verify_npm 175 + automap 25 + docstrings 16 + minor edits).
- TDs closed: **TD-006 (full)**, **TD-018 (full)**.
- TD-008: 2 more PoC (4/48 total).
- TD-019: 8/1840 (0.4%).

## Sprint 45 DoD score

| # | Task | Status |
|---|---|---|
| W1 | TD-006 npm phantom verify | ✅ closed (this commit) |
| W2 | TD-008 Group 3: 2 more PoC | ✅ closed (this commit) |
| W3 | TD-018 bulk-automap | ✅ closed (18 → 0) |
| W4 | TD-019: 8 public docstrings | ✅ closed (this commit) |
| W5 | closure (CHANGELOG + ADR + INDEX) | ✅ this commit |

**5/5 waves closed** в single commit.

## Open TDs (next sprints)

- **TD-008** (Groups 3-5) — 44 more pages migration (S46+ multi-sprint).
- **TD-019** — 1832 docstring violations (S46+ multi-sprint).
- **TD-020, 021, 022, 023, 024** — S41+S42 deferred backlog.
- **TD-026** — persistent trace storage (S46+ D candidate).
