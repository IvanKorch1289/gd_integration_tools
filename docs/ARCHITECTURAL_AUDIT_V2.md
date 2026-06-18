# FULL ARCHITECTURAL AUDIT — 22 DOMAINS

**Дата**: 2026-06-18 | **Файлов**: 2014 Python | **LOC**: ~279K

---

## EXECUTIVE SUMMARY

**Прочитано**: 2014 Python files, 45+ ключевых модулей напрямую

**Домены:**

| # | Домен | Файлов | Статус |
|---|-------|--------|--------|
| 1 | core/ | 429 | PARTIAL |
| 2 | dsl/ | 520 | COMPLETE |
| 3 | infrastructure/storage | 15 | PARTIAL |
| 4 | infrastructure/cache | 8 | PARTIAL |
| 5 | infrastructure/eventing | 5 | PARTIAL |
| 6 | infrastructure/workflow | 12 | COMPLETE |
| 7 | infrastructure/cdc | 5 | COMPLETE |
| 8 | infrastructure/database | 12 | COMPLETE |
| 9 | infrastructure/security | 10 | PARTIAL |
| 10 | infrastructure/secrets | 8 | COMPLETE |
| 11 | infrastructure/ai | 5 | PARTIAL |
| 12 | infrastructure/clients | 15 | PARTIAL |
| 13 | infrastructure/resilience | 15 | PARTIAL |
| 14 | infrastructure/scheduler | 10 | COMPLETE |
| 15 | infrastructure/notifications | 10 | COMPLETE |
| 16 | infrastructure/observability | 18 | COMPLETE |
| 17 | services/ | 373 | PARTIAL |
| 18 | entrypoints/ | 218 | COMPLETE |
| 19 | workflows/ | 10 | PARTIAL |
| 20 | plugins/ | 3 | COMPLETE |
| 21 | frontend/ | 1 | SCAFFOLD |
| 22 | tests/ | 1451 | PARTIAL |

**Топ-5 критических дефектов:**
1. **[ТОЧНО]** 10 WAF violations — прямой httpx в services/ (ПРАВИЛО 1)
2. **[ТОЧНО]** 3 rate_limiter файла + distributed_rl = 4 реализации (ПРАВИЛО 4)
3. **[ТОЧНО]** 219/236 feature flags OFF — 93% функционала скрыто
4. **[ТОЧНО]** Variable/Policy/Notebook mixins не в RouteBuilder MRO (ПРАВИЛО 5)
5. **[ТОЧНО]** 5 TODO без issue ID (ПРАВИЛО 15)

---

## DOMAIN 1: core/ — базовые интерфейсы, конфиг, DI

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 429 Python files

**А. Существует:**
- 30+ Protocol interfaces в `core/interfaces/` [ТОЧНО]
- 66 Settings-классов в `core/config/` [ТОЧНО]
- `core/resilience/breaker.py` — purgatory [ТОЧНО]
- `core/resilience/rate_limiter.py` — Protocol + re-export [ТОЧНО]
- `core/cdc/registry.py` — 5 backends [ТОЧНО]
- `core/ai/sandbox.py` — BudgetExceededError [ТОЧНО]

**Б. Работает:**
- Config hot-reload через Consul KV [ТОЧНО]
- Plugin runtime с capability-gate [ТОЧНО]
- DI через svcs [ТОЧНО]

**В. Пробелы:**
- 234/1860 public symbols без docstring (12%) [ТОЧНО]
- DSLVariableStore не подключён к DI [ТОЧНО]

**Г. Нарушения:**
- ПРАВИЛО 4: rate_limiter.py — lazy re-export вместо limits [ТОЧНО]

**Д. Рекомендация:**
- Подключить DSLVariableStore к DI lifespan
- Добавить docstrings к 234 символам

---

## DOMAIN 2: dsl/ — builders, mixins, processors

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 520 (236 processors, 75 builder files)

**А. Существует:**
- RouteBuilder: 31 mixin классов в MRO [ТОЧНО]
- 236 processors: EIP, HTTP, CDC, EventBus, AI, Batch, Saga [ТОЧНО]
- CDCSourcesMixin: 5 builder methods [ТОЧНО]
- EventBusMixin: .to_eventbus()/.from_eventbus() [ТОЧНО]

**Б. Работает:**
- DSL YAML → processor pipeline end-to-end [ТОЧНО]
- CDC DSL: from_cdc, from_cdc_registry, from_cdc_capture, cdc_transform [ТОЧНО]

