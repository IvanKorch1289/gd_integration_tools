# SPRINT_8_PLAN.md — финальное закрытие PLAN.md V17

> **Версия документа**: Sprint 8 plan (создан 2026-05-15).
> **Связь**: `PLAN.md` V17 §4 Sprint 8 + carryover из S5/S6/S7 + 2 открытых BLOCKER.
> **Длительность**: 2 недели = Sprint 8A (1 нед) + Sprint 8B (1 нед).
> **Команды**: 5 (К1 Security / К2 Resilience+Perf+Quality / К3 DSL+Workflow+RPA+Net /
> К4 AI+RAG+Quality / К5 Frontend+Ext+Mig+Docs). Ownership: `.claude/team-ownership.toml`.
> **Итого wave**: 9 (К1) + 12 (К2) + 13 (К3) + 11 (К4) + 7 (К5) + 2 (backbone + finale) = **54 wave**.

---

## 0. Контекст и предпосылки

### Состояние master (HEAD `e7051065` после Sprint 7 round 2 + 3 carryover wave закрытых in-flight 2026-05-15 09:58)

> **Race-update**: пока составлялся этот план, параллельная сессия закрыла 3 wave,
> которые числились в Sprint 8A carryover:
>
> - `12c2f25f [wave:s7/k3-dsl-blueprints-migrate]` → закрывает Sprint 8 К3 W8
>   (`dsl/blueprints/` subdir). **Wave удалён из 8A.**
> - `116f40ec [wave:s7/k3-workflow-versioning]` → закрывает Sprint 8 К3 W9
>   (Temporal patched API + per-workflow semver). **Wave удалён из 8A.**
> - `e7051065 [wave:s7/k5-3-streamlit-pages]` → закрывает Sprint 8 К5 W2/W3/W4
>   (70_Tenants + 71_Capabilities + 30_Files_S3 в одном коммите). **3 wave удалены из 8A.**
>
> **Скорректированный объём**: Sprint 8 = 54 - 5 = **49 wave** (К1=9, К2=12,
> К3=11, К4=11, К5=4, backbone+finale=2).


* **Sprint 6**: 24 wave-commits, DoD ≈ 92.9%.
* **Sprint 7**: 13 wave-commits, DoD ≈ 93% (T1-T5 + K1 billing + K4 multi-agent
  + Voice + Image gen + DLQ Replay UI + Resilience Dashboard + Pool Monitor +
  cosign finale).
* **Sprint 5**: 17 wave-commits (К3 W1-W12 + К4 W1-W2 + К5 W1 + backbone + doc-gen).
  Не в master: К2 round 1 (W2-W9), К3 round 2 (W13-W14), К4 round 1 (W3-W11),
  К1 round 2 — все мигрируют в Sprint 8A **через чистую реализацию**, не
  cherry-pick полуготовых reflog-коммитов.
* **BLOCKER #1**: TaskIQ removal — 13 callsites `Invoker.ASYNC_QUEUE`.
* **BLOCKER #3**: WAF Phase-2 — 38 прямых `httpx.AsyncClient()` callsites.
* **5 quotas тестов fail** (Sprint 7 K1 регрессия).

### Audit findings 2026-05-15 (см. `.claude/KNOWN_ISSUES.md::Audit findings`)

* ❌ Quotas tests fail → S8 K1 W0.
* ⚠️ Plugin hot-swap путь в PLAN.md ≠ реальный (`core/plugin_runtime/hot_swap.py`,
  не `services/plugins/hotswap*`) — docs-drift, runtime функционал закрыт.
* ⚠️ windows-sidecar layout ≠ V17 windows_worker/ → S8 K3 W1.

### worktree state

* 36 worktree-agent веток, 1 NOVEL (`worktree-agent-a21edb7fe3ead5b8c`,
  `[wave:s5/k5-w1-workflow-logs-ui]` — `66_Workflow_Logs.py`).
* Triage-report: `vault/triage-worktrees-2026-05-15.md`.
* Cleanup ожидается перед началом Sprint 8 (документированные команды в report).

---

## 1. Стратегия Sprint 8A + 8B

Sprint 8 разбит на 2 sub-sprint'а по неделе с явным DoD каждой половины.
Sprint 9 = только финальная documentation + Visual Editor + pre-prod gate
(PLAN.md V17 §4 Sprint 9 строки 660-670).

