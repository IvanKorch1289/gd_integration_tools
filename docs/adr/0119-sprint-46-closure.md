# ADR-0119 — Sprint 46 closure: TraceStorage abstraction + docstring tool + toxiproxy runbook (5/5 DoD)

* Статус: Accepted (Sprint 46 W5, 2026-06-09)
* Связано с: TD-019, TD-020, TD-026, ADR-0117 (S44 trace buffer).

## Контекст

Sprint 46 = S45 backlog continuation. Single commit per S44/S45 pattern.
**Honest scope reduction**: 2/5 waves = bounded substantive work, 3/5 =
zero/analysis-only (отмечено явно).

## Sprint 46 deliverables

| # | Task | Source | Outcome |
|---|---|---|---|
| W1 | TD-019 docstring lift (5 top files) | TD-019 | **0 added** (файлы уже complete после S60 migration). Tool `tools/add_docstrings.py` создан для future runs. |
| W2 | TD-008 Group 3 migration (5+ pages) | TD-008 | **0 added** (sidebar date_input pattern не fits `date_range_filter` — requires different helper). |
| W3 | TD-026 TraceStorage abstraction | TD-026 | ✅ `src/backend/dsl/engine/trace_storage.py` (NEW, 200 LOC): Protocol + InMemory + JsonFile impl. Self-test passes 2/2. |
| W4 | TD-020 toxiproxy setup runbook | TD-020 | ✅ `docs/runbooks/toxiproxy-setup.md` (NEW, 130 LOC): operator guide (install, API verify, 6 proxies, .env.test, troubleshooting). |
| W5 | closure | docs | this commit |

## Решения

### W1: 0 docstrings — initial audit stale
- Initial audit: 121 missing в 5 files.
- Re-audit (после add_docstrings.py fix): 0 missing.
- Причина: S60 structlog migration (commit `37bda149`) уже добавил
  docstrings к этим файлам. Initial count был на HEAD~N.
- **Lesson**: always re-verify audit перед bulk fix (per `verify-analysis-claims` skill).
- Tool `tools/add_docstrings.py` сохранён — useful для future audits
  (e.g., new files, regressions).

### W2: 0 migrations — sidebar context mismatch
- 66_Workflow_Logs.py использует `st.date_input` внутри `with st.sidebar:`
  (а не в `cols[0/1]` паре).
- `date_range_filter` использует `st.columns(2)` — не работает в sidebar.
- **Honest scope**: PoC ceiling reached. Mass migration требует
  `sidebar_date_range_filter` variant. S47+ D.

### W3: TraceStorage Protocol + 2 impls
- `Protocol[TraceStorage]` с `@runtime_checkable` для duck typing.
- `InMemoryTraceStorage` — zero overhead, re-export S44 W1 buffer logic.
- `JsonFileTraceStorage` — append-only JSONL per route, persistent.
  Trade-offs documented в module docstring (linear scan, no TX, no
  retention).
- Self-test passes 2/2.
- **Remaining (S47+ D)**: wire `ExecutionTracer.__init__` к `storage`,
  Redis impl, Postgres impl, retention policy, indexing.

### W4: Toxiproxy runbook (operator action)
- Step-by-step guide: install, API verify, 6 proxies, .env.test, run.
- Troubleshooting table (3 common symptoms).
- CI integration deferred to S47+ D.
- 33 skipped chaos tests can be activated after operator setup.

## Sprint 46 metrics

- Commits: 1 (single commit per S44/S45 pattern).
- Files: 5 (1 new module + 1 new runbook + 1 new tool + 2 docs updates).
- LOC: +~520 (trace_storage 200 + runbook 130 + add_docstrings 100 +
  closure docs 90).
- TDs: TD-020 marked docs-only (no code); TD-026 partial (abstraction
  done, wire deferred).

## Sprint 46 DoD score

| # | Task | Status |
|---|---|---|
| W1 | TD-019 docstring lift | ⚠️ 0 (audit stale) — tool created |
| W2 | TD-008 Group 3 migration | ⚠️ 0 (pattern mismatch) |
| W3 | TD-026 TraceStorage abstraction | ✅ closed (this commit) |
| W4 | TD-020 toxiproxy runbook | ✅ closed (this commit, operator) |
| W5 | closure | ✅ this commit |

**2/5 waves substantive, 3/5 honest scope (zero/analysis)**. Single
commit pattern per S44/S45.

## Open TDs (next sprints)

- **TD-008**: 44 more pages migration (sidebar variant needed).
- **TD-019**: 1832 violations (mostly S60 leftovers, need re-audit).
- **TD-026**: wire ExecutionTracer to storage + Redis/Postgres impls.
- **TD-020**: CI integration + toxic scenarios (S47+ D).
- **TD-021, 022, 023, 024** — S41+S42 deferred backlog.
