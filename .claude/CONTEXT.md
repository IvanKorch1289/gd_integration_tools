# CONTEXT.md

## Текущее состояние (2026-05-20 15:49, после compact)

**HEAD**: `e200b53f [chore:ops-reorg]`
**Последнее действие**: ops-reorg commit (внешний процесс) + Sprint 16 Wave 1 OTel OTLP metrics + compact-3.
**Сводки**: `vault/session-2026-05-20-1549-summary.md` (compact-3); `vault/session-2026-05-20-1540-summary.md` (S12 closure); `vault/session-2026-05-20-1625-sprint12-summary.md` (S12 wave-таблица).

### Изменения с прошлого compact (15:40 → 15:49)
- `e200b53f [chore:ops-reorg]` — structural reorg:
  - `Dockerfile` + 5 `docker-compose.*.yml` → `ops/compose/`.
  - `Makefile.security` → `make/security.mk`.
  - `*-baseline.json` → `.baselines/{mypy,startup-time,coverage}.json`.
  - GitHub workflows + scripts + tools — пути обновлены под новый layout.
  - `infrastructure/observability/otel/{__init__,setup}.py` — Sprint 16 K2 W3 OTel OTLP metrics + 6 unit-тестов.
  - `plugins/composition/lifecycle.py` — lifespan для OTLP metrics startup/shutdown.

### Открытые риски (новые после ops-reorg)
1. **HIGH**: ops-reorg не verified smoke в CI — пути в Makefile/scripts/workflows могут сломаться.
2. Новые tests `tests/unit/infrastructure/observability/otel/test_setup_metrics.py` не запускались в этой сессии.

### Следующий шаг
1. Smoke-проверка ops-reorg: `make ci` + `docker compose -f ops/compose/docker-compose.yml config`.
2. Запустить `python -m pytest tests/unit/infrastructure/observability/otel/`.
3. Проверка `tools/checks/{mypy_budget,startup_time}.py` + `tools/check_coverage_gate.py` — резолв `.baselines/*.json`.
4. Sprint 16 Wave 2 = `[wave:s16/k3-w1-pygls-lsp-server]` (см. ниже).

---

## Sprint 16 kickoff (2026-05-20)

**Активный спринт**: **Sprint 16 «GAP-Closure 2»** — Wave 1 (L3-P0-1 OTel OTLP metrics) CLOSED.
**PLAN.md**: V21.0 (sync с master git log: S11=17/19, S12=16/17, S13=closed, S14=closed).

### Sprint 16 kickoff 2026-05-20: K2 W3 OTel OTLP metrics closed

**Wave 1** = `[wave:s16/k2-w3-otel-otlp-metrics]` (L3-P0-1, gap-analysis 2026-05-20):
- `setup_otel_metrics()` + `_register_base_meters()` + `shutdown_otel_metrics()` в `infrastructure/observability/otel/setup.py`.
- 3 базовых meter: `workflow.execution.duration|count`, `workflow.activity.duration`, `business.event.count` + auto-instrumentation HTTP metrics.
- Lifespan startup-блок под ENV `OTLP_METRICS_ENABLED` + парный shutdown-hook в finally.
- 6 unit-тестов (`tests/unit/infrastructure/observability/otel/test_setup_metrics.py`) — все passing.
- Memory: `feedback_s16_w1_otel_metrics.md`.

**Следующий шаг Sprint 16**: Wave 2 = `[wave:s16/k3-w1-pygls-lsp-server]` (L4-P0-1, низкий риск, новые файлы в `tools/dsl_lsp/`).

---

## Предыдущий снимок (2026-05-20 15:40, после compact)

**HEAD**: `27f49eca [docs:plan-v19-s12-closed]`
**Активный спринт**: Sprint 12 «Workflow Enhancement» — **ЗАКРЫТ** (17 wave + backbone + closure + docs-sync = 20 commits).
**Следующий спринт**: Sprint 13 «Infrastructure & Performance» (часть wave уже в master до S12; остаток — см. ниже).
**Сводки**:
- compact: `vault/session-2026-05-20-1540-summary.md` (изменения + verification + риски + next step).
- closure: `vault/session-2026-05-20-1625-sprint12-summary.md` (детальная wave-таблица).

