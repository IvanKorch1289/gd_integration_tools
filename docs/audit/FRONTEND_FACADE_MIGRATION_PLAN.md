# FRONTEND FACADE MIGRATION PLAN — 2026-08-14

**HEAD**: `2532c9b` (cycle 205)
**Status**: 1/16 high-priority files migrated (template proven). 14/16 blocked on backend endpoints.

---

## Scope

**31 файла** в `src/frontend/streamlit_app/` импортируют из `src.backend.core.frontend_facade`.

Per boundary rule (DEEP_AUDIT_REPORT.md R3.10d): frontend не должен импортировать `services/*` или `infrastructure/*` напрямую. `frontend_facade` re-exports из `services.dsl_portal` (workflow/AI сервисы) — это layer violation.

## Analysis (Этап 2)

Все 31 импорт идут через `src.backend.core.frontend_facade`. Из них:

- **17 uses** (6 files) — `core/*` symbols: `feature_flags`, `emit_audit_safe`, `get_logger`, `express_settings`. ✅ **Это core symbols, не layer violation** (core может быть импортирован).
- **14 uses** (в 14 файлах) — `services.dsl_portal` symbols: `get_saga_history`, `get_saga_stats`, `get_ai_cost_snapshot`, `get_dsl_builder_service`, `get_default_stuck_monitor`, `get_global_registry`, `get_whoosh_index`, `list_audit_records`, `list_recent_trace_events`, `list_route_ids`, `list_workflow_templates`, `get_import_service`, `compute_step_diff`, `load_pipeline_from_yaml`. ❌ **Layer violation, нужна миграция**.

## Migration strategy

**Use existing HTTP API clients** (P6 thin-client pattern) — `src/frontend/streamlit_app/api_clients/` уже содержит `WorkflowsClient`, `AdminClient`, etc. Если backend endpoint не существует → нужно его добавить в `src/backend/entrypoints/api/v1/endpoints/`.

## Progress (Этап 3)

### ✅ DONE: `19_Saga_Компенсации.py`

- Removed `from src.backend.core.frontend_facade import get_saga_history`
- Added `from src.frontend.streamlit_app.api_clients import get_api_client`
- Replaced `asyncio.run(get_saga_history(wf_id, limit=100))` → `client.workflows.get_saga_history(wf_id, limit=100)`
- `get_saga_stats` → TODO (no HTTP equivalent yet, returns empty dict)
- `asyncio` import removed (no longer needed)
- Lint: All checks passed
- Python import smoke test: PASS

### ⏳ TODO: 14 files (blocked on HTTP client coverage)

| # | File | Service symbols | HTTP client method | Status |
|---|---|---|---|---|
| 1 | `34_DSL_Отладчик.py` | `list_route_ids`, `list_recent_trace_events`, `list_audit_records` | NONE | blocked |
| 2 | `_groups/schema/import_tab.py` | `get_import_service` | NONE | blocked |
| 3 | `_groups/dsl/dsl_templates/workflow_templates_tab.py` | `list_workflow_templates` | NONE | blocked |
| 4 | `33_DSL_Шаблоны.py` | `list_workflow_templates` | NONE | blocked |
| 5 | `_editor/workflow_diff.py` | `compute_step_diff`, `get_global_registry` | NONE | blocked |
| 6 | `_editor/properties.py` | `load_pipeline_from_yaml` | NONE | blocked |
| 7 | `_editor/visual/tab_canvas.py` | `load_pipeline_from_yaml` | NONE | blocked |
| 8 | `_editor/yaml_sync.py` | `Pipeline`, `load_pipeline_from_yaml` | NONE | blocked |
| 9 | `23_AI_Учёт_затрат.py` | `get_ai_cost_snapshot` | NONE | blocked |
| 10 | `18_Версионирование_Воркфлоу.py` | `get_global_registry` | NONE | blocked |
| 11 | `63_Вики.py` | `get_whoosh_index` | NONE | blocked |
| 12 | `96_Монитор_зависших_сообщений.py` | `get_default_stuck_monitor` | NONE | blocked |
| 13 | `32_DSL_Конструктор.py` | `get_dsl_builder_service` | NONE | blocked |
| 14 | `15_Оценка_стоимости_Workflow.py` | `get_global_registry` | NONE | blocked |
| - | `17_Replay_Воркфлоу.py` (already) | `get_saga_history` | `WorkflowsClient.get_saga_history` ✓ | same as #1 above |

## What's needed to unblock

11 service symbols → 11 missing HTTP client methods → 11 missing backend endpoints.

### Backend endpoints to add (in `src/backend/entrypoints/api/v1/endpoints/`)

```
GET  /api/v1/admin/workflows/registry/all-ids       → get_global_registry
GET  /api/v1/admin/ai/cost/snapshot                → get_ai_cost_snapshot
GET  /api/v1/admin/dsl/builder-service             → get_dsl_builder_service
GET  /api/v1/admin/dsl/templates                    → list_workflow_templates
GET  /api/v1/admin/dsl/whoosh-index                 → get_whoosh_index
GET  /api/v1/admin/audit/events                    → list_audit_records
GET  /api/v1/admin/audit/recent-events             → list_recent_trace_events
GET  /api/v1/admin/routes/available                 → list_route_ids
GET  /api/v1/admin/dsl/import-service              → get_import_service
POST /api/v1/admin/dsl/diff                        → compute_step_diff
POST /api/v1/admin/dsl/load-pipeline               → load_pipeline_from_yaml
GET  /api/v1/admin/outbox/stuck-monitor            → get_default_stuck_monitor
```

(12 endpoints; some can be combined.)

### Frontend client methods to add (in `src/frontend/streamlit_app/api_clients/`)

Each endpoint above needs a corresponding client method on the appropriate client class (`WorkflowsClient`, `AdminClient`, `DSLClient`, etc.) — `def get_saga_history(...)`, etc.

## Recommendation

This is a **multi-session refactor**:
1. **Session 1**: Add 12 backend endpoints (small changes, mostly wrapping existing service functions)
2. **Session 2**: Add 12 client methods (1-line each after endpoints exist)
3. **Session 3+**: Migrate 14 files (one commit per file, smoke-test each)

Estimated effort: 1-2 days of focused work, NOT one turn.

## Alternative: simplify with `frontend_facade` → `core.api` consolidation

A more focused refactor: keep `frontend_facade` (rename to `core.frontend`), move the services re-exports to `core.api` as documented in cycle 29 (P1-#1 master prompt). Then:
- `core.api` becomes the canonical facade for ALL backend symbols (core + services)
- `frontend_facade` becomes thin re-export from `core.api`
- 31 files continue to use `frontend_facade` but it now points to `core.api` internally
- Zero file migrations needed

**Tradeoff**: violates the "extensions use sdk + core.api, NEVER services" rule (by extending core.api to include services). But for FRONTEND (not extension) the rule doesn't strictly apply.

Decision: present both options to user for sign-off before next session.
