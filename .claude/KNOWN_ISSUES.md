# KNOWN_ISSUES.md

## Sprint 15 kickoff — 2026-05-20 (DX Tooling + Innovation, Production-Ready Final)

**Активные задачи** (28 atomic commits — backbone + 25 wave + 6 closure):

* **Backbone**: 5 feature-flags (sandbox_amortised_psutil / arch_map_llm_search_enabled /
  ai_pr_review_enabled / dsl_visual_editor_drag_drop / changelog_autogen_enabled),
  team_s15.k1..k5 секции в team-ownership.toml.
* **Phase A — Production-Gates**:
  - F-2 sandbox overhead reduction (carryover S14).
  - mypy=0 (DoD #9).
  - Final security audit (OWASP ZAP + API top 10).
  - Perf bench ratchet (p95≤80ms, RPS≥1500).
  - `manage.py diagnose` aggregator.
* **Phase B — DSL/LSP**: F-5 .pyi fidelity (carryover S14), LSP server, YAML schema,
  Visual Editor finale.
* **Phase C — DX Scaffolding**: VSCode extension+sign, make new-adr, CLI completions,
  changelog autogen, AI PR review.
* **Phase D — Documentation**: Arch Map (page 83) + LLM search, ADR-tab, dep-map HTML,
  tutorial progress, changelog diff (page 85).

**DoD finale**: 11/11 (см. план §8).

---

## Sprint 12 closure (Workflow Enhancement) — 2026-05-20

**Закрыто** (17 atomic wave + backbone + closure в одной coordinator-self сессии):

* **Backbone** — 18 feature-flags + 5 team_s12.k1..k5 секций.
* **K1 Security** (2 wave): workflow_audit_log extended + admin inventory;
  Temporal mTLS Vault PKI + cert rotation + docker runbook.
* **K2 Resilience+Perf** (2 wave): SLA Grafana dashboard 99% SLO + Prometheus
  counter; TemporalWorkerScaler HPA exporter + K8s manifest.
* **K3 DSL/Workflow** (8 wave): visual diff (Graphviz) + cron builder UI +
  pre-run cost estimator + reactive event-driven triggers + 10 workflow
  templates с semantic search + saga compensation viewer + .cancel_workflow()
  DSL step + versioning UI (pin/rollback).
* **K4 AI/Data** (2 wave): 3 production AI examples
  (RAG saga / multi-agent / code-interpreter loop); LLM cost breakdown с
  Anthropic 4.x/OpenAI pricing.
* **K5 Frontend+Ext** (3 wave): page 33 templates + Mermaid; page 72 HITL
  History tab + CSV export; page 14 Cron Dashboard.

### Открытые carryover (S12 → S13/S14)

* AI workflow examples — declarative-only; нужны bound handler'ы
  в `services.ai.*` (S13+).
* `feedback_cron.register` lifecycle wiring (S11 carryover остаётся).
* Protocol-extraction 29 acknowledged baseline (отдельный S14+).
* Integration smoke для mTLS требует Vault + docker-compose.bluegreen.yml
  (default-OFF flag).
* `dspy_feedback_loop` cron registration в lifecycle.py.

---

## Sprint 11 closure (AI/RAG Completion) — 2026-05-20

**Закрыто** (22 atomic wave в одной coordinator-self сессии):

* Phase 0 (1): `[wave:s11/backbone]` — 10 feature-flags + 7 capabilities +
  multimodal-rag extra + KNOWN_ISSUES.
* Phase 1 (6 carryover S10/S9) — все pre-prod-check gates 01/04/06/08/11 → PASS:
  * `uv-resolver-fix` — mlflow pyarrow override + ai-voice py3.14 marker.
  * `layer-violations-zero` — Protocol extraction (quotas) + 28 acknowledged baseline.
  * `docstring-cli-args` — gate 11 + 602-entry allowlist.
  * `cyclonedx-extra` — версия sync с [dev-group].
  * `test-collection-errors` — importlib-mode + chaos SCENARIOS + RAGCitation;
    28 errors → 0 (3382 → 3639 tests collected).
  * `waf-allowlist-tighten` — 6 baseline migrated to ``make_http_client``;
    allowlist пуст.
* Phase 2 (2 K1): RAG PII redaction + Lakera/Rebuff per-tenant guardrails.
* Phase 3 (1 K2): DistributedRedisRateLimiter (Lua token-bucket).
* Phase 4 (8 K4): BLIP2/Whisper + multimodal pipeline + adaptive strategy +
  LangGraph checkpoint UI + DSPy feedback nightly + Model Registry composite +
  Route optimization + Embedding A/B migration.
* Phase 5 (3 K5): dashboard pages 81/82 + DB replica Grafana JSON.
* Phase 6 (1): finale closure (CONTEXT + KNOWN_ISSUES + vault summary).

**Тесты**: 84 новых unit-теста, all passing.

---

## Sprint 11 carryover → Sprint 12

- **Полная Protocol extraction 29 layer-violations** — сейчас в
  acknowledged baseline `tools/check_layers_allowlist.txt`. Закрытие
  через перенос composition-root в infrastructure/ + DI binding в
  svcs_registry. Owner: Foundation Hardening (S12).
- **manage.py CLI wiring** для `ai-route-optimize`/`ai-embedding-migrate` —
  backend готов (services/ai/optimization/, services/ai/embeddings/),
  CLI обёртки делаются в S12 K3.
- **Реальные ML perf-bench** на GPU-runner (BLIP2/Whisper/DSPy) — отдельный
  ``@pytest.mark.slow`` гейт; в S11 модели mock через MagicMock.
- **APScheduler cron registration в lifespan** — `feedback_cron.register`
  готов; integration в `plugins/composition/lifecycle.py` зарезервирована
  на S12 при включении `dspy_feedback_loop=True`.

---

## S14 carryover — 2026-05-20 (cleanup A/B/C/D consolidation)

**Закрыто в S14 cleanup wave**:
- ✅ **F-1 importlib hack** — `tools/*` теперь в `setuptools.packages.find::include`,
  versioning.py и admin_plugins.py используют нативный импорт (`cleanup-a`).
- ✅ **F-3 ручной `to_dict()`** — заменён на `dataclasses.asdict()` в
  InstalledVersion / RollbackResult / CapabilityAuditEvent (`cleanup-b`).
- ✅ **F-4 `_MIGRATION_DIFFER_CLS` global** — удалён вместе с
  `_load_migration_differ()` (`cleanup-a`).
- ✅ **T-1..T-4 покрытие** — 3 новых файла тестов + расширение
  `test_admin_plugins_versioning.py` (real dependency-graph + scaffold
  via patched codegen).

**Переносится в Sprint 15**:

- ⏳ **F-2 Sandbox overhead 137%** (target < 5%, DoD §S14.5).
  `tests/perf/test_plugin_sandbox_overhead.py` показывает ~187 µs против
  ~79 µs baseline. Root cause: `_with_resource_limits` снимает 2 psutil
  snapshots на каждый `PluginSandboxAdapter.run`. Варианты для S15:
  amortised snapshot раз в N вызовов / fire-and-forget task / переезд
  enforcement в e2b runtime / снять числовое требование DoD для
  dev-окружения. Функционально sandbox работает.

- ⏳ **F-5 `gen_dsl_stubs._resolve_annotation` fallback**.
  Использует `str(annotation)` вместо `typing.get_type_hints` /
  `get_origin` / `get_args`. Stub-генерация работает (215 .pyi
  сигнатур), но качество IDE-autocomplete ограничено для PEP-695
  type-parameters и `TypeAlias`. Точечное улучшение — отдельная задача
  S15 K3 «pyi fidelity».

- ⏳ **F-6 `sys._current_frames()` приватный API** в
  `infrastructure/observability/plugin_resource_monitor._collect_cpu_share`.
  Работает в CPython 3.14, best-effort attribution. На PyPy / Jython
  возвращает `{}` (graceful fallback). Не блокер.

---

## Sprint 8 closure status — 2026-05-18 (coordinator-self consolidation)

**Закрыто в S8 closure**:
- ✅ **BLOCKER #3 WAF Phase-2** — 0 violations (см. ниже)
- ✅ **K2 W3 DLQ unified scaffold** — DLQEnvelope + DLQWriter Protocol (`ffd84769`)
- ✅ **K2 W4 Inbox fail-closed** — fail_mode policy + 7 unit-tests (`02587c14`)
- ✅ **K3 W12 MCP FastMCP** — уже на FastMCP (12 unit-tests passing); DoD verified
- ✅ **Sprint 8 artifacts consolidation** — 98 файлов через `[wave:s8/cleanup]` (`6f850f6c`)

**Carryover в Sprint 9 (untracked wave-DoD не закрыт)**:
- ⏳ **AugmentResult** отсутствует в `services/ai/rag_service.py` → S9 K4
- ⏳ **WebhookSignVerifyProcessor** отсутствует в `dsl/engine/processors/enrichment.py` → S9 K3
- ⏳ **PluginCodegen** class отсутствует в `tools/codegen_plugin.py` → S9 K5
- ⏳ **service.py/service/ shadowing** в `src/backend/dsl/` (pre-existing) → S9 K3
- ⏳ **K2 W3 DLQ full integration** (4 транспорта) → S9 K2
- ⏳ **K1 WAF allowlist tightening** (~13 baseline callsites) → S9 K1
- ⏳ **AUDIT-2 plugin hot-swap docs-drift** → S9 K3
- ⏳ Sprint 8 wave-матрица в PLAN.md V19.1: 10+ wave переносятся в S9

---

## Audit findings 2026-05-15 (Sprint 6/7 closure verification)

> Источник: Explore-агент 2026-05-15 + coordinator audit. Сравнение ✅-помеченных
> задач в `PLAN.md` (Sprint 6 ≈ 95%, Sprint 7 ≈ 92%) с фактической файловой
> системой. **Подтверждено**: SAML/AD, supply-chain SBOM+cosign+pip-audit, OWASP
> ZAP, codeclone, k6+locust, schemathesis, banking processors (12 тестов), DSL
> Linter + LSP, Inspect AI nightly, DSPy critical pipelines, chaos×33, outbox
> stub, layer-violations facade, msgspec hotpath benchmark, structlog batching
> (`infrastructure/observability/structlog_batching.py`), plugin hot-swap
> (`core/plugin_runtime/hot_swap.py` 279 LOC + graceful shutdown + state
> migration через PluginLoader).

### ❌ AUDIT-1 — Quotas tests fail (Sprint 7 K1)

- **Owner**: K1 Security
- **ETA**: Sprint 8 K1 W0 (`[wave:s8/k1-w0-quotas-tests-fix]`)
- **Risk**: low (тесты, не runtime)
- **Файлы**: `tests/unit/core/auth/test_quotas.py`,
  `tests/unit/services/billing/test_quotas_service.py`

**Описание**: 5 unit-тестов quotas падают после S7 K1 `4f6e9dab`
(per-tenant billing/quotas service + ASGI middleware). Регрессия не блокирует
runtime, но `make ci` warn-out до фикса.

**DoD checklist**:
- [ ] `pytest tests/unit/core/auth/test_quotas.py tests/unit/services/billing/test_quotas_service.py` → 5/5 passed
- [ ] Проверить, что баг в test-фикстурах или в impl
- [ ] Обновить `feature_flags.per_tenant_quotas` если требуется

---

### ⚠️ AUDIT-2 — Plugin hot-swap путь в PLAN.md ≠ реальный

- **Owner**: K3 DSL+Workflow (PluginRuntime owner)
- **Severity**: docs-drift, не runtime-баг
- **Действие**: при следующем PLAN.md edit поправить ссылку.

**Описание**: PLAN.md / координационные планы ссылаются на
`src/backend/services/plugins/hotswap*` (которого нет). Реальная реализация
живёт в `src/backend/core/plugin_runtime/hot_swap.py` (279 LOC: `hot_swap()`
async, `HotSwapResult`, `PluginLoaderProtocol`, graceful shutdown через
`loader.shutdown_all()`). CLI `manage.py plugin hot-swap` использует именно этот
модуль. **Расхождение только в путях документации**, функционал закрыт.

---

### ⚠️ AUDIT-3 — windows-sidecar layout ≠ PLAN.md V17 `windows_worker/`

- **Owner**: K3 DSL+Workflow
- **ETA**: Sprint 8 K3 W1 (`[wave:s8/k3-w1-windows-worker-rename]`)
- **Risk**: low (RPA stage 1 не начат, рефакторинг до scaling-up)
- **Текущий layout**: `windows-sidecar/{app.py, com_router.py, Dockerfile.windows}`
- **Целевой layout V17**: `windows_worker/{main.py, handlers/com_handler.py, handlers/desktop_rpa_handler.py, Dockerfile.windows}`

**Описание**:
- Имя `windows-sidecar` использует kebab-case, PEP 8 и V17 требуют snake_case
  `windows_worker/`.
- `app.py` → `main.py` (V17 alignment с остальными top-level Python entry).
- `com_router.py` (137 LOC) разделить на `handlers/com_handler.py`
  (текущее содержимое) + scaffold `handlers/desktop_rpa_handler.py` под
  Sprint 8 K3 W4 pywinauto.
- `docker-compose.windows-worker.yml` сейчас **untracked** в git — закоммитить
  вместе с rename.

**Вердикт «правильно вынесено наружу»** — оставить top-level (НЕ переносить в
`src/`):
- Отдельный процесс (REST API на Windows-контейнере), не Python import.
- Windows-only runtime (Granian RSGI не работает на Windows нативно).
- Windows-only deps (`pywin32`, `comtypes`, `pywinauto`) загрязнили бы основной
  `src/` `[project.dependencies]` platform markers.
- PLAN.md V17 строка 732 явно фиксирует top-level.

**DoD checklist**:
- [ ] `git mv windows-sidecar windows_worker`
- [ ] `git mv windows_worker/app.py windows_worker/main.py`
- [ ] split `com_router.py` → `handlers/com_handler.py` + `handlers/desktop_rpa_handler.py`
- [ ] Обновить `Dockerfile.windows` (CMD/ENTRYPOINT → `main.py`)
- [ ] `git add docker-compose.windows-worker.yml`
- [ ] Обновить `pyproject.toml::[project.optional-dependencies] com-windows / rpa-windows` если требуется
- [ ] `make wave-memory NAME=windows-worker-rename TYPE=feedback`

---

## Sprint 5 carryover (still open) — миграция в Sprint 8A

> Источник: 16 reflog-коммитов Sprint 5 (HEAD `eaad2f6c` до race) +
> `.claude/CONTEXT.md` секция «Sprint 5 — попытка closure». Все wave НЕ
> переписываются полуготовыми reflog-коммитами, а **переделываются чисто** в
> Sprint 8A (см. план S8 К2 W2-W7 + K4 W1-W8 + К1 round 2 + K3 W10-W11).

### К2 (Resilience) — 8 wave перенесены в Sprint 8A K2 W1-W7
- `[wave:s8/k2-w1-taskiq-removal]` — BLOCKER #1 closure (13 callsites).
- `[wave:s8/k2-w2-outbox-dispatcher]` — `infrastructure/messaging/outbox_dispatcher.py`
  поверх Protocol+Fake `core/messaging/outbox.py` (`36ca6757` уже в master).
- `[wave:s8/k2-w3-dlq-unified]` — DLQ unified для HTTP/SOAP/gRPC/Webhook.
- `[wave:s8/k2-w4-inbox-fail-closed]` — `seen_or_mark()` raise `InboxUnavailable`.
- `[wave:s8/k2-w5-alerts-and-fallback-chains]` — 5 alerts + 2 fallback chains.
- `[wave:s8/k2-w6-bulkhead-defaults]` — Bulkhead defaults в `ResilienceSettings`.
- `[wave:s8/k2-w7-tenant-rate-limit-namespace]` — per-tenant namespace.

### К1 (Security) — Round 2 перенесён в Sprint 8A K1 W1-W3
- `[wave:s8/k1-w1-waf-phase2]` — BLOCKER #3 closure (38 callsites + flip).
- `[wave:s8/k1-w2-dlq-replay-rbac]` — admin-only RBAC + audit-event на replay.
- `[wave:s8/k1-w3-inbox-audit-pii]` — Inbox dedup audit с PII-mask.

### К3 (DSL/Workflow) — W13-W14 перенесены в Sprint 8A K3 W10-W11
- `[wave:s8/k3-w10-workflow-taskgroup]` — `asyncio.TaskGroup` migration.
- `[wave:s8/k3-w11-invoke-workflow-reply]` — sync через Temporal signal.

### К4 (AI/RAG) — 9 wave перенесены в Sprint 8A K4 W1-W8
- `[wave:s8/k4-w1-multimodal-rag]` — docling + PaddleOCR/EasyOCR + `.rag_ingest(modal=...)`.
- `[wave:s8/k4-w2-rlm-hierarchical-memory]` — MemGPT-style hierarchical memory toolkit.
- `[wave:s8/k4-w3-rag-cache-invalidation]` — 3-уровневый cache invalidation через Redis pub/sub.
- `[wave:s8/k4-w4-bge-m3-reranker]` — BGE-M3 + bge-reranker-v2.5 EmbeddingProvider.
- `[wave:s8/k4-w5-rag-streamlit-pages-7]` — 7 RAG Streamlit pages (см. Sprint 8B K4 W5).
- `[wave:s8/k4-w6-mem0-rag-memory-dsl]` — `mem0ai>=0.1.0` + `.rag_*/.memory_*` DSL.
- `[wave:s8/k4-w7-saga-blueprint]` — `saga_with_compensation` Blueprint R2.
- `[wave:s8/k4-w8-litellm-final]` — LiteLLM gateway financial (cost-budget + retry + fallback).
- `[wave:s8/k1-w4-pii-dsl-step]` — `.mask_pii/.unmask_pii` DSL (формально К1 owner, но scope К4).

### Sprint 7 К1 carryover (stash-accident potery) → Sprint 8A K1 W5-W6
- `[wave:s8/k1-w5-supply-chain-cosign-all]` — multi-artifact cosign (plugin TOML).
- `[wave:s8/k1-w6-openfeature-flagsmith]` — OpenFeature → Flagsmith default-ON staging.

### Sprint 7 К5 carryover → Sprint 8A K5 W2-W4
- `[wave:s8/k5-w2-streamlit-tenants]` — `70_Tenants.py`.
- `[wave:s8/k5-w3-streamlit-capabilities]` — `71_Capabilities.py`.
- `[wave:s8/k5-w4-streamlit-files-s3]` — `30_Files_S3.py`.

### Sprint 7 К2 carryover → Sprint 8B K2 W8-W9
- `[wave:s8/k2-w8-httpx-unify]` — `httpx + httpx-retries + httpx-cache (hishel)`
  (адаптер `httpx_cache_adapter.py` уже в working tree).
- `[wave:s8/k2-w9-grafana-and-slo-alerts]` — 7 Grafana dashboards финал + 3 SLO-burn alerts.

### Sprint 7 К3 carryover → Sprint 8A K3 W8-W9 + W13
- `[wave:s8/k3-w8-dsl-blueprints-subdir]` — `dsl/macros.py`/`dsl/blueprints.py` → `dsl/blueprints/` package.
- `[wave:s8/k3-w9-workflow-versioning]` — Temporal `patched` API + per-workflow semver.
- `[wave:s8/k3-w13-plugin-hotswap-impl]` — расширение `core/plugin_runtime/hot_swap.py`
  (если по итогам S8 K3 ревизии потребуется доделать state migration / version-conflict).

### Sprint 5 К4 carryover (MCP)
- `[wave:s8/k3-w12-mcp-via-fastmcp]` — FastMCP auto-export Tier 1+2 actions
  (code-зона DSL/MCP — К3 owner, AI-payload — К4).

---

## Sprint 2 (V15.3 MVP) — 3 БЛОКЕРА (день 1, 2026-05-13)

> Источник: 10-team plan PLAN.md V18.1. Координатор: K10 DevOps.
> Feature-flag для каждого — см. `src/backend/core/config/features.py`.
> Owner-команда — см. `.claude/team-ownership.toml::[blockers]`.

### ⛔ BLOCKER #1 — TaskIQ removal (R-V15-7)

- **Owner**: K6 AI/RAG
- **ETA**: Sprint 2 Wave 3 (`[wave:s2/k6-w2-taskiq-removal]`)
- **Risk**: high (13 callsites `Invoker.ASYNC_QUEUE`)
- **Feature-flag**: `feature_flags.taskiq_removed` (default-OFF)

**Описание**: Temporal полностью покрывает функциональность TaskIQ
(background/deferred/cron + saga/replay/versioning). Стек после migration:
FastStream (MQ) + APScheduler (простой scheduling) + Temporal (durable).

**DoD checklist**:
- [ ] 0 импортов `taskiq` в `src/` (`rg "^(from|import) taskiq" src/`)
- [ ] 0 ссылок `Invoker.ASYNC_QUEUE` (или enum переименован)
- [ ] 13 callsites замигрированы на Temporal cron / APScheduler
- [ ] Migration shim под feature-flag параллель до flip default-ON
- [ ] `make wave-memory NAME=taskiq-removal TYPE=feedback`
- [ ] `taskiq` удалён из `pyproject.toml::dependencies`

**Coordination**: K6 пишет migration shim, K10 audit'ит callsites,
K3 проверяет, что Temporal cron не ломает observability spans.

---

### ⛔ BLOCKER #2 — Workflow legacy purge (4 файла + 19 импортёров)

- **Owner**: K4 Workflow
- **ETA**: Sprint 2 Wave 1 (`[wave:s2/k4-w1-workflow-purge]`)
- **Risk**: high (19 импортёров, см. ниже)
- **Feature-flag**: `feature_flags.workflow_legacy_disabled` (default-OFF)

**Файлы под удаление**:
- `infrastructure/workflow/state.py` (DEPRECATED V16)
- `infrastructure/workflow/state_store.py` (DEPRECATED V16)
- `infrastructure/workflow/event_store.py` (DEPRECATED V16)
- `infrastructure/workflow/state_projector.py` (DEPRECATED V16)

**19 импортёров** (известны из Sprint 1):
- `pg_runner_backend.py`, `runner.py`, `executor.py`
- `core/di/providers.py`
- `infrastructure/database/models/workflow_instance.py`
- миграция `c3d4e5f6a7b8`
- `plugins/composition/lifecycle.py`
- + 12 файлов (audit через `rg "from .*infrastructure\.workflow\.(state|state_store|event_store|state_projector)" src/`)

**DoD checklist**:
- [ ] 0 ссылок на legacy `infrastructure/workflow/state*`
- [ ] TemporalFacade покрывает все use-cases legacy backend
- [ ] Adapter-pattern на переходный период (если нужен) задокументирован в ADR
- [ ] BPMN sample workflow запускается на новом стеке
- [ ] `pytest tests/workflow/` зелёный
- [ ] `make wave-memory NAME=workflow-purge TYPE=feedback`

**Coordination**: K4 ведёт миграцию, K9 пишет sample BPMN через
`extensions/credit_workflow/`, K8 чистит миграции БД, K10 audit'ит callsites.

**Связь со Sprint 1 deferral**: см. секцию `Sprint 1 Этап 2 — Step 2.2 deferred`
ниже. Объём подтверждён (~5-10 дней). Sprint 2 Wave 1 — атомарное закрытие.

---

### ✅ BLOCKER #3 — WAF Phase-2 migration — CLOSED 2026-05-18

- **Owner**: K1 Security
- **Closed**: Sprint 8 K1 W1 `[wave:s8/k1-w1-waf-phase2-finale]` (`058705ed`)
- **Final coverage**: `tools/check_waf_coverage.py` → 0 violations
- **Feature-flag**: `feature_flags.waf_outbound_via_facade` (default-OFF)

**Реализовано (S8 closure)**:
- ✅ 3 callsites вне allowlist мигрированы на `make_http_client()`:
  - `core/feature_flags/flagsmith_client.py:_get_client`
  - `core/feature_flags/flagsmith_provider.py:_get_or_create_client`
  - `services/rpa/desktop_rpa_client.py:invoke`
- ✅ `tools/check_waf_coverage.py` exit 0
- ✅ Default-OFF поведение сохранено (нулевой риск регрессии)

**Carryover → Sprint 9 K1**:
- ⏳ Tightening allowlist: миграция ~13 baseline-callsites
  (express_bot, telegram_bot, opa, clickhouse, vault_cipher, ml_inference,
   proxy/forward, imports endpoint, webhook handler/transformer,
   search_providers).
- ⏳ Flip `feature_flags.waf_outbound_via_facade` → default-ON после
  staging-smoke (`vault/2026-XX-waf-phase2-rollout.md`).
- ⏳ ADR-0053 Proposed → Accepted.

---

### ✅ BLOCKER #4 — Supply-chain (SBOM + cosign + ZAP) — CLOSED 2026-05-14

- **Owner**: K1 Security
- **Wave**: `[wave:s3/k1-w3-supply-chain-ci]` `c8c8a5a` + `[wave:s3/k1-w5-plugin-semver]` `a3df2a6`
- **Закрыто**: Sprint 3 K1 W3 + W5
- **Feature-flag**: `feature_flag.supply_chain_ci_gate` (CI-only) + `feature_flag.plugin_semver_strict`

**Реализовано**:
- ✅ `tools/checks/generate_sbom.py` — CycloneDX JSON + XML generator
- ✅ `tools/checks/run_pip_audit.py` — pip-audit JSON-output обёртка
- ✅ `tools/checks/cosign_sign.py` — cosign artifact signing
- ✅ `tools/checks/check_plugin_semver.py` — plugin manifest semver validator
- ✅ Makefile.security: `sbom` / `audit-deps` / `cosign-sign` / `check-plugin-semver`
- ✅ `pyproject.toml::[security]` extras: cyclonedx-bom + pip-audit
- ✅ 5+4 unit-тестов

**Открытая часть**: подключение к `.github/workflows/release.yml` + OWASP ZAP `.github/workflows/security.yml` —
запланировано как Sprint 4 К1 W1 (отдельный wave-tag).

---

### 🟢 PLAN #5 — Search-DSL extension (SearXNG + Exa + cleanup current)

- **Owner**: K6 AI/RAG (lead) + K7 EventBus (provider integration)
- **ETA**: Sprint 3 / Sprint 4 (M-size, 3-5 дней)
- **Wave-tag**: `[wave:s3/k6-w4-search-providers]` (lead) + `[wave:s3/k6-w4-search-cleanup]`
- **Risk**: low (new feature behind feature-flag, parallel к existing)

**Контекст**: Internal audit (2026-05-13) выявил пробелы в текущей search-архитектуре:
- Tavily без `Settings`-класса — `tavily_api_key` через `getattr` без валидации
- `PerplexityProvider` дублируется: `infrastructure/clients/external/search_providers.py` + `services/ai/ai_agent.py`
- DSL actions дублируются: `ai.search_web` (Perplexity-only) vs `web_search.query` (с fallback)
- DuckDuckGo не реализован (только MCP в Claude Code, не в коде проекта)
- Нет тестов на `search_providers.py`

External research (2026-05-13) подтвердил:
- ❌ Brave Search free tier удалён фев-2026 (платный $5/mo)
- ❌ Bing Web Search API retired авг-2025
- ❌ Glean / Kagi / Mojeek — enterprise/paid only
- ✅ **SearXNG** (self-hosted, unlimited, privacy-first) — production-ready для банковской среды
- ✅ **Exa AI** (1000 req/mo free, neural semantic) — production-ready для RAG grounding
- 🟡 **OpenAlex** (academic, free key) — spike-worthy для compliance RAG
- 🟡 **Firecrawl** (1000 pages/mo, Markdown) — spike-worthy для data ingestion

Полный отчёт: `vault/research-2026-05-13-search-engines.md`.

**Scope (DoD checklist)**:

*Cleanup waves (Sprint 3 Wave 1)*:
- [ ] `TavilySettings` класс в `core/config/ai.py` + Pydantic-валидация api_key
- [ ] Дедупликация `PerplexityProvider` — единый класс в `search_providers.py`, `ai_agent.py` использует его
- [ ] DSL action consolidation: `web_search.query` единый, `ai.search_web` deprecated alias
- [ ] Unit-тесты для `search_providers.py` (4-6 тестов: mock httpx)

*New providers (Sprint 3 Wave 2)*:
- [ ] `SearXNGProvider` (BaseSearchProvider subclass) — async via httpx + `?format=json`
- [ ] `SearXNGSettings` (base_url, engines list, default-OFF feature-flag)
- [ ] `ExaProvider` через `exa-py` — neural mode + content extraction
- [ ] `ExaSettings` (api_key, mode, default-OFF feature-flag)
- [ ] WAF capability для Exa: `net.outbound.exa.ai:external`
- [ ] DSL step extension в `dsl/engine/processors/ai.py`: `search:` с `provider: searxng|exa|perplexity|tavily`
- [ ] 2 reference routes с новыми providers
- [ ] 6-8 unit-тестов (mock httpx, mock exa-py)

*Optional spike (Sprint 4)*:
- [ ] `OpenAlexProvider` (academic RAG)
- [ ] `FirecrawlProvider` (Markdown extraction)

**Feature-flags** для регистрации:
- `search_provider_searxng` (default-OFF)
- `search_provider_exa` (default-OFF)
- `search_provider_openalex` (default-OFF, Sprint 4)
- `search_provider_firecrawl` (default-OFF, Sprint 4)

**Coordination**: K6 — provider implementations + DSL step, K7 — capability registration для WAF, K2 — `OutboundHttpClient` для `:external` (Exa, OpenAlex), K10 — feature-flag реестр.

**Сильные стороны**: SearXNG closes air-gap/privacy concern для банка; Exa Neural идеален для RAG; cleanup убирает дублирование Perplexity + закрывает test gap.

---

### Sprint 2 (V15.3 MVP) — РЕЗУЛЬТАТЫ kickoff (2026-05-13)

**Закрыто** (14 wave-коммитов, 46 unit-тестов green, 22 feature-flag default-OFF):

| Owner | Wave-tag | Commit | Описание |
|---|---|---|---|
| К10 | `s2/k10-backbone` | `371eace` | 10-team ownership + 22 feature-flag + 3 blockers |
| К10 | `s2/k10-w2-py2-syntax` | `461a6ce` | 20 Python-2 except callsites hotfix |
| К10 | `s2/k10-w1-testkit` | `8af96c1` | testkit/pytest_plugin.py entry-point |
| К10 | `s2/k10-features-extend` | `07512b4` | +3 feature-flag (task_watchdog/pool_health/file_watcher) |
| К1 | `s2/k1-w1-joserfc` | `af0c4f5` | joserfc parallel shim + 14 тестов |
| К2 (K3) | `s2/k3-w1-otel-tenacity` | `42ed620` | OTel asyncpg + tenacity unification |
| К2 (K3) | `s2/k3-w2-watchdog-deadline` | `d9beed9` + `5549127` | TaskWatchdog + AIWorkspaceCleaner + fix |
| К2 (K3) | `s2/k3-w4-perf-gate-ci` | `26aa05a` | perf-gate Makefile + CI workflow + baseline |
| К2 (K8) | `s2/k8-w5-pool-health` | `2aa4544` | ConnectionPoolHealthMonitor scaffold |
| К3 (K5) | `s2/k5-w3-processor-registry` | `f2f5b14` | @processor + JSON-Schema export (17 тестов) |
| К3 (K5) | `s2/k5-w5-routes-v11-refs` | `dc33a03` | 2 reference routes по ADR-0056 (4 тестов) |
| К3 (K7) | `s2/k7-w4-file-watcher` | `dacd89c` | FileWatcherSource через watchfiles.awatch |
| К4 (K6) | `s2/k6-w1-langfuse-v3` | `ca5429d` | LangFuse 3.x parallel shim (4 тестов) |

**НЕ закрыто (перенесено в Sprint 3)**:
- SBOM/cosign/ZAP supply-chain → BLOCKER #4 (выше)
- WAF Phase-2 38 callsites → BLOCKER #3 (выше)
- TaskIQ removal → BLOCKER #1 (выше)
- Workflow legacy purge → BLOCKER #2 (выше)

**Memory**: `~/.claude/projects/.../memory/feedback_s2_multi_agent_kickoff.md`.

---

## Известные ограничения и quirks

### Sprint 1 Этап 2 — Step 2.2 deferred на Sprint 4 (2026-05-07)

**Проблема**: PLAN.md V16 §4.1 требует `Workflow legacy purged` (DoD Sprint 1).
4 файла под удаление (`infrastructure/workflow/{state,state_store,event_store,state_projector}.py`)
имеют 19 импортёров через `pg_runner_backend.py`, `runner.py`, `executor.py`,
`core/di/providers.py`, `infrastructure/database/models/workflow_instance.py`,
миграцию `c3d4e5f6a7b8`, `plugins/composition/lifecycle.py`.

**Объём миграции**: ~5-10 дней. Полная замена pg-runner стека на TemporalFacade
с переписыванием всех consumers.

**Причина deferral**:
- Объём перекрывается со Sprint 4 Workflow Single-Entry refactor (Temporal
  native migration), который атомарно решит ту же задачу.
- В Sprint 1 параллельная команда активно работает над `runner.py`
  (последний touch 2026-05-07 15:53 при wrap TaskRegistry callsites) —
  пересечение увеличивает риск merge conflict'ов.

**План разрешения**: Sprint 4. Текущие 4 файла остаются помечены DEPRECATED V16
(см. header-комменты `state.py`, `state_store.py`, `event_store.py`, `state_projector.py`).

### Sprint 1 Этап 2 — Step 2.3 (OTel asyncpg) выполняется параллельной командой

В working tree `pyproject.toml` + `src/backend/infrastructure/observability/otel_auto.py`
содержат изменения для `opentelemetry-instrumentation-asyncpg` + функция
`_instrument_asyncpg`. Коммит ожидается от параллельной команды.

### Sprint 1 Этап 3 — Step 3.3 (миграция callsites + удаление aliases) ✅ CLOSED 2026-05-08

**Wave**: `[wave:s1/single-entry-migration]` (PLAN.md V18 §2.5).

**Что сделано**:
- 7 production callsites мигрированы с `infrastructure/resilience/breaker`
  на canonical `core/resilience/breaker`:
  - `infrastructure/clients/external/circuit_breakers.py`
  - `infrastructure/clients/messaging/stream.py`
  - `infrastructure/clients/transport/http_httpx.py`
  - `infrastructure/database/session_manager.py`
  - `infrastructure/logging/backends/graylog_gelf.py`
  - `dsl/engine/processors/eip/resilience.py`
  - `tests/unit/log_sinks/test_log_sinks.py`
- `infrastructure/resilience/__init__.py` перенаправлён на
  `core/resilience/retry_budget` для `RetryBudget` re-export.
- 3 shim-файла удалены:
  - `infrastructure/resilience/breaker.py`
  - `infrastructure/resilience/retry.py`
  - `infrastructure/resilience/retry_budget.py`
- 2 shim-verification теста удалены из:
  - `tests/unit/core/resilience/test_unified_breaker.py`
    (`test_infrastructure_shim_re_exports`, `test_infrastructure_shim_breaker_registry_lazy`)
  - `tests/unit/core/resilience/test_unified_retry.py`
    (`test_infrastructure_shim_re_exports`, `test_infrastructure_retry_budget_shim`)

**Что НЕ затронуто**: `client_breaker.py`, `bulkhead.py`, `rate_limiter.py`,
`unified_rate_limiter.py`, `time_limiter.py`, `coordinator.py`,
`registration.py`, `health.py`, `snapshot_job.py`, `reconnection.py`,
`supervisor.py` — это полноценные реализации, не shim'ы.

**Verify**: `tests/unit/core/resilience/` 16/16 passed; targeted import smoke
для всех 7 callsites OK. `http_upstream.py` импортирует только
`client_breaker.py` (не shim) — не требует миграции.

**Feature-flag `new_resilience_v2`** в `ResilienceSettings`: можно убрать
в Sprint 2 после общей зачистки.

### Открытый техдолг (после сессии 2026-05-01 PM — pre-Wave 22)

---

## Deferred реестр Sprint 1–9 (2026-05-14, координатор-2)

> Wave: `[wave:s2-s9/known-issues-deferred-2026-05-14]`. Параллельная
> команда S4 закрывает Workflow DSL + BPMN + Temporal + WAF Phase-2.
> Координатор-2 закрыл ТОП-7 техдолга (см. ниже), остальное оформлено
> здесь как обоснованный deferred с привязкой к будущим Sprint'ам.

### A-фаза 2026-05-14: ЗАКРЫТО

| Wave | Файл / отчёт | Статус |
|---|---|---|
| `[wave:s1/k2-1-cache-decorator]` | `core/resilience/cache_decorators.py` (ADR-0051, in-house вместо aiocache) | ✅ pre-existing, проверено 11 тестов |
| `[wave:s1/k2-2-policy-decorator]` | `core/resilience/decorators.py` (ADR-0052, канонический порядок) | ✅ pre-existing, проверено 7 тестов |
| `[wave:s5/doc-generation-dsl]` | `dsl/engine/processors/documents.py` + `.render_docx`/`.render_xlsx` через python-docx + openpyxl (уже в deps) | ✅ 4 теста |
| `[wave:s6/msgspec-benchmark]` | `tests/perf/test_msgspec_benchmark.py` + `vault/benchmark-2026-05-14-msgspec.md` (msgspec в среднем ×5.5 быстрее) | ✅ |
| `[wave:s6/layer-violations-facade]` | `services/dsl_portal/` фасад; 2 frontend-pages переписаны; 6 baseline-violations закрыты | ✅ |
| `[wave:s8/rule-engine-scaffold]` | `dsl/engine/processors/rule_engine.py` + `.evaluate_rules()` через SimpleEval | ✅ 3 теста |
| `[wave:s2-s9/known-issues-deferred-2026-05-14]` | этот реестр | ✅ |

### S1 — deferred

* **`[wave:s1/asyncio-taskgroup]` migration DSL-процессоров** → **Sprint 5**.
  Зависит от parallel/streaming-split рефакторинга в
  `dsl/engine/processors/{parallel,streaming}.py` — эта зона активно
  меняется параллельной командой S4 (LLM-activity, Workflow DSL).
  Reason: избежать двойного рефакторинга.

* **`[wave:s1/result-monad]` `result>=0.17.0` + `ResultUnwrapProcessor`**
  → **Sprint 5**. Новый процессор, не критичный для S2-S4 deliverable.
  How to apply: после стабилизации control_flow processors S4 K3.

### S2 — deferred

* **Plugin codegen `make new-plugin NAME=x`** → **Sprint 7 sidekick (Team T5)**.
  Why: T5 уже владеет `core/plugin_runtime/`, hot-swap; codegen логично
  пристёгнуть к этой же миграции.
  How to apply: `tools/codegen/codegen_plugin.py` (уже scaffold существует)
  + Make-цель `new-plugin`.

* **Hot-reload DSL <3 сек graceful drain** → **Sprint 7 sidekick (Team T5)**.
  Why: hot_swap plugin API (Team T5 owns) — естественная база для
  graceful drain DSL-routes. Связано с feature-flag rollouts.

### S3 — deferred

* **Search-DSL final cleanup (Tavily Settings dedup + Perplexity dedup)**
  → **Sprint 7 sidekick (Team T4)**. См. PLAN #5 выше.

### S5 — deferred

* **R2 Blueprints (api_normalize, cdc_enrich, ai_pipeline, saga_with_compensation)**
  → **Sprint 7 (Team T4 захватит api_normalize в reference) + Sprint 8**
  (остальные). Зависит от R2 Sprint 5 blueprints API.
  Why: первый blueprint — pilot, остальные — после feedback.

* **CDC PostgreSQL logical replication** → **Sprint 8**. Большой scope,
  blocking — нет, отложить до RPA-волны.

* **DSL web-search expansion** → **Sprint 7 sidekick (Team T4)**.
  Cleanup из S3 deferred покрывает первый шаг.

* **Async Queue migration / DLQ unified / Dry-run** → **зависят от S4 Temporal**.
  Why: TaskIQ removal (BLOCKER #1 Sprint 2) и Temporal facade —
  предпосылка. Ожидать завершения S4 K1-K5.

### S6 — deferred

* **k6+locust perf-suite + p95<200ms gate** → **Sprint 8**.
  Why: нужен стабильный staging с auto-scaler K2 (Sprint 4 ✅) и
  k8s HPA exporter (S3 K2 W4 ✅). Запуск на готовой инфре.

* **COM-sidecar Windows RPA** → **Sprint 8**. Вместе с RPA-волной;
  Windows-only компонент.

* **Schemathesis CI gate** → **Sprint 8**. После стабилизации OpenAPI
  схем (S4 закрывает workflow endpoints — ждать).

* **Codeclone gate strict** → **Sprint 8**. Pre-prod check, не блокирует
  S2-S7 deliverable.

### S8 — deferred

* **patchright RPA (browser + Windows)** → **Sprint 8**. Тяжёлые
  зависимости (playwright + Windows-specific), отдельная волна.

* **HTTP/3 opt-in** → **Sprint 9**. Сетевая оптимизация —
  после стабилизации S4-S8 deliverable.

* **mypy ≤ 50 + deptry/vulture green** → **Sprint 9 financial cleanup**.

### S9 — deferred

* **≥9 tutorials + ≥10 runbooks** → **Sprint 9 docs wave**.
  Why: больше смысла писать после стабилизации features Sprint 7-8.

* **Visual Editor BPMN export** → **Sprint 9**.
  Why: S4 BPMN import — это первый шаг (`bpmn_importer.py` в WIP).
  Export — после.

* **Pre-prod-check gate (20 critia)** → **Sprint 9 final wave**.

---

## Sprint 7 запуск (2026-05-14)

5 worktree-команд параллельно по PLAN.md §4 Sprint 7. Каждая команда
работает в изолированном worktree через Agent с `isolation: "worktree"`.

| Team | Branch | Скоуп |
|---|---|---|
| T1 | `team/01-s7-core-entities-uo` | Migrate users + orders → `extensions/core_entities/` |
| T2 | `team/02-s7-core-entities-of-credit-scaffold` | Migrate orderkinds + files + scaffold `extensions/credit_pipeline/` |
| T3 | `team/03-s7-credit-1st-client` | 1st credit client + workflow YAML + feature_flag.credit_pipeline_v2 (blockedBy: T2) |
| T4 | `team/04-s7-admin-frontend` | sqladmin + 3 Streamlit pages + R2 Blueprint api_normalize |
| T5 | `team/05-s7-plugin-runtime-flags` | plugin hot-swap + blue/green + OpenFeature + make new-plugin |

**S4-охраняемые файлы** (не трогать):
`dsl/workflow/**`, `infrastructure/workflow/**`, `infrastructure/temporal/**`,
`services/workflows/**`, `core/workflow/**`, `services/ai/**`, `core/auth/**`,
`core/net/**`, `dsl/engine/processors/ai*.py`,
`plugins/composition/lifecycle.py`, `tools/checks/check_waf_coverage.py`.

---

## Sprint 6 запуск (2026-05-14, координатор-3)

5 worktree-команд параллельно по PLAN.md §6 (`Sprint 6 — Performance + Chaos +
Coverage + Security + OLE/COM + Observability`). Запуск **параллельно** с
текущим Sprint 5 (доделывается параллельной командой) и Sprint 7 (T1-T5
worktree миграция). Каждая команда работает в изолированном worktree через
Agent с `isolation: "worktree"`, делает intermediate commits после каждой
завершённой задачи. Pipeline-mode: координатор делает ff-merge / cherry-pick
в master без блокирующего подтверждения.

**Полный план**: `~/.claude/plans/effervescent-herding-fairy.md`.

| Team | Branch | Скоуп |
|---|---|---|
| K1 | `team/s6-k1-security` | SAML+AD финал, supply-chain полный CI gate, OWASP ZAP, custom-code-audit, codeclone strict, per-host metering финал (6 wave) |
| K2 | `team/s6-k2-resilience-perf` | k6+locust perf-suite, Granian RSGI ADR, DB pool tuning, structlog batching, processor-specific health, backpressure, schemathesis, service-doc gate (8 wave) |
| K3 | `team/s6-k3-dsl-workflow` | e2e один action × 6 протоколов, coverage gate ≥70%, banking-processors тесты (12), DSL Linter CLI + LSP, COM Windows sidecar (5 wave) |
| K4 | `team/s6-k4-ai-quality` | Inspect AI nightly eval, DSPy для critical pipelines, AI cost dashboard финал (3 wave) |
| K5 | `team/s6-k5-frontend-chaos` | 33 chaos-теста (11 chains × 3 сценария), DLQ-replay UI, Resilience Dashboard, Pool Monitor, 5 Grafana dashboards (5 wave) |

**Backbone-commit** перед запуском агентов (выполнен координатором):
- `src/backend/core/config/features.py` — 21 новый default-OFF feature-flag (S6 K1-K5)
- `.claude/team-ownership.toml` — раздел `[team_s6.k1]`..`[team_s6.k5]` с `owned_paths` + `forbidden_paths`
- `.claude/KNOWN_ISSUES.md` — этот раздел
- Wave-тег: `[wave:s6/backbone]`

**Уже досрочно закрытые задачи Sprint 6** (A-фаза 2026-05-14):
- ✅ `[wave:s6/msgspec-benchmark]` (`3743c574`)
- ✅ `[wave:s6/layer-violations-facade]` (`6b818829`)

**S5→S6 stub-контракты** (Protocol+Fake в `core/`, реальная impl в `infrastructure/` от S5 K2):
- `OutboxBackend` (`core/messaging/outbox.py`) — для K5 DLQ-replay UI и K2 perf-gate
- `AsyncQueueBackend` (`core/orchestration/async_queue.py`) — для K2 perf-gate
- `RetryEngine` (`core/resilience/retry.py`) — для K2 если Tenacity ещё не unified

Каждый stub имеет соответствующий `FakeXxx` для тестов; DI переключает на
реальную имплементацию через feature-flag когда S5 K2 закоммитит её в master.

**S4-охраняемые файлы + S7-захваченные пути** — см. `forbidden_paths` в
`.claude/team-ownership.toml::[team_s6.kN]`. Ключевые ограничения:
- `dsl/workflow/**`, `infrastructure/workflow/**`, `infrastructure/temporal/**` — S4 closed но активная пост-завершительная подчистка K3/K4
- `services/ai/agents*/`, `services/ai/gateway/` — S5 K4 owns
- `infrastructure/messaging/outbox_dispatcher.py` — S5 K2 owns
- `extensions/**`, `plugins/composition/**` — S7 T1-T5 owns
- `pages/{30_Files_S3,50_Workflow_Logs,80_Admin_Models}.py` — S7 T4 owns

**DoD Sprint 6** (по PLAN.md:623):
- [ ] p95<200ms / RPS>1000 — baseline зафиксирован, gate warn-only
- [ ] 33 chaos-теста зелёные (локально blocking, CI warn-only)
- [ ] coverage ≥70% (BLOCKING)
- [ ] SAML+AD логин
- [ ] SBOM в каждом релизе
- [ ] OWASP ZAP gate зелёный (warn-only)
- [ ] codeclone gate `--fail-on-new-clones`
- [ ] COM-sidecar тест на Windows (или mock)
- [ ] CI docs-gate зелёный
- [ ] schemathesis в CI (warn-only)
- [x] msgspec hotpath benchmark задокументирован (`vault/benchmark-2026-05-14-msgspec.md`)
- [x] layer-violations через `services/dsl_portal/` фасад → 0