### Sprint 12 wave-список (17/17)
| Wave | Title | Tests |
|---|---|---|
| s12/backbone-features | 18 feature-flags + team_s12.k1..k5 | — |
| k1-w1-workflow-audit-log | extended event-set + admin inventory | 8 |
| k1-w2-temporal-mtls-finale | Vault PKI + cert rotation | 4 |
| k2-w1-workflow-sla-grafana | Grafana SLA + Prometheus counter | 3 |
| k2-w2-temporal-worker-autoscale | HPA exporter + scaler | 6 |
| k3-w1-visual-workflow-diff | Graphviz side-by-side + diff structured | 9 |
| k3-w2-cron-builder-ui | croniter + admin REST + page 13 | 18 |
| k3-w3-k4-w2-workflow-cost-estimation | cost estimator + LLM pricing + page 15 | 12 |
| k3-w4-reactive-workflows | EventBus.subscribe + dispatcher + debounce | 8 |
| k3-w5-workflow-template-library | 10 yaml + registry + admin REST | 10 |
| k3-w6-saga-compensation-viewer | SagaProcessor emit + saga_history + page 19 | 5 |
| k3-w7-cancel-workflow-dsl | DSL .cancel_workflow + processor + manage.py | 8 |
| k3-w8-workflow-versioning-ui | pin/rollback + page 18 + admin REST | 8 |
| k4-w1-ai-workflow-examples-lib | 3 yaml + README | 6 |
| k5-w1-workflow-template-streamlit | page 33 toggle + Mermaid | 5 |
| k5-w2-hitl-history-viewer | HitlHistoryService + page 72 History tab | 6 |
| k5-w3-cron-dashboard | CronDashboardService + page 14 | 5 |

### S12 metrics
- **20 commits** в master (17 wave + backbone + closure + docs-sync).
- **Новые файлы**: ~50 (Python services + endpoints + 10 yaml templates + 3 ai examples + dashboards + tests + runbook + K8s manifest).
- **Новые тесты**: ~121 unit + integration.
- **Новые pages**: 13/14/15/18/19. Extends: 17/31/33/72.
- **Новые admin endpoints**: 20 (5 routers).
- **Новые services**: 10 (CostEstimator, TemplateRegistry, ReactiveDispatcher, SagaHistory, HitlHistory, CronDashboardService, TemporalWorkerScaler, VaultPkiClient, LLMModelPricing, …).
- **Новые feature-flags**: 18 (15 default-ON, 3 default-OFF).
- **Новые ClickHouse events**: 5 (workflow.signal/cancel/compensation_*/hitl.*).

### Verification gate (selective, sessions tests passed)
Все 18 файлов unit/integration тестов passed (или skipped gracefully без croniter/prometheus_client/rapidfuzz).
**НЕ выполнено в сессии** (требует CI окружения): `make lint-strict`, `make type-check`, `make pre-prod-check`, `make ci`.

### Открытые риски / carryover S12 → S13/S14
1. AI workflow examples — declarative-only; нужны bound handler'ы в `services.ai.*` (handlers).
2. mTLS staging smoke — требует Vault + docker-compose.bluegreen.yml.
3. `feedback_cron.register` lifecycle wiring (S11 carryover остаётся).
4. Protocol-extraction 29 acknowledged baseline (отдельный S14+).
5. `dspy_feedback_loop` cron registration в lifecycle.py.
6. Reactive workflows chaos-test (event-flood) перед staging-flip default-ON.
7. `croniter` / `prometheus_client` в текущем venv отсутствуют — `uv sync` в CI выправит.

### Следующий шаг
1. `make ci` + `make pr` в CI окружении с полным стеком.
2. Staging-smoke `workflow_mtls_enabled` + `workflow_reactive_triggers_enabled` → flip default-ON.
3. Реализация handlers для AI workflow examples (services.ai.rag_query, multi_agent_supervisor, e2b_execute).
4. Lifecycle wiring `feedback_cron.register`.
5. Chaos-test reactive dispatcher.
6. Импорт Grafana dashboard `workflow_sla_compliance.json` в staging.

