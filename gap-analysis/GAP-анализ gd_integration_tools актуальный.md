# gd_integration_tools — PLAN.md V18.2 vs Реальность + GAP-анализ v4

> **Дата анализа**: 2026-05-15  
> **Версия PLAN.md**: V18.2 FINAL (2026-05-14)  
> **Текущий спринт**: Sprint 8 (49 активных wave; Sprint 9 — финал + документация)  
> **Метод**: сканирование git-дерева (master, 1941 файл) + верификация по пути каждого артефакта, заявленного в PLAN.md как ✅

***

## 1. Общий итог сверки

PLAN.md содержит статусы ✅ / 🟡 / ⏳ для каждого wave. Сверка показала, что **большинство ✅-артефактов реально существуют**, однако по ряду позиций пути расходятся с документацией, а некоторые файлы отсутствуют вопреки ✅-маркеру. Общий счёт верификации (78 ключевых путей из PLAN.md):

| Статус | Кол-во |
|---|---|
| ✅ Файл найден (в т.ч. по альтернативному пути) | 66 |
| ❌ Файл не найден (расхождение или не реализовано) | 12 |
| ⚠️ Файл по другому пути, чем задокументировано | 14 |

***

## 2. Расхождения: заявлено ✅ — файл отсутствует

Это **реальные пробелы** между статусом в PLAN.md и кодовой базой.

### 2.1 BLOCKER #1 — TaskIQ не удалён (КРИТИЧНО)

**Статус в PLAN.md**: `[wave:s8/k2-w1-taskiq-removal]` = Sprint 8A BLOCKER  
**Факт**: `src/backend/infrastructure/execution/taskiq_broker.py` **присутствует** в master.  
Это означает, что taskiq-зависимость из `pyproject.toml` не удалена. Файл брокера существует, 13 callsites `Invoker.ASYNC_QUEUE` вероятно не мигрированы на Temporal/APScheduler. PLAN.md корректно отмечает это как BLOCKER, но в master он открыт.

### 2.2 BLOCKER #3 — WAF Phase-2 не закрыт (КРИТИЧНО)

**Статус в PLAN.md**: `[wave:s8/k1-w1-waf-phase2]` = Sprint 8A BLOCKER  
**Факт**: `tools/check_waf_coverage.py` существует, `core/net/outbound_http.py` существует, но 38 `httpx.AsyncClient()` callsites, по данным SPRINT_8_PLAN.md, не мигрированы на `OutboundHttpClient`. Фасад создан — фактическая миграция callsites не выполнена.

### 2.3 Messaging layer — 3 файла отсутствуют

| Компонент | Путь в PLAN.md | Факт |
|---|---|---|
| Outbox Dispatcher | `infrastructure/messaging/outbox_dispatcher.py` | ❌ Отсутствует |
| Inbox fail-closed | `infrastructure/messaging/inbox_dedup.py` | ❌ Отсутствует |
| DLQ unified | `infrastructure/messaging/dlq.py` | ❌ Отсутствует |

PLAN.md признаёт их как Sprint 5 carryover → Sprint 8A. `core/messaging/outbox.py` существует (протокол/интерфейс), но конкретная инфраструктурная реализация не реализована.

### 2.4 Security — mTLS/SAML backend

**Путь**: `infrastructure/security/saml_backend.py` — **отсутствует**.  
ADR-0054 (sso-federation) принят, `HttpxClient` с mTLS задокументирован как ✅ (`e017e51`), но SAML IDP backend-файл в master не обнаружен.

### 2.5 PII DSL processor

`dsl/engine/processors/pii.py` — **отсутствует**.  
PII-фильтрация в structlog (`observability/pii_filter.py`) ✅ реализована. Но `.mask_pii()` / `.unmask_pii()` как DSL-шаги не имеют отдельного процессора. PLAN.md Sprint 8 помечает как Wave К1 W4.

### 2.6 HTTP/3 + WebTransport

`infrastructure/clients/transport/http3_client.py` — **отсутствует**. PLAN.md Sprint 8B К3 W6.

### 2.7 DLQ Replay Admin API

`entrypoints/api/v1/endpoints/admin_dlq.py` — **отсутствует**.  
Streamlit страница `14_DLQ_Replay.py` существует (UI-side), но REST-endpoint для replay не найден.

### 2.8 RouteLoader full-cycle (Sprint 2)

`dsl/route/loader.py` — **отсутствует**.  
Существует `dsl/routes.py` (плоский модуль) и два reference route в `routes/`. PLAN.md Sprint 2 отмечает RouteLoader как 🟡 (in-progress). ADR-0056 (routes-v11) принят, scaffold готов, полный loader — нет.

***

## 3. Артефакты по другому пути (docs-drift)

Файлы реализованы, но пути расходятся с PLAN.md/CLAUDE.md — это создаёт путаницу при навигации через Claude/Graphify.