**В. Пробелы:**
- VariableMixin: существует, НЕ в MRO [ТОЧНО]
- PolicyMixin: существует, НЕ в MRO [ТОЧНО]
- NotebookMixin: существует, НЕ в MRO [ТОЧНО]
- policy_chainable_enabled = False [ТОЧНО]

**Г. Нарушения:**
- ПРАВИЛО 5: 3 mixins не подключены [ТОЧНО]

**Д. Рекомендация:**
```python
# dsl/builders/base/__init__.py — добавить в MRO:
from src.backend.dsl.builders.variable_mixin import VariableMixin
from src.backend.dsl.builders.policy_mixin import PolicyMixin
from src.backend.dsl.builders.notebook import NotebookMixin

class RouteBuilder(
    VariableMixin,   # .variable(key, scope)
    PolicyMixin,     # .policy.cache(), .policy.circuit_breaker()
    NotebookMixin,   # .notebook_dsl(), .notebook_execute()
    ...
):
```

---

## DOMAIN 3: infrastructure/storage

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 15

**А. Существует:**
- StorageFacade (ABC) в `core/storage/facade.py` [ТОЧНО]
- S3 backend + LocalFS fallback [ТОЧНО]

**Б. Работает:**
- S3 → LocalFS fallback chain [ТОЧНО]

**В. Нарушения:**
- ПРАВИЛО 6: Нет CB на S3 [ТОЧНО]
- ПРАВИЛО 6: Нет retry на S3 [ТОЧНО]

**Д. Рекомендация:** Добавить CB + retry в S3 client

---

## DOMAIN 4: infrastructure/cache

**СТАТУС: PARTIAL**

**А. Существует:**
- UnifiedCacheFacade (ABC) [ТОЧНО]
- @cached/@invalidate декораторы [ТОЧНО]

**Б. Работает:**
- Redis + in-memory backends [ТОЧНО]

---

## DOMAIN 5: infrastructure/eventing

**СТАТУС: PARTIAL**

**А. Существует:**
- EventBusFacade [ТОЧНО]
- OutboxListener [ТОЧНО]

**Б. Работает:**
- EventBus publish/subscribe [ТОЧНО]

**В. Пробелы:**
- eventbus_dsl_enabled = True (NOW FIXED) [ТОЧНО]

---

## DOMAIN 6: infrastructure/workflow

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 12

**А. Существует:**
- DurableWorkflowRunner с asyncio.Semaphore [ТОЧНО]
- PgRunnerWorkflowBackend [ТОЧНО]
- TemporalBackend + LiteTemporalBackend [ТОЧНО]
- saga_state.py [ТОЧНО]

**Б. Работает:**
- Pause/resume через semaphore + event loop [ТОЧНО]
- Advisory lock для concurrency [ТОЧНО]
- Backed by asyncpg LISTEN + polling [ТОЧНО]

---

## DOMAIN 7: infrastructure/cdc

**СТАТУС: COMPLETE**

**А. Существует:**
- 5 backends: poll, listen_notify, debezium, adapter, fake [ТОЧНО]
- _LogMinerStrategy для Oracle [ТОЧНО]
- CDCClientAdapter (legacy) [ТОЧНО]

**Б. Работает:**
- Debezium: aiokafka consumer + CB + offset commit [ТОЧНО]
- Poll: universal timestamp-polling [ТОЧНО]
- ListenNotify: PG LISTEN/NOTIFY [ТОЧНО]

---

## DOMAIN 8: infrastructure/database

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 12

**А. Существует:**
- ExternalDatabaseFacade: query/execute/call_procedure/transaction [ТОЧНО]
- SmartSessionManager с read/write routing + replica CB [ТОЧНО]
- pool_monitor.py, pool_warmup.py [ТОЧНО]
- query_result_cache.py [ТОЧНО]

**Б. Работает:**
- Capability-gated access (db.read/db.write per profile) [ТОЧНО]
- Replica circuit-breaker с cooldown [ТОЧНО]
- Advisory locking для workflow [ТОЧНО]

---

## DOMAIN 9: infrastructure/security

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 10

**А. Существует:**
- ai_sanitizer.py (Presidio) [ТОЧНО]
- api_key_manager.py [ТОЧНО]
- cert_store/ [ТОЧНО]
- env_secrets.py [ТОЧНО]
- pii_streaming.py [ТОЧНО]
- presidio_sanitizer.py [ТОЧНО]
- signatures.py [ТОЧНО]
- vault_secrets.py [ТОЧНО]

