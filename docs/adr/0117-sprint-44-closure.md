# ADR-0117 — Sprint 44 closure: Backend Wiring + Admin Build Fix (4/5 DoD)

* Статус: Accepted (Sprint 44 W5, 2026-06-09)
* Связано с: PLAN.md §6 (S42 trend), TD-006, TD-007, TD-008, TD-025, TD-026.

## Контекст

Sprint 44 = continuation of S42+S43 DX + maintenance. **Single commit**
per user instruction (vs atomic-per-wave в S40-S43). 5 waves planned
(S42 W4a TODO + TD-006 + TD-025 + W2 migrations + closure), 4 substantive
+ 1 closure = 1 финальный commit.

## Sprint 44 deliverables

| # | Task | Source | Files |
|---|---|---|---|
| W1 | Route Debugger backend wiring (S42 W4a TODO) | 35_Route_Debugger.py TODO | `src/backend/dsl/engine/tracer.py` (+60 LOC: ring buffer + `get_recent_traces` + `list_traced_routes`), `src/backend/entrypoints/api/v1/endpoints/dsl_routes.py` (+ActionSpec + `get_route_traces` facade method), `src/frontend/streamlit_app/api_clients/dsl_routes.py` (+`get_dsl_route_traces`), `src/frontend/streamlit_app/pages/35_Route_Debugger.py` (rewrite 159 → 211 LOC, demo data → real fetch) |
| W2 | TD-008 Group 3: 2-nd PoC migration | TECH_DEBT TD-008 | `src/frontend/streamlit_app/pages/77_Processor_Catalog.py` (text_search wrapper, 1 LOC swap) |
| W3 | TD-006 phantom-version verify script | TECH_DEBT TD-006 | `tools/verify_pypi_versions.py` (NEW, 188 LOC: PyPI JSON API + version tuple compare + `--strict` mode) |
| W4 | TD-025 tsconfig.node.json missing | TECH_DEBT TD-025 | `frontend/admin-react/tsconfig.node.json` (NEW, 11 LOC: composite + bundler module resolution) |
| W5 | closure (CHANGELOG + ADR-0117 + INDEX regen) | docs | this commit |

## Решения

### W1: tracer ring buffer + endpoint
- `ExecutionTracer._trace_buffer: dict[route_id → deque[TraceEvent]]` —
  in-memory ring buffer (maxlen=1000 per route).
- Append на `_emit` для phase ∈ {"end", "error"} (start events не нужны
  в replay — start всегда парный с end).
- `get_recent_traces(route_id, limit)` — chronological order (oldest first).
- `list_traced_routes()` — для будущего dashboard "all routes".
- Endpoint `GET /api/v1/admin/dsl-routes/{route_id}/traces?limit=N` через
  `ActionSpec` (W26.5 pattern).
- Frontend: `DSLRoutesClient.get_dsl_route_traces()` (timeout-safe fallback
  to demo data).
- **Persistent storage = TD-026 (S45+ D)** — нужен Redis или PostgreSQL
  для cross-restart history.

### W2: 2-nd PoC migration
- `77_Processor_Catalog.py` — 1-LOC swap: `st.text_input("Search query")`
  → `text_search("Search query", placeholder=...)`. Trim whitespace +
  type-safe default.
- **Honest scope reduction**: S43 W2 + S44 W2 = 2 PoC migrations total
  (17 + 77). Полная миграция 48 pages = multi-sprint work (~10 waves).
  Каждая страница имеет unique context (sidebar, cols, callbacks), что
  делает aggressive migration risky. **Pattern first**, mass adoption later.

### W3: tools/verify_pypi_versions.py
- PyPI JSON API client (urllib stdlib, 5s timeout).
- Парсит pyproject.toml через tomllib.
- Regex `_PIN_RE` для package[extras] op_version (>=, <=, ==, !=, >, <, ~=).
- Version tuple compare: `'1.5.20' > '1.5.9'` → True (lex ignore suffixes).
- Exit 0 по умолчанию, exit 1 на `--strict` mode.
- Network errors → graceful "SKIP" warnings (не fatal).
- **npm scope deferred to S45+ D** (TD-006 partial closure).

### W4: admin-react tsconfig.node.json
- 11 LOC, Vite-recommended config (composite + bundler).
- **Verification**: `npm run build` PASSES (29 modules, 637ms, 148 KB JS).
- TD-025 CLOSED.

## Sprint 44 metrics

- Commits: 1 (single commit per user instruction, this is the closure).
- LOC: +460 (tracer +60, endpoint +30, api_client +18, page 35 +52,
  page 77 +1, verify_pypi +188, tsconfig.node +11, W5 docs +100).
- Pages migrated: 1 / 47 (TD-008 Group 3 second PoC).
- TD-025: CLOSED (admin-react build passes).
- TD-026: spawned (persistent trace storage, S45+ D).
- TD-006: partial closure (PyPI side done, npm side deferred).
- New endpoints: 1 (`GET /admin/dsl-routes/{id}/traces`).
- New tool: `tools/verify_pypi_versions.py`.

## Sprint 44 DoD score

| # | Task | Status |
|---|---|---|
| W1 | Route Debugger backend wiring | ✅ closed (this commit) |
| W2 | TD-008 Group 3 2-nd PoC | ✅ closed (this commit) |
| W3 | TD-006 phantom-version verify (PyPI) | ✅ closed (this commit) |
| W4 | TD-025 tsconfig.node.json | ✅ closed (this commit, build verified) |
| W5 | closure (CHANGELOG + ADR + INDEX) | ✅ this commit |

**5/5 waves closed** (в single commit per user instruction).

## Open TDs (next sprints)

- **TD-006** (partial) — npm phantom version verify (S45+ D).
- **TD-008** (Groups 3-5) — 47 pages migration (S45+ multi-sprint).
- **TD-018, 019, 020, 021, 022, 023, 024** — S41+S42 deferred backlog.
- **TD-026** (S44 spawned) — persistent trace storage (Redis/PostgreSQL).