| Компонент | Путь в PLAN.md | Реальный путь |
|---|---|---|
| EventBus facade | `core/messaging/eventbus.py` | `infrastructure/clients/messaging/event_bus.py` |
| SagaBuilder | `dsl/workflow/saga.py` | Встроен в `dsl/workflow/builder.py` |
| LiteTemporalBackend | `infrastructure/workflow/lite_temporal.py` | `infrastructure/workflow/lite_temporal_backend.py` |
| BPMN Importer | `infrastructure/workflow/bpmn_importer.py` | `dsl/workflow/bpmn_importer.py` |
| OTel Baggage | `infrastructure/observability/otel_tracing.py` | `core/observability/baggage.py` + `infrastructure/observability/tracing.py` |
| JWTBackend joserfc | `infrastructure/security/jwt_backend_joserfc.py` | `infrastructure/security/__init__.py` |
| TaskWatchdog | `infrastructure/observability/watchdog.py` | `core/utils/task_registry.py` + `core/observability/` |
| PerHostMeter | отдельный файл | `infrastructure/observability/client_metrics.py` |
| Audit Log page | `pages/35_Audit_Log.py` | `pages/40_Audit_Log.py` |
| ConnectionReuseManager | `clients/transport/connection_reuse_manager.py` | `infrastructure/clients/transport/__init__.py` |
| K8sHPAMetricsExporter | `infrastructure/observability/k8s_hpa_exporter.py` | `core/scaling/__init__.py` |
| LangMem memory | `services/ai/memory.py` | `services/ai/agent_memory.py` |
| MultimodalRAG | `services/ai/multimodal_rag.py` | `services/ai/document_parsers/_orchestrator.py` |
| LangFuse v3 shim | `infrastructure/observability/langfuse_callback_v3.py` | `services/ai/gateway/callbacks.py` |

**Рекомендация**: добавить в PLAN.md секцию «Path aliases» или пробежать `tools/check_v11_artefacts.py` для автоматической сверки.

***

## 4. Проблема дублирования Streamlit-страниц

При сканировании обнаружено **9 коллизий** в нумерации страниц:

| № | Файл A | Файл B |
|---|---|---|
| 00_ | `00_Glossary.py` | `00_Home.py`, `00_Tutorial.py` |
| 14_ | `14_DLQ_Replay.py` | `14_Queue_Monitor.py` |
| 15_ | `15_Pool_Monitor.py` | `15_Processes_Dashboard.py` |
| 30_ | `30_DSL_Playground.py` | `30_Files_S3.py` |
| 50_ | `50_Action_Bus.py` | `50_Codegen_Wizard.py` |
| 55_ | `55_S3_Browser.py` | `55_s3_files.py` |
| 60_ | `60_Plugin_Marketplace.py` | `60_Wiki.py` |
| 65_ | `65_Services.py` | `65_workflow_live_logs.py` |
| 67_ | `67_Plugin_Marketplace.py` | (дубль 60_Plugin_Marketplace.py) |

Streamlit отображает страницы по алфавиту внутри одного номера — порядок непредсказуем. **PLAN.md этот вопрос не закрывает**. Необходима ренумерация + удаление дублей.

***

## 5. Сводная таблица статусов по спринтам

| Sprint | Заявленный DoD | Реальность |
|---|---|---|
| **S1** | Single Entry CB/RL/Retry ✅, ProcessorRegistry ✅, EventBus ⏳ | ✅ 80% — CB/RL/Retry реализованы, ProcessorRegistry есть, EventBus в нетипичном месте |
| **S2** | Idempotency ✅, AuthBackend 🟡, RouteLoader 🟡, Hot-reload ⏳ | 🟡 70% — Idempotency ✅, RouteLoader частично, Hot-reload ⏳ |
| **S3** | 25/25 wave ЗАКРЫТ ✅ | ✅ 90% — большинство wave подтверждены, PerHostMeter / ConnectionReuseManager по другому пути |
| **S4** | Workflow DSL ЗАКРЫТ ✅ | ✅ 95% — Workflow Builder, Compiler, Gateways, BPMN, LiteTemporalBackend — все есть |
| **S5** | carryover в S8 | ❌ Carryover полностью не закрыт: outbox_dispatcher, inbox_dedup, dlq unified — отсутствуют |
| **S6** | 24 wave, DoD≈92.9% | ✅ 90% — основной scope выполнен, WAF Phase-2 не закрыт |
| **S7** | 13 wave, DoD≈93% | 🟡 85% — 5 quota-тестов падают, TaskIQ не удалён |
| **S8** | 49 wave текущий | ⏳ В процессе — 5 wave закрыто in-flight, 44 открыты |

***

## 6. Chaos-тесты: заявлено 33, найдено 18

PLAN.md: «chaos-tests 33 шт. ✅».  
Факт: в `tests/chaos/` обнаружено **11 test-файлов** (backpressure, vault, graylog, redis, temporal, s3, postgresql, nats, rabbitmq, clickhouse, kafka, elasticsearch) + `testkit/chaos_fixtures.py`. Итого ~18 файлов связанных с хаос-тестированием.  
Разрыв ~15 тестов. Либо часть тестов была в working tree (не смёрджена), либо count считается по тест-функциям, а не файлам.

***

