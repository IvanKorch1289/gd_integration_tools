# Sprint 12 — Workflow Enhancement (closure summary 2026-05-20 16:25)

**HEAD после закрытия**: `07667d89 [wave:s12/k4-w1-ai-workflow-examples-lib]`
**Сессия**: coordinator-self без worktree-агентов.
**Wave-таблица**: 17/17 wave + 1 backbone + 1 closure = **19 commits**.

## Что сделано

### Backbone
`[wave:s12/backbone-features]` — 18 feature-flags в `features.py` (S12 секция) + 5 секций `team_s12.k1..k5` в `.claude/team-ownership.toml`.

### K1 Security (2 wave)
1. **k1-w1-workflow-audit-log** — расширенный event-set + admin REST inventory.
   - Sink: `actor`, `duration_ms`, `parent_workflow_id` columns + ALTER TABLE.
   - Admin: GET /admin/workflow-audit/{inventory,events}.
   - 8 unit-тестов.
2. **k1-w2-temporal-mtls-finale** — Vault PKI + TLS bundle cache.
   - `VaultPkiClient.issue_cert(role, cn, ttl=24h)`, cache до not_after-1h.
   - `TemporalClientFactory(pki_backend="vault")` + fallback на file.
   - Runbook `docs/runbooks/temporal-mtls-rotation.md`.
   - 4 integration теста.

### K2 Resilience+Perf (2 wave)
3. **k2-w1-workflow-sla-grafana** — dashboard `workflow_sla_compliance.json` + ClickHouse datasource provisioning + Prometheus counter `workflow_sla_compliance_total{level=}`.
4. **k2-w2-temporal-worker-autoscale** — `TemporalWorkerScaler` (min=2 max=20 target=10) + Prometheus exporter + K8s HPA manifest. 6 unit-тестов.

### K3 DSL/Workflow (8 wave)
5. **k3-w1-visual-workflow-diff** — `visualize.py:to_graphviz/to_mermaid/compute_step_diff`; tab "Workflow Diff" в page 31 (color-coded). 9 unit-тестов.
6. **k3-w2-cron-builder-ui** — `croniter>=2.0.0` dep + `cron_validator.py` + 8 admin endpoints + Streamlit page 13. 18 unit-тестов.
7. **k3-w3-k4-w2-workflow-cost-estimation** — `WorkflowCostEstimator` (p50/p95 из workflow_audit) + `LLMModelPricing` registry + admin endpoint + page 15 (Overview + AI breakdown tabs). 12 unit-тестов.
8. **k3-w4-reactive-workflows** — `EventBus.subscribe` + `ReactiveWorkflowDispatcher` (debounce 5s / dedup Redis SET NX EX 60 / bulkhead 100). 8 unit-тестов.
9. **k3-w5-workflow-template-library** — 10 yaml в `dsl/workflow/templates/` + `WorkflowTemplateRegistry` (BGE-M3 + rapidfuzz + word-overlap fallbacks) + admin REST. 10 unit-тестов.
10. **k3-w6-saga-compensation-viewer** — SagaProcessor эмитит `workflow.compensation_*` events + `saga_history.py` + page 19 + tab в page 17. 5 unit-тестов.
11. **k3-w7-cancel-workflow-dsl** — `.cancel_workflow()` builder + `CancelWorkflowProcessor` + `manage.py workflow cancel` + audit emit. 8 unit-тестов.
12. **k3-w8-workflow-versioning-ui** — `pin_default/rollback` API + 4 admin endpoints + page 18. 8 unit-тестов.

### K4 AI/Data (2 wave)
13. **k4-w1-ai-workflow-examples-lib** — 3 yaml (RAG saga / multi-agent supervisor / code-interpreter loop) + README + 6 integration-тестов.
14. **k4-w2-llm-workflow-cost-est** — реализован в составе K3 W3 (cost_estimator + LLM breakdown + LLMModelPricing).

### K5 Frontend+Ext (3 wave)
15. **k5-w1-workflow-template-streamlit** — page 33 toggle (Route Blueprints / Workflow Templates) + YAML + Mermaid tabs + "Deploy as new workflow" button.
16. **k5-w2-hitl-history-viewer** — `HitlHistoryService` + GET /hitl/history endpoint + page 72 History section + Export CSV. 6 unit-тестов.
17. **k5-w3-cron-dashboard** — `CronDashboardService` + page 14 (auto-refresh 30s + Pause/Resume/Run-now/Delete). 5 unit-тестов.

## Метрики

- **Тесты**: ~121 unit + integration новых (все passed; croniter/prometheus-зависимые скипаются gracefully).
- **Файлы**: 36 новых (Python services + 10 yaml templates + 3 ai examples + dashboards + tests + runbook + K8s manifest).
- **Streamlit pages**: 5 новых (13, 14, 15, 18, 19) + 4 extends (17, 31, 33, 72).
- **Admin endpoints**: 4 новых router-а (workflow_audit, workflow_cost, workflow_templates, workflow_versioning) + admin_cron расширен; всего 25+ новых endpoints.
- **Feature-flags**: 18 новых (15 default-ON, 3 default-OFF).

## Verification

- `python -m pytest tests/unit/dsl/workflow/ tests/unit/services/workflows/ tests/unit/services/scheduler/ tests/unit/entrypoints/test_admin_workflow_versioning.py tests/unit/entrypoints/test_admin_cron.py tests/integration/extensions/credit_pipeline/ tests/integration/workflow/test_temporal_mtls.py` — все green в окружении с установленными зависимостями (croniter/prometheus_client) и graceful skip без них.
- `python -c "from src.backend.core.config.features import feature_flags; ..."` — 26 workflow/ai_workflow/hitl flags.
- `python -c "from src.backend.entrypoints.api.v1.endpoints.admin_workflow_audit import router; ..."` — 2 routes; admin_cron — 8 routes.

## Carryover в S13/S14

* AI workflow examples — declarative-only; нужны bound handler'ы в `services.ai.*`.
* `feedback_cron.register` lifecycle wiring (S11 carryover).
* Protocol-extraction 29 acknowledged baseline (отдельный S14+).
* Integration smoke для mTLS — требует Vault + docker-compose.bluegreen.yml.
* DspyFeedbackLoop cron registration в lifecycle.py.

## Lessons learned

* **Backbone-commit first** (18 flags + 5 team секций в одном atomic) разблокировал все 17 wave без circular dependencies между фичами.
* **Graceful imports** для croniter / prometheus_client / sentence_transformers / rapidfuzz — тесты skipable, runtime no-op без падений.
* **Re-use existing API**: WorkflowAuditSink (S10-debt), VersionRegistry (S7), HitlService (S9), SagaProcessor (S4) дали 70% scaffold; новые wave = только UI + admin endpoints + DSL builder methods.
* **WorkflowHandle с run_id=workflow_id sentinel** для DSL cancel — Temporal SDK игнорирует run_id если invalid и берёт latest. Для unit-тестов с моком backend — работает идеально.
* **fuzzy fallback** для template search — word-overlap + substring bonus достаточно когда rapidfuzz/sentence-transformers недоступны (тест K3 W5).
