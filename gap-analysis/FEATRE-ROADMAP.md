# FEATURE ROADMAP — gd_integration_tools
## План развития интеграционной платформы AI/DSL/RPA

> **Версия**: 1.0 (составлен 2026-05-15 на основе GAP-анализа v3 + аудита репозитория)  
> **Горизонт**: Sprint 9 → Sprint 16 (≈ 4–6 месяцев после завершения Sprint 8)  
> **Принцип**: каждая фича проходит путь ADR → wave-коммит → DoD-чеклист  
> **Категоризация**: 🔴 критично / 🟡 важно / 🟢 улучшение / 💡 инновация

***

## 0. Контекст: что уже есть (Sprint 8 baseline)

На момент составления плана в репозитории реализованы:
- DSL: 94 процессора, 10 builder-модулей, 5 YAML-blueprint, LSP-сервер, lint-CLI
- Инфраструктура: 16+ sinks, 18+ sources, 7 Grafana-дашбордов, OTel, ClickHouse, structlog batching
- AI/RAG: PydanticAI, LiteLLM, DSPy, LangMem, BGE-M3, LangFuse 3.x, Inspect AI, E2B sandbox, 6 eval-suite
- Workflow: Temporal, LiteTemporalBackend, WorkflowBuilder, SagaBuilder, BPMN-импорт, YAML round-trip
- Extensibility: plugin system V11.1, hot-swap, extensions/ layout, ProcessorRegistry, JSON-Schema export
- Frontend: 53 Streamlit-страницы, DSL Visual Editor, DSL Playground, Wiki
- Security: WAF, mTLS, SAML/AD, supply-chain SBOM+cosign, OWASP ZAP, Vault rotation
- Resilience: CircuitBreaker, RetryBudget, Bulkhead, DegradationManager, SelfHealer, 18 chaos-тестов

**Открытые блокеры Sprint 8**:
- BLOCKER #1: TaskIQ removal (13 callsites)
- BLOCKER #3: WAF Phase-2 outbound (38 callsites `httpx.AsyncClient()`)
- 5 unit-тестов quotas fail (AUDIT-1)
- Дублирующиеся номера Streamlit-страниц (9 конфликтов)
- `outbox_dispatcher.py`, `inbox_dedup.py`, `dlq.py` — неполная реализация
- `35_Audit_Log.py` → `40_Audit_Log.py` (path-drift документации)

***

## 1. DSL — Язык интеграционных маршрутов

### 1.1 🔴 Исправление текущих проблем

| # | Проблема | Решение |
|---|---|---|
| DSL-1 | `dsl/routes.py` — монолит, RouteLoader V11 не имеет отдельного модуля `dsl/route/loader.py` | Выделить `RouteLoader` в `dsl/route/loader.py` с full-cycle hot-reload |
| DSL-2 | Дублирование номеров Streamlit-страниц (9 конфликтов: 00/14/15/30/50/55/60/65/67) | Ренумерация страниц по схеме: DSL 30-39, AI 40-49, Ops 50-59, Admin 60-69, Extensions 70-79 |
| DSL-3 | PII DSL-шаг отсутствует как отдельный процессор (`processors/pii.py` нет) | Выделить `.mask_pii()` / `.unmask_pii()` из `ai.py` в отдельный `processors/pii.py` |
| DSL-4 | Blueprint-библиотека содержит только 5 паттернов | Расширить до 20+ blueprint (см. §1.2) |

### 1.2 🟡 Расширение библиотеки Blueprint-паттернов

Добавить YAML-паттерны в `dsl/blueprints/`:
```
fan_out_fan_in.yaml        — распределение задач с join-барьером
request_reply_async.yaml   — async request-reply через EventBus
file_to_db_pipeline.yaml   — file-watcher → parse → validate → upsert → notify
cdc_to_search_index.yaml   — CDC Postgres → transform → Elasticsearch/Qdrant
rpa_web_scrape.yaml        — web-scrape → OCR → AI extract → store
hitl_approval.yaml         — HITL: workflow pause → form → approve/reject → resume
credit_scoring.yaml        — DSPy scoring → rule-engine → decision → notify
multimodal_ingest.yaml     — file → image/PDF parse → embed → RAG upsert
scheduled_report.yaml      — cron → query → render Excel → send email
webhook_to_kafka.yaml      — webhook source → validate → enrich → Kafka sink
saml_user_sync.yaml        — SAML assertion → user upsert → permission grant
api_to_api_bridge.yaml     — REST → transform → SOAP → map response → REST reply
```

### 1.3 🟡 DSL Complexity Budget (Cyclomatic DSL Score)

**Идея**: каждый маршрут имеет цикломатическую сложность, превышение — lint-ошибка.
```python
# tools/dsl_lint.py — добавить проверку
@dsl_check("route-complexity")
def check_complexity(route: RouteSpec) -> LintResult:
    score = len(route.steps) + 2 * len([s for s in route.steps if s.type == "choice"])
    if score > MAX_ROUTE_COMPLEXITY:
        return LintResult.error(f"Route complexity {score} > {MAX_ROUTE_COMPLEXITY}")
```
**DoD**: `make dsl-lint` отклоняет маршруты с complexity > 50; Streamlit показывает score.