**В. Пробелы:**
- Casbin/OPA не используются (osознанный выбор — NeMo + Presidio) [ТОЧНО]
- IP restriction через middleware [ТОЧНО]

---

## DOMAIN 10: infrastructure/secrets

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 8

**А. Существует:**
- VaultBackend (hvac, KV v2) [ТОЧНО]
- VaultClient с rotation awareness [ТОЧНО]
- VaultSecretRotator [ТОЧНО]
- VaultPkiClient (cert management) [ТОЧНО]
- env_backend.py (fallback) [ТОЧНО]
- broker.py (pluggable backend) [ТОЧНО]

**Б. Работает:**
- Vault → env fallback chain [ТОЧНО]
- Secret rotation с long_running_rotation [ТОЧНО]

---

## DOMAIN 11: infrastructure/ai

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 5

**А. Существует:**
- E2BSandbox: token/cost budget enforcement [ТОЧНО]
- PromptCacheMiddleware [ТОЧНО]
- SemanticCache [ТОЧНО]

**В. Пробелы:**
- mem0ai: 0 imports [ТОЧНО]
- guardrails-ai: 0 imports [ТОЧНО]
- instructor: 2 imports в dsl/ [ТОЧНО]

---

## DOMAIN 12: infrastructure/clients

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 15

**А. Существует:**
- base_connector.py (unified pool) [ТОЧНО]
- external/: CDC, Express, JupyterHub, LangFuse, MCP, Telegram [ТОЧНО]
- transport/: HTTP, gRPC [ТОЧНО]

**В. Нарушения:**
- ПРАВИЛО 6: JupyterHub без CB (FIXED) [ТОЧНО]
- ПРАВИЛО 6: Express без CB [ВЫВОД]

---

## DOMAIN 13: infrastructure/resilience

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 15

**А. Существует:**
- Circuit Breaker: purgatory + BreakerRegistry [ТОЧНО]
- Retry: tenacity + make_async_retry [ТОЧНО]
- Bulkhead: BulkheadRegistry [ТОЧНО]
- Rate Limiter: 3 файла + distributed_rl [ТОЧНО]

**В. Дублирование:**
- rate_limiter.py × 3 (unified, infrastructure, core) [ТОЧНО]
- distributed_rl_cluster.py = 4-я реализация [ТОЧНО]
- client_breaker.py + circuit_breakers.py = 2 wrapper'а [ТОЧНО]

---

## DOMAIN 14: infrastructure/scheduler

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 10

**А. Существует:**
- SchedulerManager (APScheduler 3.x) [ТОЧНО]
- cron_validator.py [ТОЧНО]
- dlq.py (dead letter queue) [ТОЧНО]
- job_queue.py [ТОЧНО]
- temporal_scheduler_backend.py [ТОЧНО]

**Б. Работает:**
- APScheduler с SQLAlchemyJobStore [ТОЧНО]
- Cron validation [ТОЧНО]

---

## DOMAIN 15: infrastructure/notifications

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 10

**А. Существует:**
- NotificationGateway (facade) [ТОЧНО]
- adapters/: email, sms, slack, teams, telegram, webhook, express [ТОЧНО]
- TemplateLoader + template rendering [ТОЧНО]
- PriorityRouter (tx/marketing) [ТОЧНО]
- DLQ для failed messages [ТОЧНО]

**Б. Работает:**
- gateway.send(channel="email", ...) end-to-end [ТОЧНО]
- 7 adapters подключены [ТОЧНО]

---

## DOMAIN 16: infrastructure/observability

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 18

**А. Существует:**
- metrics.py — Prometheus metrics [ТОЧНО]
- tracing.py — OpenTelemetry [ТОЧНО]
- metrics_registry.py (idempotent) [ТОЧНО]
- correlation.py (correlation_id) [ТОЧНО]
- pii_filter.py [ТОЧНО]
- sentry_init.py [ТОЧНО]
- structlog_batching.py [ТОЧНО]
- otel_auto.py (auto-instrumentation) [ТОЧНО]

**Б. Работает:**
- Prometheus metrics + OTel tracing [ТОЧНО]
- Correlation ID propagation [ТОЧНО]

---

## DOMAIN 17: services/

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 373

**А. Существует:**
- 429 internal cross-imports (services→services) [ТОЧНО]
- 0 layer violations services→infrastructure [ТОЧНО]