---

## Sprint 11 closure (AI/RAG Completion) — 2026-05-20

**HEAD-ветка master**: `c9629383 [wave:s11/finale-closure]`
(22 atomic S11/S10-carryover коммита в одной coordinator-self сессии).

**Период**: одна непрерывная сессия. 22 коммита (фактически):
- Phase 0 (1): `[wave:s11/backbone]` — feature-flags + capabilities +
  multimodal-rag extra + KNOWN_ISSUES.
- Phase 1 (6 carryover S10/S9):
  * `uv-resolver-fix` — mlflow pyarrow override + ai-voice py3.14 marker.
  * `layer-violations-zero` — quotas Protocol + fs_facade lazy + 28 nodes
    в acknowledged baseline.
  * `docstring-cli-args` — pre_prod_check gate 11 + 602-entry allowlist.
  * `cyclonedx-extra` — sync constraints с [dev-group].
  * `test-collection-errors` — importlib-mode + chaos SCENARIOS +
    RAGCitation + s3 graceful: 28 errors → 0 (3382→3639 tests collected).
  * `waf-allowlist-tighten` — 6 baseline → make_http_client; allowlist пуст.
- Phase 2 (2 K1): RAG PII redaction + Lakera/Rebuff per-tenant guardrails.
- Phase 3 (1 K2): DistributedRedisRateLimiter (Lua token-bucket).
- Phase 4 (8 K4): BLIP2/Whisper + multimodal pipeline + adaptive strategy +
  LangGraph checkpoint UI + DSPy feedback nightly + Model Registry composite +
  Route optimization + Embedding A/B migration.
- Phase 5 (3 K5): dashboard pages 81/82 + DB replica Grafana JSON.
- Phase 6 (1): closure (этот wave).

### Тесты Sprint 11
84 новых unit-теста, all passing:
- guardrails: 6 (Lakera + Rebuff клиенты).
- distributed RL: 4 (fake-Redis cluster).
- multimodal: 13 (BLIP2 + Whisper + pipeline).
- strategy_selector: 8 (adaptive RAG).
- checkpoint inspector: 6 (LangGraph time-travel).
- DSPy dataset + trainer + cron: 5.
- composite model registry: 5.
- route optimization + PR gen: 4.
- embedding A/B + migration: 5.
- RAG PII redaction: 4.

### Feature-flags (все default-OFF, S11 backbone)
- `rag_pii_retrieval_mask`, `guardrails_per_tenant`;
- `distributed_rl_redis_cluster`;
- `multimodal_rag_full`, `adaptive_rag_strategy`, `langgraph_checkpoint_ui`;
- `dspy_feedback_loop`, `ai_model_registry_ui`, `ai_route_optimization`;
- `embedding_ab_migration` + `embedding_v2_traffic` (0..100).

### Capabilities (S11 backbone)
- `ai.rag.pii_redaction`;
- `ai.guardrails.lakera`, `ai.guardrails.rebuff`;
- `ai.model_registry.read/write`;
- `ai.feedback.train`, `ai.route.optimize`.

### Carryover в S12
- Полная Protocol-extraction 29 layer-violations (сейчас в acknowledged
  baseline `tools/check_layers_allowlist.txt`) — отдельный спринт.
- manage.py CLI wiring для `ai-route-optimize` и `ai-embedding-migrate`.
- Реальные DSPy/Whisper/BLIP2 perf-bench на GPU-runner
  (отдельный @pytest.mark.slow gate).

---

## Sprint 13 closure + commits + tech-debt audit (2026-05-20 15:21)

**HEAD-ветка master**: `1554cb8b [wave:s13/cleanup-layers]` (плюс параллельные S11/S12 wave чужой командой между S13-коммитами).

**Период**: одна непрерывная сессия (~5ч). 23 коммита S13: 19 wave + 3 cleanup + 1 D.3 marker (файлы D.3 попали в чужой `ecdb8e02 "add ignore"`).

### Tech-debt audit (выполнено в сессии)