### 1.4 🟡 DSL A/B Processor — эксперименты в маршрутах

```yaml
# route.dsl.yaml
- step: ab_test
  experiment_id: "scoring_model_v2"
  split: {control: 0.7, treatment: 0.3}
  control_steps:
    - step: invoke
      action: "scoring.v1"
  treatment_steps:
    - step: invoke
      action: "scoring.v2"
  track_metric: "response_time_ms"
```
**Применение**: сравнение версий скоринговых моделей, DSP-prompt, RPA-сценариев без раскатки.

### 1.5 🟡 DSL Dry-run UI в Streamlit

`dsl/workflow/dryrun.py` уже есть, но UI отсутствует.  
**Предложение**: в `30_DSL_Playground.py` добавить вкладку "Dry-run":
- Загрузить YAML маршрута
- Указать sample payload (JSON editor)
- Запустить dry-run без side-effects
- Показать waterfall каждого шага с latency, input/output

### 1.6 🟢 DSL Diff / Changelog в Streamlit

`tools/dsl_diff.py` существует, но не интегрирован в UI.  
**Предложение**: страница `31_DSL_Visual_Editor.py` → вкладка "History & Diff":
- Timeline версий маршрута из Git
- Side-by-side diff двух версий
- Красная/зелёная подсветка изменённых шагов

### 1.7 🟢 Semantic Processor Search в DSL Builder

Проблема: 94 процессора — разработчику сложно найти нужный.  
**Решение**: интегрировать vector-поиск по `ProcessorRegistry.describe()`:
```python
# DSL Builder UI: поле "What do you need?"
# Input: "send file to S3 and notify Telegram"
# Output: [storage_ext, sink_publish(s3_sink), telegram/send_file]
```

### 1.8 💡 DSL Макросы с параметрами (Jinja2-over-YAML)

```yaml
# blueprints/macros.py — расширить существующий macros.py
{% macro retry_call(action, retries=3, backoff="exponential") %}
- step: call
  action: {{ action }}
  retry:
    max_attempts: {{ retries }}
    backoff: {{ backoff }}
{% endmacro %}
```
**Применение**: DRY-принцип в YAML-маршрутах, повторное использование сниппетов.

### 1.9 💡 DSL Step Tracing — "почему шаг упал"

Сейчас при ошибке в Exchange нет контекста "на каком шаге, с каким payload".  
**Решение**: добавить `StepTrace` в Exchange:
```python
@dataclass
class StepTrace:
    step_name: str
    input_snapshot: dict  # обрезанный до 1KB
    duration_ms: float
    error: str | None
```
Streamlit: `34_DSL_Debugger.py` уже есть — расширить трассировкой шагов.

***

## 2. Инфраструктура

### 2.1 🔴 Закрытие открытых долгов (carryover Sprint 5-8)

| # | Компонент | Что сделать |
|---|---|---|
| INF-1 | `outbox_dispatcher.py` отсутствует | Реализовать `infrastructure/messaging/outbox_dispatcher.py` поверх `core/messaging/outbox.py` |
| INF-2 | `inbox_dedup.py` отсутствует | `InboxDedup.seen_or_mark()` raise `InboxUnavailable` при Redis-error (fail-closed) |
| INF-3 | `dlq.py` отсутствует | DLQ unified: PostgreSQL-таблица + replay API + TTL-политики |
| INF-4 | TaskIQ broker (`taskiq_broker.py`) всё ещё присутствует | Удалить, мигрировать 13 callsites на Temporal cron + APScheduler |
| INF-5 | WAF Phase-2: 38 `httpx.AsyncClient()` callsites | Мигрировать на `OutboundHttpClient` facade, flip `waf_outbound_via_facade` ON |

### 2.2 🟡 DLQ TTL Policies — управление сроком жизни сообщений

Текущий DLQ: только replay. Нужно добавить:
```python
class DLQPolicy:
    retention_days: int = 7          # по умолчанию
    max_replay_attempts: int = 3
    escalation_after: timedelta      # эскалация в алерт
    on_expire: Literal["drop", "archive_s3", "dead_archive_clickhouse"]
    pii_scrub_before_archive: bool = True
```
**DSL**: `.dlq(policy=DLQPolicy(retention_days=30, on_expire="archive_s3"))`

### 2.3 🟡 ClickHouse Async Bulk Writer для Audit

Текущий аудит: индивидуальные INSERT → bottleneck при high-load.  
**Решение**: `infrastructure/clients/clickhouse_bulk_writer.py`:
```python
class ClickHouseBulkWriter:
    buffer_size: int = 1000
    flush_interval: float = 1.0  # сек
    
    async def append(self, event: AuditEvent) -> None: ...
    async def _flush_loop(self) -> None: ...  # background task
```
**Метрика**: flush latency, buffer utilization в Grafana.

### 2.4 🟡 Connection Pool Warm-up on Startup

Сейчас пулы создаются lazy. При первом запросе — задержка.  
**Решение**: `lifespan` подключает `PoolWarmup`:
```python
@asynccontextmanager
async def lifespan(app):
    await PoolWarmup.warm_all(min_connections=3)  # PG + Redis + ClickHouse
    yield
    await PoolWarmup.drain_all()
```
**Измерение**: p95 первого запроса после рестарта должен быть < 50ms.