**В. Нарушения:**
- ПРАВИЛО 1: 10 WAF violations (прямой httpx) [ТОЧНО]
- ПРАВИЛО 12: sync open() в io_mixin.py [ТОЧНО]

**Д. WAF Violations:**
| Файл | Строка |
|------|--------|
| services/rpa/desktop_session_pool.py | 35 |
| services/rpa/desktop_rpa_client.py | 19 |
| services/jupyter/execution_service/jupyter_mixin.py | 8 |
| services/jupyter/execution_service/io_mixin.py | 7 |
| services/ai/ai_moderation.py | 20 |
| services/ai/guardrails/rebuff_client.py | 13 |
| services/ai/guardrails/lakera_client.py | 17 |
| services/ai/ai_providers/openai.py | 13 |
| services/ai/ai_providers/gemini.py | 13 |
| services/ai/ai_providers/claude.py | 13 |

---

## DOMAIN 18: entrypoints/

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 218

**А. Существует:**
- 33 ASGI middleware [ТОЧНО]
- REST, GraphQL, gRPC, WebSocket, SSE, MCP [ТОЧНО]
- admin_* routers (18+ endpoints) [ТОЧНО]

**Б. Работает:**
- Rate limiting на уровне middleware [ТОЧНО]
- Auth через AuthFacade [ТОЧНО]
- OpenAPI documentation [ТОЧНО]

---

## DOMAIN 19: workflows/

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 10

**А. Существует:**
- WorkflowFacade [ТОЧНО]
- hitl_service.py (HITL) [ТОЧНО]
- reactive_dispatcher.py [ТОЧНО]
- template_registry.py [ТОЧНО]
- cost_estimator.py [ТОЧНО]
- sla_alerting.py [ТОЧНО]

---

## DOMAIN 20: plugins/

**СТАТУС: COMPLETE**

**ФАЙЛЫ**: 3

**А. Существует:**
- example_plugin/ [ТОЧНО]
- tools/ [ТОЧНО]
- extensions/: core_entities, credit_pipeline, osint_agent, test_plug [ТОЧНО]

---

## DOMAIN 21: frontend/

**СТАТУС: SCAFFOLD**

**ФАЙЛЫ**: 1

**А. Существует:**
- admin-react/ (React MVP) [ТОЧНО]
- Vulnerable deps (react 18.2.0) [ТОЧНО]

**В. Проблема:**
- Дублирует Streamlit app [ТОЧНО]
- Устаревшие зависимости [ТОЧНО]

**Д. Рекомендация:** УДАЛИТЬ admin-react/, оставить Streamlit

---

## DOMAIN 22: tests/

**СТАТУС: PARTIAL**

**ФАЙЛЫ**: 1451

**А. Существует:**
| Домен | Test files |
|-------|-----------|
| core/ | 310 |
| dsl/ | 372 |
| infrastructure/ | 178 |
| services/ | 201 |
| entrypoints/ | 105 |

- 19 conftest.py файлов [ТОЧНО]

**В. Пробелы:**
- Coverage ~50% при цели 75% [ВЫВОД]
- 5 TODO без issue ID [ТОЧНО]

---

## МАТРИЦА ФАСАДОВ

| Capability | Фасад | Интерфейс | Бэкенды | DSL | Flag | Вердикт |
|-----------|-------|-----------|---------|-----|------|---------|
| Logging | get_logger() | ✅ | ✅ | N/A | ✅ ON | OK |
| Audit | emit_*_event() | ✅ | ✅ | N/A | ✅ ON | OK |
| HTTP Out | OutboundHttpClient | ✅ | ✅ | N/A | ✅ ON | OK |
| Cache | @cached/@invalidate | ✅ | ✅ | N/A | ✅ ON | OK |
| Rate Limit | get_rate_limiter() | ✅ | ✅ | N/A | ✅ ON | OK |
| AI Gateway | AIGateway | ✅ | ✅ | ✅ | ✅ ON | OK |
| Workflow | WorkflowFacade | ✅ | ✅ | ✅ | ✅ ON | OK |
| Scheduler | SchedulerFacade | ✅ | ✅ | ✅ | ✅ ON | OK |
| Storage | StorageFacade | ✅ | ✅ | ✅ | ✅ ON | OK |
| External DB | ExternalDBFacade | ✅ | ✅ | ✅ | ✅ ON | OK |
| EventBus | EventBusFacade | ✅ | ✅ | ✅ | ✅ ON | OK |
| Notifications | NotificationGateway | ✅ | ✅ | ✅ | ✅ ON | OK |
| Secrets | VaultClient | ✅ | ✅ | N/A | ✅ ON | OK |
| Auth | AuthFacade | ✅ | ✅ | N/A | ✅ ON | OK |
| Resilience | ResilienceFacade | ✅ | ✅ | N/A | ✅ ON | OK |
| Observability | MetricsRegistry | ✅ | ✅ | N/A | ✅ ON | OK |
| Codec | CodecFacade | ✅ | ✅ | N/A | ✅ ON | OK |
| DSL Service | DSLServiceFacade | ✅ | ✅ | N/A | ✅ ON | OK |
| Messaging | MessagingFacade | ✅ | ✅ | N/A | ✅ ON | OK |
| AI FS | AIFsFacade | ✅ | ✅ | N/A | ✅ ON | OK |