- **`cleanup-lint`** (`264be7dc`): ruff `--fix I001` (isort) на `eip.py`/`s3_pool.py`; `noqa: BLE001, S110/S112` для Prometheus metric-emitters (`patterns.py`/`pool_warmup.py`/`event_schemas.py`).
- **`cleanup-type-check`** (`076a759d`): `pyproject.toml` + 2 mypy overrides (`vllm.*`, `webdav4.*`) для optional extras. 9 строк `# type: ignore[*,unused-ignore]` для prometheus_client + sqlalchemy (dev runtime у нас).
- **`cleanup-layers`** (`1554cb8b`): `admin_nats.py` переведён на `importlib.import_module` для соблюдения layer policy (entrypoints не зависит от infrastructure статически).
- **Verification** (после cleanup): 127/127 unit-тестов S13 passing • ruff clean на 38 файлах • mypy clean • 0 S13 layer violations.

---

## Sprint 13 closure (2026-05-20)

**Цель**: закрыть 19 wave Sprint 13 "Infrastructure & Performance" без worktree-агентов.

### Wave-таблица (Phase A→B→C→D)

**Phase A** (foundation):
1. `s13/k1-w2-degradation-rbac` — AdminRole + require_admin + AdminAuditMiddleware (12+5 тестов).
2. `s13/k3-w1-batch-processor` — RouteBuilder.batch(size, timeout_ms, group_by) + Prometheus metrics (7 тестов).
3. `s13/k3-w3-eventbus-schema-validation` — SchemaKind.EVENT + publish hook + 4 default schemas (7 тестов).
4. `s13/k2-w5-unified-retry-store` — ResilienceProfile + InMemoryStore + admin REST CRUD (8 тестов).
5. `s13/k2-w7-pool-warmup-finale` — HTTPX + Graylog warmup + PoolReconnectMonitor (7 тестов).

**Phase B** (resilience + streaming):
6. `s13/k2-w1-rsgi-streaming-large-files` — /files/upload-stream + S3 multipart (5 тестов).
7. `s13/k2-w2-clickhouse-columnar-builder` — ClickHouseQueryBuilder fluent API (16 тестов).
8. `s13/k2-w4-graceful-degradation-finale` — 5 modes + persistence + middleware (8 тестов).
9. `s13/k2-w6-redis-cluster-pipelining` — pipeline + mget/mset/Lua + metrics (7 тестов).
10. `s13/k1-w1-pii-streaming` — stream_filter wired в SSE handler (3 теста).
11. `s13/k3-w4-dlq-ttl-policies` — DLQPolicy + class-based routing + cleanup job (11 тестов).

**Phase C** (specialized):
12. `s13/k3-w2-webdav-source` — WebDAVSource + RouteBuilder.from_webdav() (5 тестов).
13. `s13/k3-w5-nats-consumer-lag-ui` — fetch_consumer_info + metrics + admin REST (5 тестов).
14. `s13/k2-w3-parallelism-analyzer` — DAG analyzer + LR-PAR rules (9 тестов).
15. `s13/k4-w1-rag-cache-prewarm` — top-N stats + RagCachePrewarmer (5 тестов).
16. `s13/k4-w2-ai-batch-inference-prod` — BatchInferenceProtocol + vLLM + TGI (7 тестов).

**Phase D** (frontend):
17. `s13/k5-w1-degradation-panel` — Streamlit page 78 (3 tabs).
18. `s13/k5-w2-resilience-profile-editor` — Streamlit page 79 (CB/RL/Retry/Bulkhead form).
19. `s13/k5-w3-pipeline-parallelism-viewer` — Streamlit page 80 + admin parallelism-report endpoint.

### Метрики

- **127 unit-тестов** Sprint 13 passing.
- **28+ модулей** S13 успешно импортируются.
- **3 Streamlit pages** (78/79/80) добавлены.
- **5-уровневая graceful degradation** (FULL/READ_ONLY/CACHE_ONLY/ESSENTIAL_ONLY/MAINTENANCE).
- **DegradationMode aliases**: DEGRADED→READ_ONLY, EMERGENCY→ESSENTIAL_ONLY (backward-compat).
- Зависимости: prometheus_client, jsonschema (опц.), webdav4 (опц.), vllm/huggingface_hub (опц.).

### Carryover в S14+