### 2.5 🟡 HTTP/3 + WebTransport (Sprint 8B)

ADR-0059 Granian RSGI уже принят. Следующий шаг — HTTP/3:
```python
# infrastructure/clients/transport/http3_client.py
class HTTP3Client:
    """aioquic-based client для серверов с HTTP/3"""
    async def request(self, method, url, **kwargs) -> Response: ...
```
**DSL**: `.call_http3(url, method)` — opt-in шаг для партнёров с QUIC.

### 2.6 🟢 SAML Backend — фактическая реализация

ADR-0054 принят, но `saml_backend.py` отсутствует.  
**Что нужно**: `infrastructure/security/saml_backend.py` (pysaml2):
- SP-initiated SSO flow
- Атрибуты → TenantContext mapping
- Assertion cache (Redis)
- SAML metadata auto-refresh

### 2.7 🟢 Graceful Degradation Registry — уровни деградации

Текущий `DegradationManager` блокирует только запись в основную БД.  
**Расширение**: уровни деградации:
```python
class DegradationLevel(IntEnum):
    FULL = 0           # всё работает
    READ_ONLY = 1      # только чтение из БД
    CACHE_ONLY = 2     # только из кэша
    ESSENTIAL_ONLY = 3 # только критические эндпоинты
    MAINTENANCE = 4    # 503 для всех кроме /health
```
Переключение через feature flag + Streamlit-кнопка в Admin.

### 2.8 🟢 WebDAV Source (входящий)

`webdav_io.py` процессор есть, но Source нет.  
**Добавить**: `infrastructure/sources/webdav.py` + DSL `.from_webdav(url, poll_interval)`.

### 2.9 💡 Distributed Rate Limiter с Redis Cluster

Текущий rate limiter: in-memory или single-Redis.  
**Проблема**: при горизонтальном масштабировании > 1 pod — лимит не соблюдается.  
**Решение**: `redis-cell` (INCR + TTL atomic) или `redis.lua` скрипт:
```python
class RedisClusterRateLimiter(RateLimiterBackend):
    """Token bucket через redis-cell CL.THROTTLE"""
    async def acquire(self, key: str, limit: int, window: int) -> bool: ...
```

### 2.10 💡 Adaptive Timeout — авто-тюнинг таймаутов

Идея из Netflix Hystrix: таймаут = p99 за последние N запросов × safety_factor.  
```python
class AdaptiveTimeoutPolicy:
    percentile: float = 0.99
    safety_factor: float = 1.5
    min_timeout: float = 0.1
    max_timeout: float = 30.0
    window_size: int = 100  # последних запросов
```
**DSL**: `.policy.adaptive_timeout(percentile=0.99, safety_factor=1.5)`

***

## 3. AI / RAG

### 3.1 🔴 Multimodal RAG — полная реализация

Scaffold `MultimodalRAG` есть (`document_parsers/_orchestrator.py`), но:
- PDF/image ingestion pipeline не завершён
- Video transcript ingestion отсутствует
- Cross-modal retrieval (запрос текстом → ответ с изображением) не реализован

**Roadmap**:
```
PDF → markitdown → chunks → text embed → Qdrant
Image → CLIP/BLIP2 → image embed → Qdrant multimodal collection
Video → Whisper transcript → chunks → text embed → Qdrant + keyframes
Query → text embed → fuse scores(text_sim, image_sim) → rerank
```

### 3.2 🟡 Prompt Version Control UI

LangFuse хранит версии промптов, но нет UI.  
**Предложение**: страница `48_Prompt_Lab.py`:
- Список промптов с версиями
- A/B тестирование промптов (LangFuse experiments)
- Метрики: cost, latency, quality score per version
- Rollback кнопка

### 3.3 🟡 RAG Freshness Indicator

**Проблема**: chunk загружен 6 месяцев назад — может быть устаревшим.  
**Решение**: добавить в Qdrant payload:
```python
class RAGChunkMetadata:
    ingested_at: datetime
    source_modified_at: datetime | None
    ttl_days: int | None           # null = без срока
    freshness_score: float         # 1.0 = свежий, 0.0 = устарел
```
**DSL**: `.rag_query(freshness_min=0.7)` — отсекает устаревшие чанки.  
**Streamlit**: `75_RAG_Ingest_Wizard.py` + freshness тепловая карта коллекций.

### 3.4 🟡 Token Budget per Tenant

**Проблема**: один tenant может исчерпать весь бюджет LLM.  
**Решение**: `services/ai/gateway/token_budget.py`:
```python
class TenantTokenBudget:
    daily_limit: int           # токенов в сутки
    hourly_burst_limit: int    # burst limit
    current_usage: int         # из Redis counter
    
    async def check_and_reserve(self, estimated_tokens: int) -> bool: ...
    async def refund(self, unused_tokens: int) -> None: ...
```
**Интеграция**: LiteLLM gateway → `TokenBudgetMiddleware` → отклонение с 429.

### 3.5 🟡 AI Workflow Checkpoint Restore UI