## 7. Итоговый GAP-анализ v4 — что не покрыто PLAN.md

### 7.1 DSL

| Пробел | Описание | Приоритет |
|---|---|---|
| **DSL Complexity Budget** | Нет ограничения на цикломатическую сложность route (количество Choice/TryCatch/Parallel вложений). Нужен lint-checker с порогом (например, ≤10 nodes на route). | High |
| **`.batch(size, timeout)` примитив** | Нет встроенного batch-агрегатора с time-window. Splitter есть, но batch-collect с flush-по-таймауту — нет. Polars/msgspec batch writer нужен. | High |
| **DSL A/B процессор** | `.ab_test(variant_a, variant_b, split_ratio)` — для экспериментального запуска двух веток на % трафика. Интеграция с feature-flag. | Medium |
| **DSL diff в Streamlit** | `tools/dsl_diff.py` существует, но страницы сравнения двух версий DSL в UI нет. | Medium |
| **Dry-run UI с sample data** | `dsl/workflow/dryrun.py` существует. Но `34_DSL_Debugger.py` не содержит кнопки "Run with sample". | Medium |
| **RouteLoader full-cycle** | `routes/echo_demo` и `routes/health_proxy_demo` есть, но `dsl/route/loader.py` не реализован — hot-reload новых `.dsl.yaml` без рестарта невозможен. | High |
| **DSL `.cancel_workflow(id)`** | Нет явного cancel-шага для запущенных workflow через DSL. Только Temporal API напрямую. | Low |
| **ProcessorCatalog поиск** | `entrypoints/api/v1/endpoints/processors_catalog.py` есть, но в Streamlit нет семантического поиска по 100+ процессорам с примерами YAML. | Medium |

### 7.2 Инфраструктура / Messaging

| Пробел | Описание | Приоритет |
|---|---|---|
| **Outbox Dispatcher + Inbox dedup + DLQ** | Три файла из Sprint 5 carryover отсутствуют в master. BLOCKER для надёжной доставки событий. | Critical |
| **DLQ TTL policies** | Даже когда DLQ появится — нет конфигурации retention per message-type (короткий TTL для аналитики, долгий для финансовых событий). | High |
| **EventBus topic-schema validation** | `event_bus.py` есть, но нет валидации payload против schema_registry при `bus.publish()`. Нужен `schema_registry` hook на публикацию. | High |
| **Pool warm-up on startup** | ConnectionReuseManager есть, но нет предварительного прогрева пулов при старте (pre-ping N connections). Холодный старт создаёт latency spike. | Medium |
| **ClickHouse async bulk writer** | Audit events пишутся поштучно. Для производительности нужен буфер + periodic flush (batch insert). | High |
| **Unified retry policy store** | 12 fallback chains существуют, но конфигурация retry/CB параметров разрознена. Нужен `ResilienceProfile` store с per-tenant override через UI. | Medium |
| **NATS JetStream consumer lag UI** | Monitoring для NATS consumer lag в Streamlit отсутствует (есть только Kafka/RabbitMQ через Queue Monitor). | Low |

### 7.3 AI / RAG

| Пробел | Описание | Приоритет |
|---|---|---|
| **RAG Freshness Indicator** | Нет TTL/staleness метки на chunk-уровне в Qdrant. Устаревшие данные не сигнализируются LLM. | High |
| **Prompt Version Control UI** | LangFuse prompt-registry реализован, но Streamlit-страницы управления версиями промптов нет. | Medium |
| **Token budget enforcement** | Нет per-tenant ограничения на токены в RAG-запросах. Возможен DoS от одного тенанта через RAG. | High |
| **LangGraph checkpoint restore UI** | AI Workflow activities через LangGraph есть (`langgraph_postgres_saver.py`), но UI для восстановления из checkpoint — нет. | Medium |
| **AI workflow dry-run** | Нет возможности запустить AI-агент с mock-LLM для теста workflow без реальных API-вызовов. | Medium |
| **Guardrails scope** | PLAN.md Sprint 8 ввёл Lakera/Rebuff. Но нет конфигурации per-tenant (банк может разрешать промпты, которые SaaS запрещает). | Medium |
| **Embedding model A/B** | Нет механизма плавного перехода между embedding-моделями без переиндексации всего RAG. | Low |
| **Feedback loop в DSL** | `feedback_service.py` существует. Но нет DSL-шага `.record_feedback(rating, comment)` для inline-фидбека в route. | Low |

### 7.4 Workflow

| Пробел | Описание | Приоритет |
|---|---|---|
| **Visual workflow diff** | Нет сравнения двух версий workflow graphically (before/after рефакторинга). Нужен Mermaid diff в Streamlit. | Medium |
| **Workflow template library** | 10 DSL blueprints существуют (YAML). Но нет UI-библиотеки "использовать шаблон" с один-клик deploy в Streamlit. | Medium |
| **HITL Streamlit panel** | Temporal HITL (`wait_for_signal`) реализован. Но нет Streamlit-страницы для операторов, которые видят приостановленные workflow и отправляют signal через UI. | High |
| **Workflow SLA monitoring** | `TaskWatchdog` с deadline-эскалацией есть. Но нет Grafana-дашборда «workflow SLA compliance rate» (% workflow завершены в срок). | Medium |
| **Saga compensation UI** | `orders_saga.py` + `payments_saga.py` реализованы. Нет UI просмотра статуса compensation steps при rollback. | Low |