### Sprint 8A — Blockers + Carryover (~28 wave / 1 неделя)

Фокус: закрыть открытые BLOCKER и hangover из S5/S6/S7 до начала нового scope.

* К1 (6): W0 quotas-fix, W1 WAF Phase-2, W2 DLQ-replay RBAC, W3 Inbox audit PII,
  W5 cosign-all, W6 OpenFeature-Flagsmith.
* К2 (7): W1 TaskIQ removal, W2 Outbox dispatcher, W3 DLQ unified, W4 Inbox
  fail-closed, W5 alerts+fallback chains, W6 Bulkhead defaults, W7 tenant
  rate-limit namespace.
* К3 (6): W1 windows-worker rename, W8 dsl/blueprints/ subdir, W9 Workflow
  versioning, W10 TaskGroup, W11 invoke_workflow reply, W13 plugin-hotswap
  enhancement.
* К4 (8): W1 Multimodal RAG, W2 RLM hierarchical, W3 RAG cache invalidation,
  W4 BGE-M3 reranker, W6 mem0 + `.rag_*/memory_*` DSL, W7 Saga blueprint,
  W8 LiteLLM final, W1 (К1 owned) PII DSL step.
* К5 (3): W2 Streamlit 70_Tenants, W3 71_Capabilities, W4 30_Files_S3.

**DoD 8A**:

* BLOCKER #1 + #3 closed (`rg "^(from|import) taskiq" src/` = 0; WAF strict).
* 5 quotas tests green.
* `core/plugin_runtime/hot_swap.py` enhanced (state migration + version conflict).
* cosign all artifacts (включая plugin TOML manifests).
* Multimodal RAG ingests PDF/image.
* DLQ unified для 4 transport-types (HTTP/SOAP/gRPC/Webhook).

### Sprint 8B — Native PLAN.md S8 + finale (~26 wave / 1 неделя)

Фокус: новый scope Sprint 8 из PLAN.md V17 §4 строки 646-657.

* К1 (3): W4 PII DSL (если не зашёл в 8A), W7 prompt-injection guardrails,
  W8 pre-receive docstring hook.
* К2 (5): W8 httpx unify, W9 Grafana+SLO alerts, W10 mypy≤50, W11
  deptry/vulture clean, W12 layer-violations zero.
* К3 (7): W2 patchright pool, W3 RPA OCR, W4 RPA Windows desktop (pywinauto),
  W5 rule-engine DSL, W6 HTTP/3+WebTransport, W7 legacy DSL Python→YAML,
  W12 MCP via FastMCP.
* К4 (5): W5 7 RAG Streamlit pages, W9 AI model registry, W10 batch inference,
  W11 code-interpreter + `.llm_structured`.
* К5 (4): W1 4 credit clients (DaData / БКИ / СМЭВ / ЦБ / 1С), W5 @st.fragment
  live, W6 Wiki Whoosh+Diátaxis+Vale, W7 Sphinx multi-version.
* finale (2): backbone (pyproject + feature-flags), finale (flip critical
  default-ON post-smoke).

**DoD 8B**:

* 5 credit clients live в `extensions/credit_pipeline/services/clients/`.
* RPA stage 1: patchright + pywinauto + OCR.
* `.evaluate_rules()` + `.llm_structured()` working.
* HTTP/3 opt-in (smoke через `aioquic`).
* mypy ≤ 50.
* layer violations = 0.
* deptry green.
* Streamlit Wiki c Whoosh поиском.
* Multi-version Sphinx published.

---

## 2. Wave-матрица

### 2.1 К1 Security — 9 wave