LangGraph postgres saver уже есть (`services/ai/agents/langgraph_postgres_saver.py`).  
**Чего не хватает**: UI для работы с checkpoint'ами:
- Страница `60_AI_Agent_Monitor.py` (Sprint 9) → вкладка "Checkpoints"
- Список активных агент-сессий
- Inspect state на каждом шаге
- Restore от произвольного checkpoint (time-travel debugging)

### 3.6 🟡 AI Feedback Loop → DSPy Fine-tuning

`services/ai/feedback/` уже есть. Замкнуть петлю:
```
User feedback → FeedbackIndexer → DSPy dataset → 
BootstrapFewShotWithRandomSearch → оптимизированный prompt →
LangFuse prompt update → A/B test → rollout
```
**Автоматизация**: scheduled job раз в неделю → новая версия промптов.

### 3.7 🟢 AI Model Registry UI

`services/ai/embedding_registry.py` есть, но нет UI.  
**Предложение**: страница `49_Model_Registry.py`:
- Список моделей (LLM + embedding + reranker)
- Статус (active/deprecated/experimental)
- Бенчмарки по задачам
- Кнопка "Use in route" → добавление в DSL

### 3.8 🟢 Guardrails Dashboard

Lakera/Rebuff (Sprint 8) будут блокировать prompt injection.  
**Нужна видимость**: страница `47_AI_Safety.py`:
- Статистика заблокированных запросов по tenant
- Топ паттернов атак
- False positive rate
- Настройка порогов чувствительности

### 3.9 💡 Adaptive RAG — динамическое переключение стратегий

```python
class AdaptiveRAGStrategy:
    """Автоматически выбирает стратегию по типу запроса"""
    
    strategies = {
        "factual": "dense_retrieval",        # точные факты
        "analytical": "hybrid_bm25_dense",   # анализ документов  
        "generative": "hyde_expansion",      # генеративные вопросы
        "comparison": "multi_query",         # сравнение объектов
    }
    
    async def classify_and_retrieve(self, query: str) -> list[Chunk]: ...
```

### 3.10 💡 AI-driven Route Optimization

**Идея**: AI анализирует логи выполнения маршрутов и предлагает оптимизации:
- "Шаги A и B можно выполнить параллельно"
- "Кэширование шага C снизит latency на 40%"
- "Шаг D падает в 12% случаев — рекомендую retry"

***

## 4. Workflow / Оркестрация

### 4.1 🔴 Temporal Client — полная инфраструктурная обёртка

`infrastructure/workflow/temporal_backend.py` есть, но:
- `temporal_client.py` с DI-фабрикой отсутствует
- WorkerPool management не автоматизирован
- Heartbeat мониторинг для long-running activities нет

**Что добавить**:
```python
# infrastructure/workflow/temporal_client.py
class TemporalClientFactory:
    async def create_client(self, settings: WorkflowSettings) -> Client: ...
    async def create_worker(self, task_queue: str, ...) -> Worker: ...
    
class ActivityHeartbeatMonitor:
    async def monitor(self, activity_id: str, timeout: timedelta) -> None: ...
```

### 4.2 🟡 Visual Workflow Diff

**Проблема**: при смене версии workflow нет визуального сравнения.  
**Решение**: в `31_DSL_Visual_Editor.py` добавить "Workflow Diff":
- Два YAML → side-by-side граф
- Добавленные шаги — зелёные
- Удалённые — красные
- Изменённые — жёлтые
- Экспорт diff как BPMN-аннотация

### 4.3 🟡 Workflow Template Library с поиском

Текущие blueprints статичны. Нужна живая библиотека:
```
WorkflowTemplateRegistry:
  - templates: list[WorkflowTemplate]
  - search(query: str) -> list[WorkflowTemplate]  # семантический поиск
  - instantiate(template_id, params) -> WorkflowSpec
  - submit_community_template(spec) -> PendingReview
```
**UI**: `33_DSL_Templates.py` уже есть — наполнить живыми шаблонами.

### 4.4 🟡 Workflow SLA Alerting

**Идея**: каждый workflow может иметь SLA:
```yaml
# workflow.yaml
sla:
  max_duration_minutes: 30
  escalation_email: "ops@bank.ru"
  escalation_slack: "#credit-ops"
  business_hours_only: true  # не алертить в 3 ночи
```
**Реализация**: Temporal activity `SLAGuardActivity` + Apprise notification.

### 4.5 🟡 HITL (Human-in-the-Loop) Streamlit UI

`wait_for_signal` в Temporal уже есть.  
**Чего не хватает**: UI для операторов:
- Страница `17_Workflow_Replay.py` → вкладка "Pending Approvals"
- Карточка задачи с контекстом (данные заявки, рекомендация AI, score)
- Кнопки Approve / Reject / Request More Info
- История решений с SLA

### 4.6 🟢 Cron Expression Builder UI

**Проблема**: разработчики вручную пишут cron в route.toml.  
**Решение**: в `63_Feature_Flags.py` или новой странице `18_Scheduler.py`:
- Visual cron builder (компонент)
- "Next 5 executions" preview
- Timezone-aware (banking: московское время)
- Dry-run schedule simulation

### 4.7 🟢 Workflow Cost Estimation