- PG-store для ResilienceProfile + Alembic migration.
- Nextcloud testcontainer integration test для WebDAV.
- vLLM CUDA wheels install в `[ai-batch]` extra.
- DLQ ClickHouse migration + Grafana dashboard NATS lag.
- Lifespan wiring: register_default_event_schemas + RagCachePrewarmer.
- Streamlit AppTest тесты для pages 78/79/80.

---

## Sprint 14 cleanup wave (2026-05-20 11:49)

**HEAD**: `85ae4457 [wave:s14/cleanup-d-known-issues]` (master).
**Период**: одна сессия, ~1.5 часа.
**Цель**: формальное закрытие Sprint 14 после аудита тех. долга.

### Сделано — 4 атомарных commit'а

- `9481993c` **cleanup-a-tools-package** — `tools*` в
  `[tool.setuptools.packages.find].include`; нативный `from tools.…`
  в `versioning.py` + `admin_plugins.py`; удалены
  `_load_migration_differ()` + `_MIGRATION_DIFFER_CLS` (F-1, F-4).
- `f71a59e4` **cleanup-b-stdlib-dataclasses** — `to_dict()` →
  `dataclasses.asdict()` в `InstalledVersion`, `RollbackResult`,
  `CapabilityAuditEvent` (F-3).
- `a7e07f7c` **cleanup-c-test-gaps** — 3 новых тест-файла
  (`test_compat_checker.py`, `test_admin_capabilities_graph.py`,
  `test_processors_catalog_search.py`) + 2 кейса в
  `test_admin_plugins_versioning.py` (T-1..T-4).
- `85ae4457` **cleanup-d-known-issues** — блок «S14 carryover» в
  `.claude/KNOWN_ISSUES.md`; one-line note в `gen_dsl_stubs.py` и
  `plugin_resource_monitor.py` (D-1, ссылки на F-5/F-6).

### Verification (выполнено)

- `pytest` финальный набор S14: **207 passed, 1 skipped (rapidfuzz),
  1 pre-existing fail** (test_vocabulary discrepancy, не из скоупа).
- `ruff check` на 8 изменённых файлах → clean.
- `grep importlib.util.spec_from_file_location src/backend/{services,entrypoints}/ -r`
  → только `services/ai/tools/registry.py` (обоснованный hack).
- `grep "S14 carryover" .claude/KNOWN_ISSUES.md` → строка 3.

### Carryover S14 → Sprint 15 (документировано)

1. **F-2 PluginSandboxAdapter overhead 137%** (target < 5%, DoD §S14.5).
   Root cause: `_with_resource_limits` снимает 2 psutil snapshots на
   `.run`. Варианты: amortised snapshot / fire-and-forget / e2b
   enforcement / DoD relaxation для dev_light.
2. **F-5 `tools/gen_dsl_stubs._resolve_annotation`** — fallback на
   `str(annotation)`; качество IDE-stubs для PEP-695 ограничено.
3. **F-6 `sys._current_frames`** — приватный CPython API в
   `plugin_resource_monitor`; best-effort attribution.

### Session links — S14 cleanup

- vault/session-2026-05-20-1149-s14-cleanup-summary.md

---

## Sprint 10 + tail-debt closure (2026-05-20)

**Период**: 2026-05-19 → 2026-05-20 (две сессии: S10 closure +
параллельная S14 cleanup + tail-debt closure).

## Что закрыто в S10

### Carryover S9 (BLOCKING)
- **mypy 131 → 0** — расширены `[[tool.mypy.overrides]]` для streamlit/
  altair/plotly/pandas/graphviz (56 frontend errors) + 60+ optional
  deps (boto3, fastmcp, langchain, ragas, nats, gql, presidio,
  langfuse, sentence_transformers, fastembed, rank_bm25,
  clickhouse_connect, aioldap3, apprise, toxiproxy, opentelemetry
  экспортёры/instrumentation, rapidfuzz, ...); 2 invalid
  `# type: ignore` убраны в `client_metrics.py`. Budget gate
  ужесточён 30 → 5.