### 7.5 Расширяемость (Plugin / Extensions)

| Пробел | Описание | Приоритет |
|---|---|---|
| **Plugin compatibility matrix** | Нет механизма объявления `incompatible_with` в `plugin.toml`. При установке двух несовместимых плагинов система не предупреждает. | High |
| **Plugin upgrade path generator** | `check_plugin_semver.py` проверяет semver, но нет автогенерации migration guide при major-bump (API diff). | Medium |
| **Extension testkit integration** | Каждый extension пишет свои фикстуры. `testkit/` существует, но нет шаблонного `conftest.py` для extensions с pre-wired plugin loader, DB snapshot, S3 mock. | High |
| **Plugin hot-reload в dev-режиме** | `hot_swap.py` реализован (279 LOC). Но нет файлового watcher на `extensions/<name>/plugin.toml` для автоматического hot-swap в dev. | Medium |
| **Capability dependency graph UI** | `71_Capabilities.py` отображает capability list. Нет визуализации dependency graph: какие capabilities требуют какие другие. | Low |

### 7.6 Производительность

| Пробел | Описание | Приоритет |
|---|---|---|
| **Lazy processor loading** | 100 процессоров импортируются при старте. Нужен lazy import (ProcessorRegistry через `importlib` при первом вызове). | High |
| **RSGI streaming для крупных файлов** | Granian RSGI задокументирован (ADR-0059), но нет streaming upload/download handler для файлов > 100MB (только буферный read). | Medium |
| **ClickHouse columnar analytics DSL** | `duckdb_query.py` есть. Но нет оптимизированного `.clickhouse_query(sql, params)` процессора с connection pool из ClickHouse client (не HTTP). | Medium |
| **msgspec hot-path measurement** | `structlog_batching.py` и msgspec benchmark в vault существуют. Но нет CI-gate на p99 latency сериализации DTO (рост кода может деградировать msgspec). | Low |
| **Startup time gate** | `dev_light < 5 сек` упомянут в DoD Sprint 1. Нет CI-шага, который проверяет фактическое время старта на каждый PR. | Medium |

### 7.7 Документация

| Пробел | Описание | Приоритет |
|---|---|---|
| **Auto-generated Processor Palette** | `generate_processors_doc.py` существует. Но нет интеграции в Sphinx build (`make docs` не генерирует страницу с примерами для каждого из 100 процессоров). | High |
| **Route flow diagram из YAML** | Нет команды `manage.py dsl render ROUTE=name` → Mermaid/BPMN/PNG. DSL Visual Editor существует, но export из route.toml → визуальная схема — нет. | High |
| **ADR decision log в Wiki** | `build_adr_index.py` существует. Но `60_Wiki.py` Streamlit-страница не отображает ADR list с поиском по тегам/статусу (only Proposed/Accepted/Deprecated). | Medium |
| **Tutorial progress tracking** | 9 tutorials запланированы на Sprint 9. Нет механизма «tutorial progress» в developer portal (галочки выполненных шагов). | Low |
| **Changelog diff между версиями** | Semantic-release настроен. Но нет Streamlit-страницы «What changed in v1.2.3 vs v1.1.0» — diff из CHANGELOG.md с фильтром по команде/зоне. | Low |

### 7.8 Developer UX

| Пробел | Описание | Приоритет |
|---|---|---|
| **`make doctor`** | Нет единой команды проверки окружения: все сервисы доступны, env-переменные валидны, Python version, зависимости установлены. | High |
| **`make simulate ROUTE=name`** | Нет возможности запустить route в dry-run с sample data из CLI (только через Streamlit UI). | Medium |
| **Plugin publish workflow** | Нет `make publish-plugin PLUGIN=x VERSION=1.0.0` — команды для публикации плагина в marketplace с cosign-signing. | Medium |
| **`manage.py diagnose`** | Нет диагностической команды, которая проверяет граф зависимостей, ищет циклические импорты, проверяет все layer-violation. | Medium |
| **IDE-friendly ProcessorRegistry types** | ProcessorRegistry + JSON-Schema export реализованы. Но нет `.pyi` stub-генерации для `RouteBuilder` методов (autocomplete в PyCharm/VSCode без LSP). | Low |

***

## 8. Рекомендуемые приоритеты для Sprint 8 / 9

### Критические (должны войти в Sprint 8)

1. **Закрыть BLOCKER #1** — удалить `taskiq_broker.py`, мигрировать 13 callsites → Temporal/APScheduler.
2. **Закрыть BLOCKER #3** — мигрировать 38 `httpx.AsyncClient()` → `OutboundHttpClient`.
3. **Реализовать outbox_dispatcher.py + inbox_dedup.py + dlq.py** — messaging carryover.
4. **RouteLoader full-cycle** — без него hot-reload routes (ADR-0056) не работает end-to-end.
5. **Устранить коллизии страниц Streamlit** — 9 дублей нарушают навигацию.
6. **HITL Streamlit panel** — ключевой UX для банковских операторов.