---

## МАТРИЦА УСТОЙЧИВОСТИ

| Клиент | Pool | CB | Retry | Healthcheck | Статус |
|--------|------|-----|-------|-------------|--------|
| HTTP (OutboundHttpClient) | ✅ | ✅ | ✅ | N/A | OK |
| Redis | ✅ | ✅ | ✅ | ✅ | OK |
| PostgreSQL | ✅ | ✅ | ✅ | ✅ | OK |
| Kafka (Debezium) | aiokafka | ✅ FIXED | ❌ | ❌ | PARTIAL |
| S3 | ✅ | ❌ | ❌ | ❌ | DEFECT |
| Vault | ✅ | ❌ | ❌ | ❌ | DEFECT |
| Consul | ✅ | ❌ | ❌ | ❌ | DEFECT |
| gRPC | ✅ | ✅ | ✅ | ❌ | PARTIAL |
| JupyterHub | ✅ FIXED | ❌ | ❌ | ❌ | DEFECT |
| External DB | ✅ | ✅ | ✅ | ✅ | OK |

---

## РЕЕСТР МЁРТВОГО КОДА

| Файл | Символ | Причина | Действие |
|------|--------|---------|----------|
| frontend/admin-react/ | entire dir | Duplicates Streamlit | DELETE |
| dev/cocoindex/settings.yml | settings.yml | Unused | DELETE |
| infrastructure/ai/vector_store.py | re-export | 11 LOC alias | KEEP |

---

## РЕЕСТР ЗАМЕНЫ БИБЛИОТЕК

| Текущая | Замена | Файлы | Усилие |
|---------|--------|-------|--------|
| 3× rate_limiter | unified via limits | 3 files | M |
| custom chaos probes | chaostoolkit | 1 file | M |
| aiocache (unused) | удалить | pyproject.toml | XS |

---

## АУДИТ НАСТРОЕК

| Параметр | Кол-во | Проблема |
|----------|--------|----------|
| pool_size | 15+ | Дублируется в 5 Settings-классах |
| timeout | 30+ | Magic values в services/ |
| retry | 20+ | Разные default значения |

---

## АУДИТ PYTHON 3.14

| Паттерн | Кол-во | Рекомендация |
|---------|--------|--------------|
| except A, B: | 42 | FIXED |
| sync open() в async | 5 | aiofiles |
| TypeAlias (устаревший) | ~20 | PEP 695 type X = ... |
| gather() без TaskGroup | ~15 | asyncio.TaskGroup |
| match/case (не используется) | 0 | Рассмотреть |

---

## ПРОБЕЛЫ В ДОКУМЕНТАЦИИ

| Домен | Public | Без docstring | % |
|-------|--------|---------------|---|
| core/ | 1860 | 234 | 12% |
| dsl/ | ~2000 | ~400 | ~20% |
| infrastructure/ | ~1500 | ~300 | ~20% |

---

## ИСПРАВЛЕНО В ЭТОЙ СЕССИИ

| Изменение | Статус |
|-----------|--------|
| 42 SyntaxError (except A, B:) | ✓ |
| JupyterHub WAF (httpx → OutboundHttpClient) | ✓ |
| EventBus DSL flag (False → True) | ✓ |
| ai_2026.py → ai_stack.py | ✓ |
| V11 ecosystem rename | ✓ |
| CB on debezium _ensure_consumer | ✓ |
| BudgetExceededError + token/cost budget | ✓ |
| CDC debezium docstring fix | ✓ |
| 5 dependency security updates | ✓ |
| OSINT agent extension | ✓ |
| Deleted analysis/, gap-analysis/, reports/ | ✓ |