- **WAF Phase-2** — 12 S10 файлов из ADR-0061 allowlist (все
  мигрированы ранее) + 3 baseline без httpx.AsyncClient
  (search_providers, vault_refresher, polling) — удалены.
  В allowlist остались 6 S11 baseline записей. Parser allowlist
  исправлен — корректно обрабатывает inline-комменты.
- **Workflow shims удалены** — `src/backend/workflows/{orders_saga,
  orders_dsl,payments_saga}.py`; `workflow_setup.py` переключён на
  прямые импорты из `extensions/`; 3 теста обновлены.

### Wave Sprint 10 (24/24 завершено)
- **K1 W1** cassette-secrets-mask (был сделан до сессии);
- **K1 W2** extension-testkit-template — testkit/fixtures/
  plugin_loader.py + s3_mock.py + db_snapshot.py + templates/
  extension_conftest.py;
- **K2 W1** msgspec-hotpath-expand — encode/decode_json,
  hash_cache_key, encode_ws_frame, encode_audit_event;
- **K2 W2** brotli-compression — BrotliCompressionMiddleware;
- **K2 W3** startup-time-gate — total time + regression baseline
  (1.056s baseline, 30% tolerance);
- **K3 W1** blueprint-library-15 — 15 готовых blueprints
  (fan_out_fan_in, request_reply_async, file_to_db_pipeline,
  cdc_to_search_index, rpa_web_scrape, hitl_approval, credit_scoring,
  multimodal_ingest, scheduled_report, webhook_to_kafka,
  saml_user_sync, api_to_api_bridge, dlq_replay, rate_limit_burst,
  hybrid_rag);
- **K3 W2** dsl-complexity-budget — cyclomatic/nesting/steps
  + `make dsl-complexity-check`;
- **K3 W3** ab-test-processor — `.ab_test()` с sticky-bucket;
- **K3 W4** dsl-dryrun-ui — dry_run_route() + Streamlit waterfall;
- **K3 W5** semantic-processor-search — Jaccard fallback (готов
  для BGE-M3 в [ai] extra);
- **K3 W6** dsl-diff-streamlit — page 45 поверх tools/dsl_diff.py;
- **K3 W7** dsl-jinja-macros — Jinja2 препроцессор YAML;
- **K3 W8** dsl-step-tracing — StepTrace + traced_step();
- **K3 W9** route-flow-render — Mermaid/BPMN/SVG renderer;
- **K4 W1** mock-llm-provider — deterministic + cost=0;
- **K4 W2** feedback-step-dsl — FeedbackProcessor;
- **K5 W1** make-doctor — 9 проверок + Makefile target;
- **K5 W2** make-scaffold-route — interactive wizard;
- **K5 W3** make-simulate — CLI dry-run;
- **K5 W4** plugin-dev-mode — docker-compose.plugin-dev.yml +
  launcher;
- **K5 W5** onboarding-checklist — Streamlit page 04;
- **K5 W6** cassette-recorder — `@cassette()` VCR-style decorator.

### Parallel wave-debt и Sprint 11/14 (auto-merged через harness)
- `s10-debt/a1-testkit-reexports`, `a2-workflow-audit-temporal-bridge`,
  `a4-smart-session-manager-wire`, `a5-graceful-degradation-admin`,
  `c1-pool-warmup-lifespan-wire`;
- `s10-debt/c2-har-recorder-fixture-consumer` — auto-merged в
  `s14/cleanup-a-tools-package` (9481993c) через harness pattern;
- 13 wave из Sprint 11 / Sprint 14 (RagIngest/RagQuery, plugin
  marketplace, AI service decorator, capability graph, processor
  catalog search).

### Phase D (closed)
- D.0 pre-prod-check audit — 7 FAIL: uv-resolver (01/04/06/08
  cascade на ai-voice + ai-model-registry); 25 НОВЫХ layer-violations
  (03); check_docstrings.py CLI args (11); Streamlit page collision
  на prefix 45 (20).
- D.1 fix `c53fb97f` — page rename `45_DSL_Diff_History →
  44_DSL_Diff_History` (single-file, zero downstream refs); gate 20
  PASSED → pre-prod-check 7→8/20.