| Wave | Tag | Scope |
|------|-----|-------|
| W0 | `[wave:s8/k1-w0-quotas-tests-fix]` | Sprint 7 K1 carryover: починить 5 unit-тестов `tests/unit/core/auth/test_quotas*` + `tests/unit/services/billing/test_quotas_service*`. |
| W1 | `[wave:s8/k1-w1-waf-phase2]` | **BLOCKER #3 closure**: migrate 38 `httpx.AsyncClient()` callsites → `OutboundHttpClient`; flip `feature_flags.waf_outbound_via_facade` default-ON. ADR-0053 Proposed → Accepted. |
| W2 | `[wave:s8/k1-w2-dlq-replay-rbac]` | Sprint 5 carryover: admin-only RBAC + audit-event на каждый DLQ-replay. |
| W3 | `[wave:s8/k1-w3-inbox-audit-pii]` | Sprint 5 carryover: Inbox dedup audit с PII-mask. |
| W4 | `[wave:s8/k1-w4-pii-dsl-step]` | Sprint 5 К4 carryover (К1 owner по security): `.mask_pii(fields, level)` / `.unmask_pii(fields, vault_key)` DSL builder + processor. |
| W5 | `[wave:s8/k1-w5-supply-chain-cosign-all]` | Sprint 7 К1 carryover: cosign sign все артефакты (включая plugin TOML manifests). |
| W6 | `[wave:s8/k1-w6-openfeature-flagsmith]` | Sprint 7 К1 carryover: OpenFeature → Flagsmith default-ON в staging compose. |
| W7 | `[wave:s8/k1-w7-prompt-injection-guardrails]` | PLAN.md S8 native: Lakera + Rebuff classifiers для AI prompts. |
| W8 | `[wave:s8/k1-w8-pre-receive-docstring]` | PLAN.md S8 native: git pre-receive hook на git-server для docstring policy. |

### 2.2 К2 Resilience+Perf+Quality — 12 wave

| Wave | Tag | Scope |
|------|-----|-------|
| W1 | `[wave:s8/k2-w1-taskiq-removal]` | **BLOCKER #1 closure**: 0 импортов `taskiq` в `src/`; миграция 13 `Invoker.ASYNC_QUEUE` → Temporal cron / APScheduler. R-V15-7. |
| W2 | `[wave:s8/k2-w2-outbox-dispatcher]` | Sprint 5 carryover: `infrastructure/messaging/outbox_dispatcher.py` поверх Protocol+Fake `core/messaging/outbox.py` (`36ca6757` уже в master). |
| W3 | `[wave:s8/k2-w3-dlq-unified]` | Sprint 5 carryover: DLQ unified для HTTP/SOAP/gRPC/Webhook; DLQ-table в Postgres + replay API; DSL `.dlq(target, max_attempts=N)`. |
| W4 | `[wave:s8/k2-w4-inbox-fail-closed]` | Sprint 5 carryover: Inbox dedup `seen_or_mark()` raise `InboxUnavailable` при Redis-error. |
| W5 | `[wave:s8/k2-w5-alerts-and-fallback-chains]` | Sprint 5 carryover: 5 alerts (CB / degradation / RL / queue / error-budget) + 2 fallback chains (graylog_chain + genai_chain). |
| W6 | `[wave:s8/k2-w6-bulkhead-defaults]` | Sprint 5 carryover: Bulkhead defaults в `ResilienceSettings`. |
| W7 | `[wave:s8/k2-w7-tenant-rate-limit-namespace]` | Sprint 5 carryover: per-tenant rate-limit namespace. |
| W8 | `[wave:s8/k2-w8-httpx-unify]` | Sprint 7 carryover: `httpx + httpx-retries + httpx-cache (hishel)` unify. Adapter `httpx_cache_adapter.py` уже в working tree. |
| W9 | `[wave:s8/k2-w9-grafana-and-slo-alerts]` | Sprint 7 carryover: 7 Grafana dashboards финал + 3 SLO-burn alerts. |
| W10 | `[wave:s8/k2-w10-mypy-le-50]` | PLAN.md S8 native: mypy ошибок ≤50 (R3 цель). |
| W11 | `[wave:s8/k2-w11-deptry-vulture-clean]` | PLAN.md S8 native: deptry/vulture clean + heavy deps в `[project.optional-dependencies]`. |
| W12 | `[wave:s8/k2-w12-layer-violations-zero]` | PLAN.md S8 native: 6 baseline layer violations → 0 через фасад `services/dsl_portal/`. |

DI container migration evaluation (PLAN.md S8 К2) → defer на Sprint 9 evaluation
(требует ADR-решение, не закрывает работу).

### 2.3 К3 DSL+Workflow+RPA+Net — 13 wave