До запуска workflow — оценка стоимости:
```python
class WorkflowCostEstimator:
    async def estimate(self, spec: WorkflowSpec, input_size_bytes: int) -> CostEstimate:
        return CostEstimate(
            llm_tokens_estimate=...,
            llm_cost_usd=...,
            compute_seconds=...,
            storage_bytes=...,
        )
```

### 4.8 💡 Reactive Workflow — Event-driven triggers без polling

```yaml
# workflow.yaml
trigger:
  type: event
  source: "credit.application.created"
  filter: "payload.amount > 1000000"
  debounce_seconds: 5
  deduplicate_by: "payload.application_id"
```
vs текущий cron-based / manual trigger.

***

## 5. Расширяемость (Plugin System)

### 5.1 🔴 Plugin Compatibility Matrix

**Проблема**: при наличии 10+ плагинов непонятно, какие конфликтуют.  
**Решение**: `plugin.toml` расширение + инструмент:
```toml
[plugin.compatibility]
conflicts_with = ["legacy_orders_v1"]
requires_plugins = ["core_entities.users>=2.0.0"]
incompatible_core_versions = ["<1.5.0"]
```
```bash
make check-compat  # tools/check_compat.py
# Output: ✅ credit_pipeline 1.2.0 совместим с core 1.8.0
#         ❌ legacy_plugin 0.3.0 конфликтует с core_entities.orders
```

### 5.2 🟡 Plugin Upgrade Migration Generator

```bash
make plugin-migrate-guide FROM=credit_pipeline:1.0.0 TO=credit_pipeline:2.0.0
# Генерирует:
# docs/migrations/credit_pipeline_1.0-2.0.md
# — Breaking changes
# — Automated migration steps
# — Manual steps
# — Rollback procedure
```

### 5.3 🟡 Plugin Marketplace с версионированием

`60_Plugin_Marketplace.py` есть.  
**Что добавить**:
- Semver changelog при установке
- Diff plugin.toml между версиями
- Rollback через `manage.py plugin rollback NAME --version 1.0.0`
- Plugin health-check endpoint

### 5.4 🟡 Plugin Dependency Graph

**Идея**: визуализация зависимостей плагинов:
```
core_entities.users ──┐
core_entities.orders ─┤
core_entities.files ──┼─→ credit_pipeline
example_plugin ────────┘
```
В Streamlit `60_Plugin_Marketplace.py` → вкладка "Dependency Graph" (D3.js через `st.components`).

### 5.5 🟡 Testkit Cassette Recorder

`testkit/` есть, но cassette-recorder отсутствует.  
**Идея** (VCR.py style для integration tests):
```python
@cassette("tests/cassettes/bki_query.yaml")
async def test_bki_integration():
    result = await bki_client.query(inn="7707049388")
    assert result.score > 0
# При первом запуске: реальный вызов → запись в cassette
# При последующих: воспроизведение из cassette (без сети)
```

### 5.6 🟢 Plugin Local Dev Server

```bash
manage.py plugin dev-server --plugin credit_pipeline --port 8001
# Запускает только этот плагин с hot-reload
# Mock всех внешних зависимостей (core, infra)
# Swagger UI только для эндпоинтов плагина
```

### 5.7 🟢 Cross-Plugin Event Bus с типизацией

```python
# extensions/credit_pipeline/plugin.py
@bus.on("core_entities.order.created", schema=OrderCreatedEvent)
async def handle_order_created(event: OrderCreatedEvent) -> None:
    await credit_service.start_assessment(event.order_id)
```
**Гарантии**: schema validation при publish/subscribe; несовместимые версии — compile-time error.

### 5.8 💡 Plugin Sandbox Isolation (Runtime)

Запуск untrusted плагинов в изолированной среде:
```python
class PluginSandbox:
    """RestrictedPython + resource limits"""
    max_memory_mb: int = 256
    max_cpu_seconds: float = 10.0
    allowed_imports: list[str]  # whitelist
    network_access: bool = False
```

***

## 6. Быстродействие

### 6.1 🔴 TaskIQ → Temporal Cron (BLOCKER #1)

Удалить `taskiq_broker.py`, мигрировать 13 callsites.  
Каждый `Invoker.ASYNC_QUEUE` → `temporal_client.start_workflow(cron_schedule=...)`.

### 6.2 🟡 RSGI Streaming для больших файлов

Granian RSGI ADR-0059 принят.  
**Gap**: большие файлы (>100MB) до сих пор буферизуются в памяти.  
**Решение**:
```python
# entrypoints/api/v1/endpoints/files.py
@router.post("/upload")
async def upload_file(request: RSGIRequest) -> Response:
    async for chunk in request.stream():  # RSGI streaming
        await s3_client.upload_part(chunk)
```
**Метрика**: RAM usage при загрузке 1GB файла должен быть < 50MB.

### 6.3 🟡 Lazy Processor Loading

Сейчас при старте импортируются ВСЕ 94 процессора.  
**Решение**:
```python
# dsl/engine/processors/__init__.py
class LazyProcessorRegistry:
    _registry: dict[str, str] = {  # name → module_path
        "ai": "dsl.engine.processors.ai",
        "rpa": "dsl.engine.processors.rpa",
        ...
    }
    
    def get(self, name: str) -> type[BaseProcessor]:
        if name not in self._loaded:
            self._loaded[name] = importlib.import_module(self._registry[name])
        return self._loaded[name]
```
**Цель**: startup time dev_light < 3 сек (сейчас ~8 сек).