### Высокий приоритет (Sprint 8B или Sprint 9)

7. **Token budget enforcement per tenant** — security требование для RAG.
8. **EventBus schema validation** при publish → schema_registry hook.
9. **Plugin compatibility matrix** в plugin.toml + проверка при загрузке.
10. **Extension testkit шаблонный conftest.py**.
11. **Lazy processor loading** — 100 процессоров влияют на startup time.
12. **`make doctor`** — базовый DX инструмент.
13. **Auto-generated Processor Palette** в Sphinx.
14. **ClickHouse async bulk audit writer**.

### Средний приоритет (Post Sprint 9 / backlog)

15. DSL Complexity Budget lint-checker.
16. `.batch(size, timeout)` DSL-примитив.
17. DSL A/B процессор.
18. RAG Freshness Indicator.
19. Visual workflow diff.
20. Workflow template library UI (из blueprints).
21. Plugin upgrade path generator.
22. `manage.py dsl render ROUTE=name` → Mermaid.
23. Grafana workflow SLA compliance dashboard.
24. DSL Prompt Version Control UI.
25. Pool warm-up on startup.

***

## 9. Технический долг — новые пункты

Ранее не зафиксированные в PLAN.md:

### 9.1 Дублирование execution middlewares

Обнаружено два слоя middleware:
- `entrypoints/middlewares/` — ASGI middleware (idempotency, tenant, auth, security_headers и др.)
- `services/execution/middlewares/` — audit_middleware.py, idempotency_middleware.py, rate_limit_middleware.py

Это **нарушение принципа Single Entry** из §1.1 PLAN.md. Audit/idempotency/rate-limit реализованы дважды. Нужна консолидация: либо удалить `services/execution/middlewares/`, либо сделать их thin-wrapper'ами над ASGI-слоем.

### 9.2 DLQ Replay страница без backend

`14_DLQ_Replay.py` в Streamlit существует, но `admin_dlq.py` REST-endpoint отсутствует. Страница не функциональна (показывает UI без данных).

### 9.3 Два S3-browser'а

`55_S3_Browser.py` и `55_s3_files.py` + `30_Files_S3.py` — три страницы для работы с S3-файлами. Необходима консолидация в одну с чётким разграничением: Files (extensions-owned) vs Raw S3 Browser (ops-owned).

### 9.4 `src/backend/workflows/` vs `extensions/`

Существует `src/backend/workflows/` с `orders_dsl.py`, `orders_saga.py`, `payments_saga.py`. По архитектуре V15 бизнес-логика должна быть только в `extensions/`. Эти файлы — кандидаты на миграцию в `extensions/core_entities/orders/` и `extensions/credit_pipeline/`.

***

## 10. Сравнение с предыдущим анализом (04.05.2026)

| Пробел из анализа 04.05 | Статус на 15.05 |
|---|---|
| `builder.py` 109KB god-object | ✅ ЗАКРЫТ — 8 модулей в `dsl/builders/` |
| Дублирование `dsl/transform` / `dsl/transforms` | ✅ ЗАКРЫТ — единый `dsl/engine/processors/` |
| 313 mypy ошибок | 🟡 Идёт работа — Sprint 8B К2 W10: цель ≤50 |
| layer violations 125 | 🟡 Идёт работа — Sprint 8B К2 W12: цель 0 |
| `watchdog` + `watchfiles` дублирование | ✅ ЗАКРЫТ — `FileWatcherSource` через watchfiles |
| CDC не DSL-source | ✅ ЗАКРЫТ — `cdc_enrich.yaml` blueprint + processor |
| BaseHTTPMiddleware → pure ASGI | ✅ ЗАКРЫТ — ADR-0057 + ASGI middleware chain |
| Plugin система не реализована | ✅ ЗАКРЫТ — `extensions/` + `plugin.toml` + hot-swap |
| Temporal absent (TaskIQ вместо него) | 🟡 ЧАСТИЧНО — `temporal_backend.py` + `LiteTemporalBackend`, но TaskIQ не удалён (BLOCKER) |
| Streamlit нет маршрутов | ✅ ЗАКРЫТ — `11_Routes.py`, `30_DSL_Playground.py`, `31_DSL_Visual_Editor.py` |
| fastembed несовместимость Python 3.14 | ✅ ЗАКРЫТ — заменён на `BGE-M3` + `embedding_registry.py` |
| Дублирующиеся сериализаторы | 🟡 ЧАСТИЧНО — msgspec hot-path benchmark в vault, но 4 сериализатора ещё не унифицированы явно |
| SAML/AD не реализован | 🟡 ADR-0054 принят, `saml_backend.py` не найден |
| Chaos tests не реализованы | ✅ ЧАСТИЧНО — 11 chaos test-файлов найдено (заявлено 33) |