| Wave | Tag | Scope |
|------|-----|-------|
| W1 | `[wave:s8/k3-w1-windows-worker-rename]` | Phase A.2 closure: `windows-sidecar/` → `windows_worker/` (PEP 8 + V17); `app.py` → `main.py`; split `com_router.py` → `handlers/com_handler.py` + scaffold `handlers/desktop_rpa_handler.py`; commit `docker-compose.windows-worker.yml`. |
| W2 | `[wave:s8/k3-w2-rpa-patchright-pool]` | PLAN.md S8 native: `patchright` + `PlaywrightBrowserPool` worker-pool; DSL `.browser_launch/.navigate/.click/.fill/.extract/.wait_for/.screenshot/.pdf`. |
| W3 | `[wave:s8/k3-w3-rpa-ocr]` | PLAN.md S8 native: PaddleOCR + EasyOCR providers для `.extract_text(provider="paddle"|"easy")`. |
| W4 | `[wave:s8/k3-w4-rpa-windows-desktop]` | PLAN.md S8 native: `pywinauto>=0.6.8` для Windows desktop UI через sidecar `handlers/desktop_rpa_handler.py`; DSL `.desktop_rpa(app, action, params)`. |
| W5 | `[wave:s8/k3-w5-rule-engine-dsl]` | PLAN.md S8 native: `.evaluate_rules(ruleset, input)` + `simpleeval` evaluator + ruleset в БД + reload через feature-flag. Scaffold `30d24195` уже в master, нужна полная реализация. |
| W6 | `[wave:s8/k3-w6-http3-webtransport]` | PLAN.md S8 native: `aioquic` opt-in HTTP/3 + WebTransport. |
| W7 | `[wave:s8/k3-w7-legacy-dsl-python-to-yaml]` | PLAN.md S8 native: миграция legacy DSL routes Python → YAML (audit + переписать). |
| W8 | `[wave:s8/k3-w8-dsl-blueprints-subdir]` | Sprint 7 carryover: `dsl/macros.py`/`dsl/blueprints.py` → `dsl/blueprints/` подпапка с per-blueprint модулями. |
| W9 | `[wave:s8/k3-w9-workflow-versioning]` | Sprint 7 carryover: Temporal `patched` API + per-workflow semver через `Workflow DSL`. |
| W10 | `[wave:s8/k3-w10-workflow-taskgroup]` | Sprint 5 К3 W13 carryover: `asyncio.TaskGroup` migration в workflow runner. |
| W11 | `[wave:s8/k3-w11-invoke-workflow-reply]` | Sprint 5 К3 W14 carryover: `invoke_workflow` reply-mode (sync через Temporal signal). |
| W12 | `[wave:s8/k3-w12-mcp-via-fastmcp]` | Sprint 5 К4 carryover (code-зона DSL/MCP — К3): FastMCP auto-export Tier 1+2 actions + DSL `expose_mcp = true` + LangFuse `@mcp.prompt`. |
| W13 | `[wave:s8/k3-w13-plugin-hotswap-impl]` | Audit-finding: расширение `core/plugin_runtime/hot_swap.py` (state migration + version-conflict handling). CLI `manage.py plugin hot-swap` уже использует базовую функцию. |

### 2.4 К4 AI+RAG+Quality — 11 wave

| Wave | Tag | Scope |
|------|-----|-------|
| W1 | `[wave:s8/k4-w1-multimodal-rag]` | Sprint 5 carryover: docling + PaddleOCR / EasyOCR; DSL `.rag_ingest(source, modal="text"|"image"|"audio")`. |
| W2 | `[wave:s8/k4-w2-rlm-hierarchical-memory]` | Sprint 5 carryover: MemGPT-style hierarchical memory toolkit. |
| W3 | `[wave:s8/k4-w3-rag-cache-invalidation]` | Sprint 5 carryover: 3-уровневый RAG cache invalidation через Redis pub/sub. L3 уже в master `28642fd6`. |
| W4 | `[wave:s8/k4-w4-bge-m3-reranker]` | Sprint 5 carryover: BGE-M3 + bge-reranker-v2.5 как параллельный EmbeddingProvider. |
| W5 | `[wave:s8/k4-w5-rag-streamlit-pages-7]` | Sprint 5 carryover: 7 Streamlit RAG страниц (Inspector / Trace / ClusterMap / EvalDashboard / CacheDashboard / Playground / IngestWizard). |
| W6 | `[wave:s8/k4-w6-mem0-rag-memory-dsl]` | Sprint 5 carryover: `mem0ai>=0.1.0` + `.rag_query/.rag_upsert/.rag_delete/.memory_write/.memory_read` DSL. |
| W7 | `[wave:s8/k4-w7-saga-blueprint]` | Sprint 5 carryover: `saga_with_compensation` Blueprint R2 dual-mode. |
| W8 | `[wave:s8/k4-w8-litellm-final]` | Sprint 5 carryover: LiteLLM gateway financial (cost-budget + retry + fallback). |
| W9 | `[wave:s8/k4-w9-ai-model-registry]` | PLAN.md S8 native: MLflow + Hugging Face Hub adapter. |
| W10 | `[wave:s8/k4-w10-batch-inference]` | PLAN.md S8 native: vLLM / TGI client. |
| W11 | `[wave:s8/k4-w11-code-interpreter-and-llm-structured]` | PLAN.md S8 native: e2b.dev / pyodide-wasm sandboxing + `.llm_structured(model, output_schema, prompt, retry=3)` через `instructor>=1.7.0`. |