### 6.4 🟡 ClickHouse Columnar Query Builder

Текущий analytics: raw SQL.  
**Предложение**: типизированный builder:
```python
audit_query = (
    ClickHouseQueryBuilder("audit_events")
    .select("action", "count()")
    .where("tenant_id", "=", tenant_id)
    .where("timestamp", ">=", since)
    .group_by("action")
    .order_by("count()", desc=True)
    .limit(100)
)
result = await ch_client.execute(audit_query)
```

### 6.5 🟡 msgspec Hotpath Expansion

`vault/benchmark-2026-05-15-structlog.md` + msgspec benchmark есть.  
**Расширить** msgspec на:
- Exchange serialization (сейчас: pydantic)
- Audit event serialization
- Cache key serialization
- WebSocket message framing

### 6.6 🟢 Response Compression Middleware

Добавить в ASGI chain:
```python
class BrotliCompressionMiddleware:
    min_size: int = 1024       # байт — не сжимать мелкие ответы
    quality: int = 4           # баланс скорость/степень
    exclude_paths: list[str] = ["/health", "/metrics"]
```
**Результат**: -60% трафика для JSON-ответов.

### 6.7 🟢 Database Read Replica Routing

```python
class SmartSessionManager:
    """Автоматически направляет SELECT на replica, INSERT/UPDATE на primary"""
    
    async def get_session(self, intent: Literal["read", "write"]) -> AsyncSession:
        if intent == "read" and self.replica_available():
            return await self._replica_pool.acquire()
        return await self._primary_pool.acquire()
```

### 6.8 💡 Pipeline Execution Parallelism Analyzer

Статический анализатор маршрута для выявления шагов, которые можно параллелизировать:
```python
analyzer = PipelineParallelismAnalyzer()
report = analyzer.analyze(route_spec)
# Output:
# Steps [3, 4, 5] have no data dependencies → can run in parallel
# Estimated speedup: 2.3x
# Suggested: wrap in .parallel() block
```

***

## 7. Документация

### 7.1 🔴 Tutorials по Diátaxis (Sprint 9 — минимум 9 шт.)

Отсутствующие tutorial'ы (критичные для онбординга):
1. `getting-started.md` — от `git clone` до первого маршрута
2. `build-first-action.md` — action → авторегистрация в 6 протоколах
3. `build-rest-connector.md` — импорт OpenAPI → codegen → DSL
4. `write-dsl-route.md` — YAML-маршрут с retry, circuit breaker, AI
5. `plugin-development.md` — создание плагина за 60 минут
6. `RAG-setup.md` — ingestion + retrieval + evaluation
7. `RPA-script.md` — web scraping + OCR + данные в БД
8. `multi-tenant-setup.md` — tenant onboarding + SLO
9. `workflow-with-hitl.md` — workflow + HITL approvals

### 7.2 🟡 Auto-generated Processor Documentation

`tools/generate_processors_doc.py` существует.  
**Улучшение**:
- Генерировать из docstrings + JSON-Schema ProcessorRegistry
- Включать примеры YAML и Python
- Выводить в `docs/reference/processors/`
- Собирать в Sphinx + публиковать в Streamlit Wiki

### 7.3 🟡 Route Flow Diagram Auto-export

```bash
make export-route-diagram ROUTE=routes/credit_pipeline/route.toml
# Генерирует:
# docs/generated/credit_pipeline.mermaid
# docs/generated/credit_pipeline.bpmn
# docs/generated/credit_pipeline.svg
```
**Streamlit**: в `31_DSL_Visual_Editor.py` кнопка "Export as BPMN/Mermaid/SVG".

### 7.4 🟡 ADR Decision Log в Streamlit Wiki

`60_Wiki.py` есть.  
**Добавить**: вкладка "Architecture Decisions":
- Список всех 46+ ADR
- Поиск по тексту (Whoosh — Sprint 8B)
- Статус (Proposed/Accepted/Deprecated)
- Связанные коммиты и wave-теги

### 7.5 🟢 Runbooks — минимум 10 шт. (Sprint 9)

Отсутствующие runbooks (критичные для эксплуатации):
1. `deploy-rollback.md`
2. `scale-out.md`
3. `incident-response.md`
4. `db-migration.md`
5. `cache-flush.md`
6. `audit-export.md`
7. `key-rotation.md`
8. `plugin-install.md`
9. `cdc-restart.md`
10. `temporal-worker-restart.md`

### 7.6 🟢 Sphinx Multi-version Documentation

```bash
make docs-publish  # Sprint 8B К5 W7
# Публикует docs/ в GitHub Pages
# Версии: latest, stable, v1.0, v0.9
```

### 7.7 💡 Интерактивная карта зависимостей в документации

Расширить Graphify-интеграцию:
- Экспорт графа в D3.js HTML
- Фильтрация по слою (core / infra / dsl / extensions)
- Поиск "где используется модуль X"
- Публикация как часть Sphinx docs

