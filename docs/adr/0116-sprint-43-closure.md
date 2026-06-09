# ADR-0116 — Sprint 43 closure: Streamlit Filters + Vite Cleanup (2/5 DoD)

* Статус: Accepted (Sprint 43 W5, 2026-06-09)
* Связано с: PLAN.md §6 (S42 DX trend), TD-007, TD-008.

## Контекст

Sprint 43 = continuation of DX trend from S42. Не было §7 в PLAN.md
(последний spec — §6 S42). Scope выбран из TECH_DEBT backlog:
- **TD-007** (low) — vite-env.d.ts HTML pollution fix.
- **TD-008** (medium) — streamlit dup groups, Group 3 (filter+search).
- **TD-025** (low, spawned by W1) — admin-react tsconfig.node.json missing.

Plus candidates: TD-006 (phantom version), S42 W4a TODO (Route Debugger
backend), WAF-coverage. **Honest scope reduction**: 5 candidate tasks,
3 chosen + closure = 4 commits planned, 3 actually landed (2 + closure).

## Sprint 43 deliverables

| # | Task | Wave | Commit | Files |
|---|---|---|---|---|
| 1 | TD-007 vite-env.d.ts fix (HTML → triple-slash) | W1 | `4925e1e6` | `frontend/admin-react/src/vite-env.d.ts` |
| 2 | TD-008 Group 3: shared/filters.py + PoC migration | W2 | `f1e69f94` | `shared/filters.py` (NEW, 191 LOC), `shared/__init__.py`, `pages/17_Workflow_Replay.py` |
| 3 | Closure: CHANGELOG + ADR-0116 + INDEX regen | W5 | (this commit) | `CHANGELOG.md`, `docs/adr/0116-...md`, `docs/adr/INDEX.md`, `docs/adr/WIKI.md` |

## Решения

### W1: TD-007 root cause
- `vite-env.d.ts` содержал HTML template (copy-paste bug из S19 K5 W5c).
- Fix: заменён на canonical `/// <reference types="vite/client" />`
  (1 строка).
- Verification: `npm run build` всё ещё fails на **отдельной** проблеме
  (TD-025 — `tsconfig.node.json` missing), не на TD-007.
- **Honest scope reduction**: не фиксил TD-025 в этом commit — это
  separate task, не блокирует production (admin-react — MVP, not deployed).

### W2: shared/filters.py
- 5 light wrappers around `st.text_input`, `st.multiselect`,
  `st.date_input`, `st.selectbox`, `st.slider`.
- Russian-first labels, type-safe defaults, optional `key=`.
- **Не** пытаются enforce единый UX (filter chips, persisted state) —
  это намеренно: каждая страница сохраняет свой context.
- PoC migration: `17_Workflow_Replay.py::_render_event_filters`
  (-11 LOC inline boilerplate → +2 LOC helper calls).

### W3, W4: deferred to S44+
- **W3 (Route Debugger backend integration)**: требует wiring
  `src/frontend/streamlit_app/pages/35_Route_Debugger.py` →
  `src/backend/dsl/engine/tracer.py` + new FastAPI endpoint
  `GET /api/v1/dsl/traces/{route_id}` + tests. Estimate: 1 wave.
- **W4 (TD-006 phantom-version verify script)**: требует
  `tools/check_dependencies.py` extension с PyPI/npm registry verify.
  Estimate: 1 wave.

## Sprint 43 metrics

- Commits: 2 (W1 + W2) + 1 closure (this) = 3.
- LOC: +220 (filters.py 191 + 13 import + 7 page) / -20 (page boilerplate).
- Pages migrated: 1 / 48 (2% of TD-008 Group 3).
- TD-007: CLOSED.
- TD-008: partial closure (1 page, 47 to go).
- TD-025: spawned, deferred to S44+.
- New tests: 0 (filters.py — runtime-only, требует streamlit extra).

## Sprint 43 DoD score

| # | Task | Status |
|---|---|---|
| W1 | TD-007 vite-env.d.ts fix | ✅ closed (`4925e1e6`) |
| W2 | TD-008 Group 3: filters.py + PoC | ✅ closed (`f1e69f94`) |
| W3 | Route Debugger backend wiring | ⏭️ deferred S44+ |
| W4 | TD-006 phantom-version verify | ⏭️ deferred S44+ |
| W5 | closure (CHANGELOG + ADR + INDEX) | ✅ this commit |

**2/5 waves closed, 3 deferred to S44+** (honest scope reduction).

## Next (S44+)

Per backlog:
1. **S44 W1**: Route Debugger backend integration (W3) — bounded.
2. **S44 W2**: TD-008 Group 3 full migration (47 pages) — multi-wave.
3. **S44 W3**: TD-006 phantom-version verify script (W4) — bounded.
4. **S44 W4**: TD-025 tsconfig.node.json missing — bounded.
5. **S44 W5**: closure.

Or alternate scope per user direction (e.g., Jupyter DSL S45+).