### 2.5 К5 Frontend+Ext+Mig+Docs — 7 wave

| Wave | Tag | Scope |
|------|-----|-------|
| W1 | `[wave:s8/k5-w1-credit-clients-4]` | PLAN.md S8 native: миграция 4 клиентов кредитного конвейера (DaData / БКИ / СМЭВ / ЦБ / 1С) в `extensions/credit_pipeline/services/clients/`. |
| W2 | `[wave:s8/k5-w2-streamlit-tenants]` | Sprint 7 carryover: `70_Tenants.py` Streamlit page. |
| W3 | `[wave:s8/k5-w3-streamlit-capabilities]` | Sprint 7 carryover: `71_Capabilities.py`. |
| W4 | `[wave:s8/k5-w4-streamlit-files-s3]` | Sprint 7 carryover: `30_Files_S3.py`. |
| W5 | `[wave:s8/k5-w5-streamlit-fragments-live]` | Sprint 7 carryover: `@st.fragment(run_every=2)` для live workflow logs. |
| W6 | `[wave:s8/k5-w6-wiki-whoosh-diataxis]` | PLAN.md S8 native: Streamlit Wiki (Whoosh + live DSL examples + Diátaxis + Vale prose + ru proofreader). |
| W7 | `[wave:s8/k5-w7-sphinx-multiversion]` | Multi-version Sphinx + ReadTheDocs / GitLab Pages publish. |

### 2.6 Backbone + finale

* `[wave:s8/backbone]` — обновить `pyproject.toml` (`aioquic`, `patchright`,
  `pywinauto`, `mlflow`, `vllm-client`, `e2b`, `pyodide`, `instructor`,
  `mem0ai`, `tavily-python`, `perplexityai`, `docxtpl`, `xlsxwriter`,
  `simpleeval` в нужные `[project.optional-dependencies]`); 54 feature-flag
  default-OFF.
* `[wave:s8/finale]` — flip critical feature-flags default-ON после staging-smoke
  (`feature_flags.taskiq_removed`, `feature_flags.waf_outbound_via_facade`,
  `feature_flags.com_sidecar_enabled`, `feature_flags.rule_engine_enabled`).

---

## 3. DoD Sprint 8 (15 критериев)

К концу Sprint 8B все 15 пунктов должны быть ✅:

1. `rg "^(from|import) taskiq" src/` = 0 строк, `taskiq` удалён из `pyproject.toml`.
2. `rg "httpx\.AsyncClient\(\)" src/` = 0 строк (кроме `core/net/`);
   `make check-waf-coverage` strict-blocking.
3. mypy ошибок ≤ 50 (`make type-check-strict`).
4. `make deps-check-strict` + `vulture --min-confidence 80` green.
5. layer violations = 0 (`tools/checks/check_layers.py`).
6. 5 клиентов кредитного конвейера в `extensions/credit_pipeline/services/clients/`.
7. RPA stage 1: patchright + pywinauto + OCR DSL-шаги с integration tests.
8. `.evaluate_rules()`, `.llm_structured()`, `.mask_pii/.unmask_pii`,
   `.rag_*/.memory_*` builder + processor + tests.
9. HTTP/3 opt-in работает (smoke test через `aioquic` client).
10. AI model registry (MLflow + HF adapter) с тестами.
11. Streamlit Wiki с Whoosh поиском.
12. 4 Streamlit pages (70 / 71 / 30 + @st.fragment).
13. `windows-sidecar` → `windows_worker` rename + handler split.
14. Multi-version Sphinx опубликован.
15. coverage ≥ 75% (от 70% baseline в S6).