***

## 8. Удобство расширения для разработчиков (DX)

### 8.1 🔴 `make doctor` — диагностика окружения

```bash
make doctor
# ✅ Python 3.14.2
# ✅ uv 0.6.x
# ✅ PostgreSQL: connected (pool: 5/20)
# ✅ Redis: connected (memory: 42MB/512MB)
# ❌ Temporal: not running (start: make temporal-dev)
# ⚠️  Kafka: not configured (optional, set KAFKA_BOOTSTRAP_SERVERS)
# ✅ Vault: connected (seal status: unsealed)
# ❌ .env.example: 3 missing keys vs .env
```

### 8.2 🔴 `make scaffold-route` — интерактивный wizard

```bash
make scaffold-route
# ? Route name: credit_quick_check
# ? Source type: REST endpoint / Webhook / Scheduler / FileWatcher / ...
# ? Sink type: Database / S3 / Kafka / Email / ...
# ? Add AI step? Yes → Which model? (list from embedding_registry)
# ? Add retry? Yes → Max attempts: 3
# Generating: routes/credit_quick_check/route.toml
# Generating: routes/credit_quick_check/credit_quick_check.dsl.yaml
# Done! Run: make dsl-lint ROUTE=credit_quick_check
```

### 8.3 🟡 `make simulate` — dry-run с sample data

```bash
make simulate ROUTE=routes/credit_pipeline/credit_check.dsl.yaml \
              PAYLOAD='{"inn": "7707049388", "amount": 500000}'
# Running dry-run...
# Step 1: validate_input     → ✅ 12ms
# Step 2: bki_query          → 🔶 MOCK (BKI not configured in dev_light)
# Step 3: dsp_scoring        → ✅ 45ms (score: 0.73)
# Step 4: rule_engine        → ✅ 3ms (decision: approve)
# Total: 60ms | 0 errors | 1 mock
```

### 8.4 🟡 VSCode Extension для DSL

`dsl/cli/lsp_server.py` уже есть (Sprint 2).  
**Что сделать поверх LSP**:
- `.vsix` пакет в `tools/vscode-extension/`
- Syntax highlighting для `.dsl.yaml`
- Hover documentation для каждого шага (из ProcessorRegistry)
- "Run step" CodeLens для dry-run отдельного шага

### 8.5 🟡 Developer Onboarding Checklist

`manage.py onboarding` или `00_Tutorial.py` (Streamlit):
```
□ 1. Clone + uv install          (5 мин)
□ 2. make doctor                 (2 мин)
□ 3. make dev                    (запуск dev_light)
□ 4. Открыть Streamlit :8501     (1 мин)
□ 5. Создать первый route        (15 мин, tutorial)
□ 6. Запустить тест              (5 мин)
□ 7. Создать плагин              (30 мин, tutorial)
Total: ~1 час до первой рабочей интеграции
```

### 8.6 🟡 Plugin Development Mode с Hot-Reload

```bash
make plugin-dev NAME=my_plugin
# Запускает:
# - Только инфраструктуру (PG, Redis, MinIO)
# - Hot-reload плагина при изменении файлов
# - Mock всех внешних API
# - LiveReload Streamlit для страниц плагина
# - pytest --watch для тестов плагина
```

### 8.7 🟢 `make new-adr TITLE="..."` — scaffolding ADR

```bash
make new-adr TITLE="GraphQL DataLoader для N+1 prevention"
# Создаёт: docs/adr/0061-graphql-dataloader.md
# Шаблон с секциями: Context / Decision / Consequences / Alternatives
# Открывает в $EDITOR
```

### 8.8 🟢 CLI автодополнение (manage.py completions)

```bash
manage.py completions install --shell zsh
# Добавляет в ~/.zshrc source для completions
# manage.py plugin <TAB>     → install, uninstall, list, hot-swap, dev-server
# manage.py workflow <TAB>   → run, dryrun, import, export, replay
# manage.py route <TAB>      → lint, simulate, validate, list
```

### 8.9 🟢 Changelog автогенерация из wave-коммитов

```bash
make generate-changelog
# Читает git log --grep="^\[wave:"
# Группирует по Sprint → Team → Wave
# Генерирует CHANGELOG.md в Conventional Commits формате
# + обновляет Streamlit Wiki страницу "Releases"
```

### 8.10 💡 AI-assisted Code Review для Extensions

При открытии PR с изменениями в `extensions/`:
```yaml
# .github/workflows/ai-review.yml
- name: AI Code Review
  run: |
    manage.py ai review-pr \
      --diff ${{ github.event.pull_request.diff_url }} \
      --focus "layer-violations,security,performance,test-coverage" \
      --output pr-review.md
```
GitHub Action комментирует PR с предложениями.

### 8.11 💡 Interactive Architecture Map

`tools/generate_resource.py` → расширить до интерактивной карты:
- Streamlit страница с D3.js / Graphviz графом
- Нажать на модуль → docstring + зависимости + тесты
- Фильтр: "показать только AI-related модули"
- "Impact analysis": изменение модуля X затронет Y модулей

***

## 9. Матрица приоритетов