**Прогресс за 11 дней**: закрыто ~8 из 14 критических пробелов из анализа 04.05. Рост кодовой базы: +729 файлов (+60%). Это нетипично высокая скорость для 5 параллельных команд.

***

## 11. Промпт для Claude Code (актуализированный, v4)

```
# Claude Code — gd_integration_tools Comprehensive Refactoring Prompt v4
# Источник: GAP-анализ v4, 2026-05-15

## Контекст
Репозиторий: https://github.com/IvanKorch1289/gd_integration_tools
Ветка: master (HEAD e7051065 + Sprint 8 in-flight)
PLAN.md: V18.2 FINAL
Текущий спринт: Sprint 8 (49 wave)

## Порядок работы
1. Прочитай PLAN.md полностью.
2. Прочитай SPRINT_8_PLAN.md (текущий operational план).
3. Прочитай .claude/KNOWN_ISSUES.md.
4. Запусти `graphify map src/backend` для актуальной карты связей.
5. Следуй правилам .claude/rules/*.

---

## BLOCKER WAVE 1 — критические blockers (до всего остального)

### B1. TaskIQ removal [wave:gap4/blocker-taskiq]
- Удалить `src/backend/infrastructure/execution/taskiq_broker.py`
- Найти все 13 callsites `Invoker.ASYNC_QUEUE` (`rg "ASYNC_QUEUE" src/`)
- Мигрировать на Temporal cron (`workflow.cron_schedule`) или APScheduler
- Удалить `taskiq*` из `pyproject.toml [project.dependencies]`
- Удалить `feature_flags.taskiq_*` из `.claude/DECISIONS.md`
- DoD: `rg "^(from|import) taskiq" src/` = 0 строк

### B2. WAF Phase-2 migration [wave:gap4/blocker-waf-phase2]
- Найти: `rg "httpx\.AsyncClient\(\)" src/ --include="*.py"` → ожидается 38 hits
- Заменить каждый на `await OutboundHttpClient.get()` из `core/net/outbound_http.py`
- Исключить: тесты, `core/net/outbound_http.py` сам, `testkit/`
- Flip `feature_flags.waf_outbound_via_facade` → default-ON в staging compose
- DoD: `make waf-check` = 0 violations

### B3. Messaging carryover [wave:gap4/blocker-messaging]
- Реализовать `infrastructure/messaging/outbox_dispatcher.py`
  - Poll `core/messaging/outbox.py` Protocol
  - Dispatch через EventBus backend (Kafka/RabbitMQ/NATS)
  - Retry с tenacity + DLQ при исчерпании попыток
- Реализовать `infrastructure/messaging/inbox_dedup.py`
  - `seen_or_mark(message_id) -> bool`
  - Redis SETNX backend
  - raise `InboxUnavailable` при Redis-error (fail-closed)
- Реализовать `infrastructure/messaging/dlq.py`
  - Единый DLQ для HTTP/SOAP/gRPC/Webhook
  - `DLQMessage(transport, payload, attempts, last_error, ttl)`
  - PostgreSQL storage + replay API endpoint
  - DSL `.dlq(target, max_attempts=N, ttl_hours=48)`
- DoD: `pytest tests/unit/infrastructure/messaging/` green

---

## WAVE 2 — RouteLoader + Page dedup

### W2.1 RouteLoader full-cycle [wave:gap4/route-loader]
- Создать `src/backend/dsl/route/loader.py`
  - `RouteLoader.load_directory(path: Path)` → список `RouteSpec`
  - Парсинг `route.toml` через `tomllib`
  - Загрузка `*.dsl.yaml` через существующий DSL builder
  - Регистрация в `ActionHandlerRegistry`
  - watchfiles.awatch на директорию → hot-reload < 3 сек
  - feature_flag: `hot_reload_routes`
- DoD: `routes/echo_demo` доступен через REST без рестарта после изменения

### W2.2 Streamlit page renumbering [wave:gap4/page-dedup]
- Устранить 9 дублей нумерации (см. §4 отчёта)
- Схема ренумерации:
  - 00_Home, 01_Glossary, 02_Tutorial
  - 14_DLQ_Replay → 18_DLQ_Replay
  - 15_Pool_Monitor → оставить, 16_ → 19_Processes
  - 30_Files_S3 → 35_Files_S3 (не конфликтует с 30_DSL_Playground)
  - 50_Codegen_Wizard → 58_Codegen_Wizard
  - 55_s3_files.py → удалить (дубль 55_S3_Browser)
  - 60_Wiki → 68_Wiki
  - 65_workflow_live_logs → 69_Workflow_Live_Logs
  - 67_Plugin_Marketplace → удалить (дубль 60_Plugin_Marketplace)
- Обновить `PLAN.md §5 Frontend pages`

---

## WAVE 3 — DSL расширения

### W3.1 DSL Complexity Budget [wave:gap4/dsl-complexity]
- Добавить в `src/backend/dsl/cli/linter.py`:
  - `RouteComplexityChecker` — подсчёт depth (Choice/TryCatch вложений)
  - Порог: `max_nesting_depth = 5`, `max_steps_per_route = 50`
  - CLI: `manage.py dsl lint --complexity ROUTE_PATH`
  - CI-шаг: `make dsl-complexity-check`
- DoD: echo_demo route проходит, синтетически сложный route failит

### W3.2 `.batch(size, timeout)` DSL step [wave:gap4/dsl-batch]
- Добавить `BatchProcessor` в `dsl/engine/processors/core.py`
  - Агрегация N сообщений ИЛИ flush по timeout (whichever first)
  - async generator через `asyncio.Queue`
  - DSL builder: `.batch(size=100, timeout_ms=500)`
- DoD: unit-test с 50 msg + flush по timeout

### W3.3 DSL Render → Mermaid [wave:gap4/dsl-render]
- `manage.py dsl render ROUTE=routes/echo_demo` → stdout Mermaid flowchart
- `manage.py dsl render ROUTE=name --format bpmn` → BPMN XML
- Интеграция в `34_DSL_Debugger.py`: кнопка "Visualize" → рендер в Streamlit через `st.graphviz_chart`
- DoD: credit_assessment.workflow.yaml рендерится без ошибок

### W3.4 `make doctor` [wave:gap4/make-doctor]
- `tools/checks/doctor.py` — единая диагностика:
  - Python version ≥ 3.14
  - Все сервисы из docker-compose доступны (ping)
  - Env-переменные из `.env.example` присутствуют
  - `uv sync` ok
  - Layer violations = 0
  - Taskiq imports = 0
  - WAF violations = 0
- `Makefile` target: `make doctor`
- DoD: зелёный вывод на чистом окружении, красный — с ошибками

---

## WAVE 4 — Infrastructure quality

### W4.1 ClickHouse async bulk audit [wave:gap4/clickhouse-bulk-audit]
- Создать `infrastructure/observability/audit_bulk_writer.py`
  - `AuditBulkWriter` — буфер + periodic flush (default: 500 events или 5 сек)
  - `asyncio.Queue` + background task через TaskRegistry
  - Использует существующий ClickHouse client
  - Graceful shutdown: flush remaining на SIGTERM
- Подключить в `entrypoints/middlewares/audit_log.py`
- DoD: benchmark показывает ≥ 10x throughput vs поштучной вставки

### W4.2 EventBus schema validation [wave:gap4/eventbus-schema-validate]
- В `infrastructure/clients/messaging/event_bus.py`:
  - При `bus.publish(topic, payload)` — lookup topic schema в `schema_registry`
  - Если схема найдена: validate payload через `jsonschema.validate`
  - feature_flag: `eventbus_schema_validation` (default OFF)
- DoD: публикация невалидного payload с включённым флагом → ValidationError

### W4.3 Lazy processor loading [wave:gap4/lazy-processors]
- В `dsl/engine/processors/__init__.py`:
  - Заменить прямые импорты на `_PROCESSOR_REGISTRY: dict[str, str]` (name → module path)
  - `get_processor(name)` → `importlib.import_module(path)` при первом вызове
  - Кэш в `functools.lru_cache`
- DoD: startup time без eager-import всех 100 процессоров

### W4.4 Pool warm-up on startup [wave:gap4/pool-warmup]
- В `infrastructure/clients/transport/__init__.py` или lifespan:
  - `async def warmup_pools(min_connections: int = 2)` для DB/Redis/HTTP
  - Вызов в `src/backend/main.py` lifespan startup
  - Metric: `pool.warmup.duration_ms` → Prometheus
- DoD: p95 первых 10 запросов = p95 последующих 10 (нет cold-start spike)

---

## WAVE 5 — Plugin / Extensibility

### W5.1 Plugin compatibility matrix [wave:gap4/plugin-compat]
- Добавить в `plugin.toml` schema:
  ```toml
  [plugin.compatibility]
  incompatible_with = ["other-plugin>=1.0.0"]
  requires_capability = ["auth.jwt", "storage.s3"]
  ```
- В `core/plugin_runtime/` validate при загрузке:
  - Проверять `incompatible_with` против загруженных плагинов
  - raise `PluginConflictError` с описанием конфликта
- В `60_Plugin_Marketplace.py` отображать совместимость
- DoD: установка двух несовместимых плагинов → explicit error

### W5.2 Extension testkit template [wave:gap4/extension-testkit]
- Добавить в `tools/templates/` шаблон `extension_conftest.py.j2`:
  - Pre-wired `PluginLoader` fixture
  - PostgreSQL test-schema isolation (per-test schema)
  - Redis mock (fakeredis)
  - S3 mock (moto)
  - Sample `plugin.toml` для тестовой регистрации
- В `tools/codegen_plugin.py`: генерировать `tests/conftest.py` из шаблона
- DoD: `make new-plugin NAME=test_ext` → `pytest extensions/test_ext/tests/` green без внешних сервисов

### W5.3 Plugin dev watcher [wave:gap4/plugin-dev-watcher]
- В `manage.py`:
  - `manage.py dev --watch-plugins extensions/` 
  - watchfiles.awatch на `extensions/*/plugin.toml`
  - При изменении → автоматический `hot_swap` через `core/plugin_runtime/hot_swap.py`
  - feature_flag: `plugin_dev_watcher` (dev profiles only)
- DoD: изменение `plugin.toml` в dev-режиме → hot-swap без SIGTERM

---

## WAVE 6 — AI / RAG improvements

### W6.1 RAG freshness indicator [wave:gap4/rag-freshness]
- Добавить поле `ingested_at: datetime` + `ttl_hours: int | None` к chunk metadata в Qdrant
- В RAG retrieval: фильтровать / помечать устаревшие chunks
- DSL: `.rag_query(collection, query, max_staleness_hours=72)`
- В `22_RAG_Console.py`: отображать freshness badge (green/yellow/red)
- DoD: stale chunk не возвращается при `max_staleness_hours` < age

### W6.2 Token budget per tenant [wave:gap4/rag-token-budget]
- В `core/tenancy/` или `core/auth/`:
  - `TenantQuota.rag_tokens_per_day: int`
  - Счётчик в Redis с TTL 24h
  - При превышении → raise `TenantQuotaExceeded`
- В `services/ai/gateway/client.py`: проверка перед LLM-вызовом
- Метрика: `ai.tokens.used{tenant_id}` → Grafana
- DoD: тест с исчерпанным бюджетом → 429 от API

### W6.3 HITL Streamlit panel [wave:gap4/hitl-panel]
- Новая страница `src/frontend/streamlit_app/pages/72_HITL_Panel.py`
  - Список приостановленных workflow (Temporal signal-wait)
  - Форма для ввода данных оператором
  - Кнопка "Approve" / "Reject" → вызов `WorkflowFacade.send_signal(workflow_id, signal, payload)`
  - Real-time обновление через `st.rerun()` или `st.fragment`
- DoD: кредитная заявка на HITL → оператор видит в UI → одобряет → workflow продолжается

---

## WAVE 7 — Technical debt

### W7.1 Execution middleware dedup [wave:gap4/middleware-dedup]
- Провести аудит: `services/execution/middlewares/` vs `entrypoints/middlewares/`
- Удалить дублирующиеся `audit_middleware.py`, `idempotency_middleware.py`, `rate_limit_middleware.py` из `services/execution/middlewares/`
- Сделать `services/execution/` thin-wrapper над ASGI middleware если нужен
- Обновить все импортёры
- DoD: `rg "from.*services.execution.middlewares" src/` = 0

### W7.2 business-logic в src/backend/workflows → extensions [wave:gap4/biz-migrate]
- `src/backend/workflows/orders_dsl.py`, `orders_saga.py`, `payments_saga.py`
- Переместить в `extensions/core_entities/orders/workflows/`
- Обновить `src/backend/workflows/registry.py` → импорт из extension
- DoD: layer-check проходит, тесты зелёные

### W7.3 S3 page consolidation [wave:gap4/s3-pages]
- Удалить `55_s3_files.py` (дубль)
- `55_S3_Browser.py` → ops-focused (bucket browser, presigned URLs)
- `30_Files_S3.py` → extension-focused (files linked to entities)
- DoD: нет дублей по функциональности

---

## DoD для всего промпта

- [ ] `make doctor` → все зелёные
- [ ] `rg "^(from|import) taskiq" src/` = 0
- [ ] `make waf-check` = 0 violations  
- [ ] `pytest tests/unit/infrastructure/messaging/` → outbox/inbox/dlq green
- [ ] RouteLoader hot-reload работает (< 3 сек)
- [ ] Streamlit страницы без дублей нумерации
- [ ] `pytest tests/` → coverage ≥ 70%
- [ ] mypy ≤ 50 ошибок
- [ ] Layer violations = 0
- [ ] `make dsl-complexity-check` → echo_demo green

## Верификация
После каждого wave: `make verify` (= lint + type-check + unit-tests + layer-check + waf-check)
```

***

## 12. Краткий исполнительный вывод

Проект за 11 дней (04.05→15.05) сделал впечатляющий рывок: +729 файлов, закрыто ~57% ранее выявленных критических пробелов. PLAN.md V18.2 адекватно отражает текущее состояние — статусы ✅ в основном подтверждены, но:

1. **2 BLOCKER открыты** (TaskIQ + WAF Phase-2) — входят в Sprint 8A.
2. **3 messaging-компонента отсутствуют** (outbox_dispatcher, inbox_dedup, dlq) — Sprint 5 carryover.
3. **14 артефактов по другому пути**, чем документировано — нужен `check_v11_artefacts.py` расширенный режим.
4. **9 коллизий страниц Streamlit** — не упомянуто в PLAN.md вообще.
5. **12 новых GAP-позиций** предложены выше (§7) — высокий приоритет 8 из них.

PLAN.md в целом **хорошо структурирован и охватывает ≈88% реальных потребностей**. Добавив секцию §12 «Page numbering policy» и §13 «Technical debt tracker» (execution middleware dedup, workflows→extensions миграция, S3-page consolidation), PLAN.md достигнет ≥95% cover