---

## 4. NOT in Sprint 8 — переносится в Sprint 9

* DI container migration ADR-решение (требует benchmark + diff в отдельной
  ветке `prototype/di-container`).
* DSL Visual Editor finale (Streamlit drag-drop) — К3 + К5 финал.
* 9 tutorials + 10 runbooks (Diátaxis docs).
* mem0 / Zep persistent personalisation для `credit_pipeline`.
* Streamlit `60_AI_Agent_Monitor.py`.
* Pre-production gate checklist (20 критериев `make pre-prod-check`).
* Free-threading PEP 703 benchmark.
* DR runbook + backup verification.
* Snapshot / restore профили для dev_light.
* Legacy workflow Python → YAML migration финал.

---

## 5. Verification per phase

Базовый набор после каждого wave-commit:

* `make verify-change` (composite: lint + type-check + targeted tests).
* `make check-waf-coverage` (для К1/К2 wave).
* `make routes && make actions && make plugin-schema && make route-schema &&
  make service-schema` (для К3 DSL wave).
* `pytest tests/integration/rpa/ tests/e2e/test_rule_engine.py
  tests/integration/ai/test_model_registry.py` (для К3 RPA / rule-engine /
  К4 model registry).
* `manage.py workflow dryrun` для каждого нового blueprint.

Финальная верификация перед закрытием Sprint 8:

* `make ci` (composite: lint + type + test + coverage + security) — green.
* `make pr` (= ci + docs) — green.
* `make perf` — p95 < 200 ms / RPS > 1000 (Sprint 6 baseline).
* `make chaos` — 33 теста green.
* `make custom-code-audit` — 0 findings.
* `make pre-prod-check` (если уже подключён в Sprint 9) — warn-only.

---

## 6. Координация и риски

### 6.1 Branch isolation (lesson из 4 race conditions)

Каждая команда работает в отдельной ветке:

* `team/s8-k1-security`
* `team/s8-k2-resilience-perf-quality`
* `team/s8-k3-dsl-workflow-rpa-net`
* `team/s8-k4-ai-rag-quality`
* `team/s8-k5-frontend-ext-mig-docs`

Координатор делает ff-merge / cherry-pick из team-веток в master после
intermediate commits каждого wave.

### 6.2 Запрещённые зоны

* К1 не трогает `dsl/` (К3 owner) — DSL-PII шаги передаются К3 после
  основной логики.
* К2 не трогает `core/auth/` (К1 owner) — quotas / RBAC изменения через
  взаимный review.
* К3 не трогает `services/ai/` (К4 owner) — MCP `expose_mcp` шапка
  декларативна, реальный AI-payload — К4.
* К4 не трогает `infrastructure/messaging/` (К2 owner) — DLQ для AI
  происходит через общий unified DLQ из К2 W3.
* К5 не трогает `core/plugin_runtime/` (К3 owner) — Streamlit pages
  обращаются к hot-swap через CLI / REST.

### 6.3 BLOCKER coordination

* **BLOCKER #1 TaskIQ removal** (К2 W1) блокирует К4 batch inference (К4 W10)
  если в callsites есть AI-pipelines на TaskIQ. К2 публикует migration shim
  default-OFF, К4 параллельно мигрирует AI callsites после flip.
* **BLOCKER #3 WAF Phase-2** (К1 W1) блокирует К4 model registry HTTPS
  external calls (HF Hub / MLflow remote). К1 публикует `OutboundHttpClient`
  helper, К4 использует с первого wave.

### 6.4 Worktree cleanup до старта

Перед запуском team-веток выполнить triage-cleanup согласно
`vault/triage-worktrees-2026-05-15.md`. Цель: `git worktree list` = 1-2 строки
(main + опционально `worktree-k3-recovery`).

---

## 7. Ссылки

* `PLAN.md` V17 §4 (главный roadmap).
* `.claude/KNOWN_ISSUES.md` (audit findings + Sprint 5 carryover + BLOCKERs).
* `.claude/CONTEXT.md` (оперативная сводка).
* `.claude/team-ownership.toml` (зоны 5 команд).
* `vault/triage-worktrees-2026-05-15.md` (worktree cleanup инструкции).
* `vault/session-2026-05-15-1030-s7-closure-round2-summary.md` (Sprint 7 closure).