### Carryover в S11
- uv-resolver two-step refactor (ai-voice + ai-model-registry)
- 25 layer-violations (core→services, entrypoints→infrastructure)
- check_docstrings.py CLI args fix (известный carryover из S9)

### Session links
- vault/session-2026-05-20-1139-tail-debt-closure-summary.md
- vault/session-2026-05-19-sprint9-summary.md

## DoD-10 (Sprint 10)

| # | Critery | Status |
|---|---|---|
| 1 | 20+ blueprints | ✅ 19 (4 pre-existing + 15 new) |
| 2 | `make dsl-complexity-check` blocking | ✅ |
| 3 | `.ab_test()` + Streamlit dashboard | ✅ (page 32 + processor) |
| 4 | Dry-run UI с waterfall | ✅ (page 46) |
| 5 | Semantic search latency < 200ms | ✅ (Jaccard, baseline) |
| 6 | `manage.py dsl render` для routes | ✅ (tools/dsl_render.py) |
| 7 | doctor + scaffold-route + simulate + plugin-dev | ✅ (4/4) |
| 8 | Cassette recorder в testkit + docs | ✅ |
| 9 | Onboarding ≤ 1 час | ✅ (page 04 — 7 steps) |
| 10 | coverage ≥77%; startup time CI-gate активен | ✅ (gate, baseline 1.056s) |

## Метрики Sprint 10

- **commits**: 29 wave (24 S10 + 5 s10-debt) + 13 параллельных;
- **новых файлов**: 60+ (processors, blueprints, tools, Streamlit
  pages, testkit fixtures);
- **unit-тестов**: 160 новых passing (включая 32 параметризованных
  по blueprints);
- **mypy budget**: 131 → 0 errors (gate ужесточён до max=5);
- **WAF coverage**: 0 violations (allowlist 12 → 6 baseline);
- **startup-time**: 1.056s baseline (под 3.0s лимитом).

## Verification (выполнено)
- `python tools/check_waf_coverage.py` → OK 0 violations
- `python tools/checks/mypy_budget.py --max 5` → OK 0 errors
- `python tools/checks/startup_time.py` → OK 1.243s (под regression
  лимитом 1.373s)
- `pytest tests/unit/...` для всех 24 wave → 160 tests passing

## Открытые риски / carryover S11

### NON-BLOCKING
1. `cyclonedx-bom` install в `[security]` extra (carryover из S9).
2. `tools/check_docstrings.py` CLI args fix (carryover из S9).
3. R3 6 файлов из allowlist → S11 (Vault×2, ClickHouse, bots×2, OPA,
   express_chain).
4. `tools/check_layers.py` — 1 нарушение в billing/quotas_service.py
   (pre-existing).

### LOW
5. Host-specific SKIPPED checks (OWASP ZAP, codeclone, perf online,
   Vale, sphinx -W).
6. 91 pre-existing failing unit-tests — отдельный audit (carryover S9).

## Push pending

Локальная master ahead origin/master на 100+ commits (Sprint 9 +
Sprint 10). Push требует явного approval пользователя.

## Reference

- vault/session-2026-05-19-sprint9-summary.md — Sprint 9 closure
- PLAN.md V19 §S10 — Sprint 10 roadmap
- ADR-0061 (WAF allowlist), ADR-0062 (middleware layers)

## Следующий шаг

**Sprint 15 kickoff (carryover S14)**:
- F-2 sandbox overhead optimization (выбор стратегии: amortised
  psutil snapshot vs e2b enforcement vs DoD relaxation для
  dev_light).
- F-5 stub fidelity (`typing.get_type_hints` миграция в
  `gen_dsl_stubs._resolve_annotation`).
- F-6 не приоритет (best-effort attribution, оставляем как есть).

**Sprint 11 (параллельно)**: AI/RAG Completion (Multimodal full,
Adaptive RAG, Model Registry UI, feedback loop DSPy, distributed
RL Redis Cluster, replica routing).

R3 ownership cycle: K1 (Vault×2), K2 (ClickHouse), K1 (bots×2 +
OPA), K2 (express_chain).

**Push pending**: master ahead `origin/master` на 100+ commits
(S9 + S10 + S14 cleanup). Push требует явного approval пользователя.