| Направление | Критично 🔴 | Важно 🟡 | Улучшение 🟢 | Инновация 💡 |
|---|:---:|:---:|:---:|:---:|
| DSL | 4 | 4 | 3 | 3 |
| Инфраструктура | 5 | 5 | 3 | 2 |
| AI/RAG | 1 | 5 | 2 | 2 |
| Workflow | 1 | 5 | 2 | 1 |
| Расширяемость | 1 | 3 | 3 | 2 |
| Быстродействие | 1 | 3 | 3 | 1 |
| Документация | 1 | 3 | 2 | 1 |
| DX | 2 | 4 | 5 | 2 |
| **Итого** | **16** | **32** | **23** | **14** |

***

## 10. Рекомендуемый порядок Sprint 9-16

### Sprint 9 (1 нед) — Финал Sprint 8 + Pre-prod Gate
- Закрыть BLOCKER #1 (TaskIQ), BLOCKER #3 (WAF)
- SAML backend (INF-6)
- Outbox dispatcher + Inbox dedup + DLQ unified
- `make doctor` (DX-8.1)
- 9 tutorials по Diátaxis

### Sprint 10 (2 нед) — DX + DSL Blueprint
- `make scaffold-route` wizard (DX-8.2)
- `make simulate` dry-run (DX-8.3)
- Blueprint library 20 паттернов (DSL-1.2)
- DSL Dry-run UI в Streamlit (DSL-1.5)
- Plugin local dev server (EXT-5.6)

### Sprint 11 (2 нед) — AI/RAG Completion
- Multimodal RAG полная реализация (AI-3.1)
- Prompt Version Control UI (AI-3.2)
- RAG Freshness Indicator (AI-3.3)
- Token Budget per Tenant (AI-3.4)
- AI Guardrails Dashboard (AI-3.8)

### Sprint 12 (2 нед) — Workflow Enhancement
- Temporal Client Factory (WF-4.1)
- Visual Workflow Diff (WF-4.2)
- HITL Streamlit UI (WF-4.5)
- Workflow SLA Alerting (WF-4.4)
- Cron Expression Builder UI (WF-4.6)

### Sprint 13 (2 нед) — Infra + Performance
- ClickHouse Async Bulk Writer (INF-2.3)
- RSGI Streaming для файлов (PERF-6.2)
- Lazy Processor Loading (PERF-6.3)
- Distributed Rate Limiter (INF-2.9)
- Read Replica Routing (PERF-6.7)

### Sprint 14 (2 нед) — Plugin Ecosystem
- Plugin Compatibility Matrix (EXT-5.1)
- Testkit Cassette Recorder (EXT-5.5)
- Cross-Plugin EventBus типизация (EXT-5.7)
- Plugin Dependency Graph UI (EXT-5.4)

### Sprint 15 (2 нед) — DX + Tooling
- VSCode Extension (DX-8.4)
- Plugin Dev Mode с Hot-Reload (DX-8.6)
- CLI автодополнение (DX-8.8)
- Pipeline Parallelism Analyzer (PERF-6.8)
- Adaptive RAG стратегии (AI-3.9)

### Sprint 16 (1 нед) — Innovation Sprint
- AI-driven Route Optimization (AI-3.10)
- Adaptive Timeout Policy (INF-2.10)
- Reactive Workflow triggers (WF-4.8)
- AI-assisted PR Review (DX-8.10)
- Interactive Architecture Map (DX-8.11)

***

## 11. Метрики успеха

| Метрика | Сейчас (May 2026) | Sprint 9 | Sprint 16 |
|---|---|---|---|
| Время до первого working route (онбординг) | ~4 часа | ~2 часа | ~1 час |
| Startup time (dev_light) | ~8 сек | ~5 сек | ~3 сек |
| p95 latency (cached route) | ~150ms | ~100ms | ~80ms |
| Processor count | 94 | 100+ | 120+ |
| Blueprint patterns | 5 | 15 | 25+ |
| Tutorial docs | 0 | 9 | 15+ |
| Runbooks | 0 | 10 | 20+ |
| Plugin ecosystem | 3 plugins | 5 plugins | 10+ plugins |
| mypy errors | >50 | ≤50 | 0 |
| Layer violations | >0 | 0 | 0 |
| Test coverage | ~35% | ≥70% | ≥80% |

***

## 12. Принципы реализации новых фич

1. **ADR first**: каждая архитектурная фича — новый ADR перед реализацией
2. **Feature-flag default-OFF**: все новые фичи скрыты за флагом до staging smoke
3. **Wave-commit pattern**: один wave = один атомарный коммит с тегом `[wave:sN/kM-wK-name]`
4. **DoD checklist**: каждая фича имеет явный Definition of Done
5. **testkit first**: если фича требует external call — сначала cassette/fixture
6. **80/20 декларативности**: YAML/TOML предпочтительнее Python для конфигурации
7. **Extensions only**: бизнес-логика — только в `extensions/`, ядро domain-agnostic
8. **Lazy imports**: все тяжёлые библиотеки (AI, RPA) — через `_ensure_<lib>()`
9. **Single Entry**: один CB / RL / Retry / Cache / Bulkhead через ResilienceCoordinator
10. **Observability by default**: каждый новый компонент — OTel spans + Prometheus метрики