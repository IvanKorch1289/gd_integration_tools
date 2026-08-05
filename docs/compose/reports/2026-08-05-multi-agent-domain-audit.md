# gd_integration_tools — повторный доменный аудит (multi-agent, 05.08.2026)

> **Метод**: 11 параллельных subagent'ов с чистым контекстом, каждый читал только
> файлы своего домена без трансляции выводов из предыдущих сессий.
> Коммит на момент анализа: `5df9190d` (master), `pyproject.toml version = 0.20.0`.
>
> **Цель**: получить честную картину состояния проекта после циклов доработки
> S171–S176, отделить реальные блокеры от устаревших находок, выставить приоритеты.

---

## Сводка по доменам (TL;DR)

| # | Домен | Отчёт агента | Статус |
|---|---|---|---|
| 1 | Инфраструктура (L9) | general-1 | OTel logs не несут trace_id; docker-compose без resource limits; ~12 из 38 pre-prod gates — no-op |
| 2 | Безопасность (L8) | general-2 | Sandbox/auth/Argon2 закрыты; CapabilityGate race; middleware ordering (DataMasking до Auth); дубль PII middleware |
| 3 | Data & State (L6) | general-3 | CDC DLQ ✓; S3 multipart abort; DLQ retention без partition; Worker Versioning dead; Memcached delete_pattern silent |
| 4 | Entrypoints & API (L1) | general-4 | Multi-protocol регистрация реальна; CDC/Email без explicit auth; gRPC/MQTT слабая защита; route_timeouts dead |
| 5 | DSL engine (L2) | general-5 | RouteBuilder MRO=37; `@processor` покрытие ~22%; call_function dev-bypass; Idempotency DSL↔HTTP нет общего контракта |
| 6 | Workflow / Temporal | general-12 | Scheduler DLQ не подключён к lifespan; Worker Versioning default OFF; TemporalSchedulerBackend не wired; compensation worker отсутствует |
| 7 | AI Agents / RAG | general-7 | Sandbox ✓; LangMem ✓; banking processors ✓; **Guardrails FAIL-OPEN**, supervisor-loop вместо LLM, tool whitelist exact-match не glob |
| 8 | RPA | general-8 | Cookie encryption ✓; 3-layer defense ✓; **operations/__init__.py не re-export 7 новых процессоров**, FtpUpload password в self.password |
| 9 | Business Logic / Plugins | general-9 | Capability-gate ✓; per-plugin shutdown ✓; credit_pipeline — heuristic stub; extensions coverage неполный |
| 10 | Dependencies / Settings | general-10 | Version drift; uv.lock 6 дней stale; Consul в dev-group вместо extras; **10+ feature-flags default-ON при "default-OFF" описании** |
| 11 | Testing / Observability | general-11 | **ClickHouse audit БЕЗ retry/DLQ**; layer check FAIL (3 новых нарушения); start_span — NO-OP shim; polars отсутствует — test collection broken |

---

## Кросс-доменные паттерны (по агрегатам)

### Что реально УСТРАНЕНО в циклах S171–S176 (подтверждено кодом)

| ID | Находка | Подтверждение | Цикл |
|---|---|---|---|
| B-02 | CDC event loss | `cdc/client.py::_dispatch_change` сериализует в `DLQEnvelope` и пишет через `DLQWriter` | S176 |
| B-04 | hot_swap задевал все плагины | `PluginLoader.shutdown_one` + audit-event | S176 |
| B-07 | SecurityHeaders race condition | pure ASGI rewrite в `security_headers.py:53-110` | S176 |
| P0-1 | InProcessAgentSandbox | dual-gate (env+feature_flag); fail-closed по умолчанию | S176 |
| P0-3 | Module whitelist "for MVP" | fail-closed через `call_function_whitelist_strict` (default ON) | S176 |
| P0-6 | yaml.load без safe_load | grep → 0 вхождений | S176 |
| P0-7 | Symlink race в fs_facade | realpath ДО/ПОСЛЕ конкатенации | S176 |
| P0-8 | API-ключи без соли | Argon2id PHC + migration script | S176 |

### Что РЕАЛЬНО ОТКРЫТО (cross-domain)

| # | Домен | Severity | Проблема |
|---|---|---|---|
| 1 | Testing | CRITICAL | ClickHouse audit batch — no retry/DLQ → SOC-2 gap на любом network blip |
| 2 | Testing | CRITICAL | Layer check FAILED (exit 1) — 3 НОВЫХ нарушения: entrypoints → `dsl.engine.context` |
| 3 | Testing | HIGH | `start_span` — hard-coded no-op contextmanager (ADR-NEW-21 carryover) |
| 4 | Testing | HIGH | Test collection broken — `polars` отсутствует, `pytest --co` exit non-zero |
| 5 | Workflow | HIGH | Scheduler DLQ listener не подключён к lifespan → admin endpoint всегда 503 |
| 6 | Workflow | HIGH | WorkerVersioningHelper default `use_versioning=False` → D172/S171 P0 dead code |
| 7 | Workflow | HIGH | Compensation worker отсутствует — `WorkflowState.state="compensating"` ни разу не драйнится |
| 8 | AI | HIGH | GuardrailsProcessor FAIL-OPEN при отсутствии LAKERA_API_KEY или feature_flag OFF |
| 9 | AI | HIGH | Supervisor "LLM router" — детерминированный loop вместо LLM call |
| 10 | DSL | HIGH | RouteBuilder MRO depth = 37 (god-class) |
| 11 | DSL | HIGH | `@processor` покрытие ~22% (64/295) → JSON-Schema/AsyncAPI/LSP пустые |
| 12 | Security | HIGH | CapabilityGate race на `_cache`/`_tenant_cache` (нет asyncio.Lock) |
| 13 | Security | HIGH | DataMaskingMiddleware @ order=580 (до Auth @ 620) → leaks JSON shape anonymous |
| 14 | Data | HIGH | S3 multipart upload без abort на cancel/OOM |
| 15 | Data | HIGH | DLQ retention: `DELETE FROM dlq_events` без partition pruning |
| 16 | Infra | HIGH | structlog НЕ пробрасывает trace_id/span_id из OTel |
| 17 | Workflow | HIGH | TemporalSchedulerBackend — код есть, в SchedulerManager не подключён |
| 18 | Workflow | HIGH | `TemporalSchedulerBackend.list_jobs()` — process-local dict, теряется на рестарте |
| 19 | DSL | MEDIUM | call_function empty-whitelist → dev-bypass (strict только в ENVIRONMENT=production) |
| 20 | DSL | MEDIUM | IdempotentConsumerProcessor (DSL) vs IdempotencyMiddleware (HTTP) — разные key-prefixes |
| 21 | DSL | MEDIUM | WorkflowBuilder 0 prod-callers (только docstring/tests) — dead DSL |
| 22 | Workflow | MEDIUM | `TemporalWorkerPool.shutdown()` sequential, не "parallel" как в docstring |
| 23 | Workflow | MEDIUM | `patched()` helper — нет prod-callers |
| 24 | AI | MEDIUM | Tool whitelist `tools_policy.py:73-78` — exact match, не glob (docstring лжёт) |
| 25 | AI | MEDIUM | LangFuse callback НЕ wired в lifespan (lazy per-call) |
| 26 | AI | MEDIUM | Multimodal RAG — нет E2E/integration теста (только unit с in-memory) |
| 27 | RPA | HIGH | `rpa/operations/__init__.py` НЕ re-export 7 новых процессоров → backward-compat сломан |
| 28 | RPA | MEDIUM | `windows_worker/handlers/desktop_rpa_handler.py` отсутствует на диске — DesktopRpaClient прибит к несуществующему sidecar |
| 29 | RPA | MEDIUM | FtpUploadProcessor — `self.password` plaintext хранится на весь lifetime |
| 30 | Security | MEDIUM | DataMaskingMiddleware + PIIMaskingResponseMiddleware дублируют, double-mask |
| 31 | Entrypoints | MEDIUM | CDC/Email REST routes — нет explicit `Depends(require_auth)` (defense-in-depth) |
| 32 | Entrypoints | MEDIUM | gRPC AuthInterceptor opt-in — если `api_key=None`, mTLS-only без fallback |
| 33 | Entrypoints | MEDIUM | MQTT — нет per-message authz, только broker-level |
| 34 | Entrypoints | MEDIUM | `TimeoutMiddleware.route_timeouts` не wired (dead code на boot) |
| 35 | Entrypoints | MEDIUM | `MiddlewareSpec.enabled_routes/disabled_routes` объявлены, но НЕ honored в `apply_to_app` |
| 36 | Entrypoints | MEDIUM | IdempotencyMiddleware → 5xx при Redis ConnectionError (нет graceful fallback) |
| 37 | Infra | MEDIUM | docker-compose.prod.yml без `mem_limit/cpus` — runaway memory risk |
| 38 | Infra | MEDIUM | pre_prod_check.py: 12 из 38 gates — `_check_warning` no-op |
| 39 | Infra | MEDIUM | Coverage gate mismatch: pre-prod 50% vs CI 75% |
| 40 | Data | MEDIUM | Kafka consumer-lag monitoring не реализован end-to-end (метрика есть, вызовов нет) |
| 41 | Data | MEDIUM | Memcached `delete_pattern` — silent no-op (multi-tenant invalidation leak) |
| 42 | Data | MEDIUM | Vault token renew только per-call (idle >7 дней → TTL expires) |
| 43 | Config | MEDIUM | pyproject version 0.20.0 vs PLAN/AGENTS v1.0.0 claims |
| 44 | Config | MEDIUM | `python-consul2` в dev-group, должен быть `[consul]` extra |
| 45 | Config | MEDIUM | `prod.yml` не override `enable_swagger/enable_redoc=false` → validator CRITICAL на каждом prod startup |
| 46 | Plugins | MEDIUM | credit_pipeline — DTI heuristic, не validated ML (риск mis-позиционирования) |
| 47 | Plugins | MEDIUM | extensions coverage: тесты есть только у `credit_pipeline` и `core_entities/*`; нет у `dadata/core_admin/skb/example_plugin/test_plug` |

---

## Глобальный приоритизированный план (для Kimi)

### P0 — Data Loss / Reliability (немедленно)

```
1. [Testing] ClickHouseAuditService.emit_batch: добавить tenacity retry + Postgres DLQ таблицу
   Файл: src/backend/services/audit/clickhouse_audit_service/service.py:146-158
   Accept: 3 retry с exponential backoff → DLQ при exhausted → audit-event

2. [Testing] tools/check_layers.py → закрыть 3 НОВЫХ нарушения
   Файлы: entrypoints/_action_bridge.py, graphql/schema.py, soap/soap_handler.py
   Accept: grep "from src.backend.dsl.engine.context" в entrypoints/ → 0

3. [Testing] Заменить start_span no-op на реальный OTel tracer.start_as_current_span
   Файл: src/backend/core/observability/correlation.py:119-136
   Accept: pytest tests/unit/core/observability/ — 100% pass + integration тест с jaeger

4. [Testing] Добавить polars в dev-extras или skip test_dataframes.py при отсутствии
   Accept: pytest --collect-only exit 0

5. [Workflow] Wire attach_scheduler_dlq() в SchedulerManager.start()
   Файл: src/backend/infrastructure/scheduler/scheduler_manager.py:75-97
   Accept: GET /admin/scheduler/dlq → 200, не 503

6. [Workflow] WorkerVersioningHelper — прокинуть use_versioning=True + deployment/build_id из settings
   Файл: src/backend/infrastructure/workflow/temporal_client.py:256-260
   Accept: build_worker_kwargs() возвращает deployment_config при feature_flag=temporal_worker_versioning

7. [Workflow] Реализовать compensation worker — drain WorkflowStateRepository.list_compensating()
   Accept: 1 activity handler per compensation chain + integration тест

8. [AI] GuardrailsProcessor — flip default на fail-closed при LAKERA_API_KEY unset
   Файл: src/backend/dsl/engine/processors/ai/guardrails_processor.py:74,86
   Accept: в prod profile отсутствие LAKERA_API_KEY → GuardrailViolationError, не silent skip

9. [AI] Supervisor "LLM router" — реальная LLM call через ChatOpenAI + tool-calling
   Файл: src/backend/services/ai/multi_agent/supervisor.py:324-331
   Accept: supervisor использует init_chat_model; integration тест показывает недетерминированный routing

10. [Security] CapabilityGate — добавить asyncio.Lock на _cache/_tenant_cache
    Файл: src/backend/core/security/capabilities/gate/{check_mixin,cache_mixin}.py:60-67
    Accept: concurrent grant+revoke тест показывает отсутствие race

11. [Security] Middleware ordering: AuthRequired(620) → DataMasking(580)→? починить LIFO семантику
    Файл: src/backend/entrypoints/middlewares/setup_middlewares.py:191,197
    Accept: анонимный запрос не вызывает DataMasking парсинг body

12. [Data] S3 multipart upload: try/finally с abort_multipart_upload на cancel/OOM
    Файл: src/backend/infrastructure/storage/s3.py:262-344
    Accept: asyncio.CancelledError + MemoryError → abort_multipart_upload вызван

13. [Data] DLQ retention: мигрировать dlq_events на PARTITION BY toYYYYMM(created_at)
    Файл: src/backend/infrastructure/messaging/dlq/cleanup_job.py:75-102
    Accept: ALTER TABLE ... DROP PARTITION заменяет DELETE; latency cleanup < 1s на 100M строк

14. [RPA] rpa/operations/__init__.py — re-export 7 S171 процессоров
    Accept: from src.backend.dsl.engine.processors.rpa.operations import FileDeleteProcessor — OK

15. [RPA] windows_worker/handlers/desktop_rpa_handler.py — создать stub или удалить DesktopRpaClient
    Accept: либо stub отдаёт 503 с явным сообщением, либо класс удалён
```

### P1 — Архитектурные границы

```
16. [DSL] RouteBuilder — декомпозиция через CompositionRouteBuilder + Protocol-based mixins
    Файл: src/backend/dsl/builders/base/__init__.py:70-107
    Accept: MRO depth ≤ 10; старый RouteBuilder помечен deprecated

17. [DSL] @processor decorator coverage: bulk-декорировать оставшиеся 230 процессоров
    Accept: export_schemas() покрывает ≥ 95% BaseProcessor subclasses

18. [DSL] call_function — strict whitelist для всех env, кроме dev_light через feature-flag
    Файл: src/backend/dsl/engine/processors/function_call.py:140-167
    Accept: в staging пустой whitelist → PermissionError, не silent allow

19. [DSL] Унифицировать idempotency key-prefix/TTL в shared services/idempotency/key_strategy.py
    Accept: HTTP и DSL используют одну key-функцию; integration тест

20. [DSL] Удалить или deprecate WorkflowBuilder (0 prod-callers)
    Accept: либо docs явно говорят "use Temporal activities", либо класс удалён

21. [DSL] 3 layer-violations entrypoints → dsl.engine.context: вынести ExecutionContext adapter
    Accept: tools/check_layers.py exit 0

22. [Workflow] TemporalSchedulerBackend — wire в SchedulerManager за feature-flag
    Файл: src/backend/infrastructure/scheduler/scheduler_manager.py + temporal_scheduler_backend.py
    Accept: settings.scheduler.backend="temporal" → SchedulerManager использует Temporal; APScheduler остаётся default

23. [Workflow] TemporalWorkerPool.shutdown() — asyncio.gather(*workers) с return_exceptions=True
    Файл: src/backend/infrastructure/workflow/temporal_client.py:277-291
    Accept: docstring соответствует коду; load тест показывает N-кратное ускорение

24. [AI] tool whitelist: реализовать glob через fnmatch либо исправить docstring
    Файл: src/backend/core/ai/policy/enforcer/tools_policy.py:73-78
    Accept: whitelist=["db.*"] корректно работает

25. [AI] LangFuse: добавить init/flush hooks в lifespan startup/shutdown
    Accept: callback warmup + flush-on-shutdown

26. [AI] Multimodal RAG E2E тест с Qdrant + BLIP2/Whisper
    Accept: tests/integration/services/ai/rag/test_multimodal_qdrant_e2e.py → 100% pass

27. [Entrypoints] route_timeouts: wire из RouteManifest в TimeoutMiddleware на lifespan
    Accept: per-route timeout реально применяется

28. [Entrypoints] MiddlewareSpec.enabled_routes/disabled_routes: honor в apply_to_app
    Accept: registry.py:266 → проверяет enabled_routes/disabled_routes

29. [Entrypoints] IdempotencyMiddleware: fallback на MemoryBackend при Redis ConnectionError
    Accept: integration тест с redis down → POST возвращает 200 (degraded mode), не 500

30. [Entrypoints] gRPC AuthInterceptor: refuse-to-start без api_key И без mTLS
    Accept: production profile не стартует без auth

31. [Entrypoints] MQTT per-message principal extraction (tenant_id in topic / JWT in payload)
    Accept: broker auth + message-level authz оба активны

32. [Security] CapabilityGate + WAF strict=True default для HttpRequestProcessor
    Файл: src/backend/dsl/engine/processors/rpa/operations/httprequestprocessor.py:75-83
    Accept: waf_policy kwarg обязателен; deny-all если не задан

33. [Security] Удалить DataMaskingMiddleware — оставить PIIMaskingResponseMiddleware
    Accept: единый middleware для PII masking; double-masking устранён

34. [Infra] structlog → _add_otel_trace processor с trace_id/span_id из current OTel span
    Файл: src/backend/infrastructure/logging/structlog_backend.py:266-279
    Accept: каждый log record имеет trace_id; Jaeger ↔ logs correlation работает

35. [Infra] docker-compose.prod.yml: добавить mem_limit/cpus для каждого сервиса
    Accept: 0 services без limits

36. [Infra] pre_prod_check.py: заменить _check_warning stubs на реальные проверки
    Accept: 38/38 gates — реальные blocking checks

37. [Data] Kafka consumer-lag: periodic poller в outbox worker + Debezium consumer
    Accept: kafka_consumer_lag{topic,group,partition} gauge в Prometheus

38. [Data] Memcached delete_pattern — assert в TenantCacheBackend.delete_pattern
    Accept: ошибка на Memcached backend + multi-tenant integration test

39. [Data] Vault periodic token renewal в VaultClient.start() (background task)
    Accept: AppRole token не истекает при idle workload

40. [Data] Pool auto-recovery в PoolMonitor при utilization >95%
    Accept: stale connections evicted автоматически

41. [Plugins] extensions coverage: добавить contract/registration tests для dadata/core_admin/skb/example_plugin/test_plug
    Accept: pytest tests/unit/extensions/ покрывает ≥80% extensions

42. [Plugins] credit_pipeline — явно маркировать как heuristic/stub; запретить production use без validated model
    Accept: docstring + feature flag + runtime warning

43. [Config] prod.yml: добавить app.enable_swagger=false, app.enable_redoc=false
    Accept: ConfigValidator на prod startup — 0 CRITICAL

44. [Config] python-consul2 → [project.optional-dependencies].consul extra
    Accept: uv sync без --extra dev не устанавливает consul

45. [Config] Feature-flags default-ON drift — 10+ флагов с Field(default=True) при "default-OFF" описании
    Accept: grep "default-OFF" в docstring И Field(default=True) → 0 вхождений
```

### P2 — Замена кастомного кода на библиотеки

```
46. [Security] CapabilityGate LRU → functools.lru_cache-like wrapper (или cachetools.LRUCache)
47. [Security] HttpRequestProcessor — оценить замену кастомного WAF на slowapi/limits
48. [AI] Supervisor orchestration — рассмотреть langgraph-supervisor вместо кастомного loop
49. [Workflow] Sandbox для workflow activities — Dapr Workflows вместо кастомной Lite backend?
50. [Data] RateLimiter/CircuitBreaker — pybreaker + limits если не ухудшит P95
51. [Infra] HTTP clients — унифицировать httpx + httpx-retries + hishel через общий фасад
52. [DSL] Result монада (result>=0.17.0) вместо разрозненных try/except в control-flow processors
```

### P3 — Observability / Testing

```
53. [Testing] ClickHouse audit batch — retry+DLQ (см. P0 #1)
54. [Testing] Run chaos suite на каждом PR touching services/entrypoints
55. [Testing] Make bandit/gitleaks blocking в security.yml (drop continue-on-error)
56. [Testing] Cosign attestation в sbom.yml:64
57. [Testing] ruff check --fix на 396 fixable violations
58. [Testing] tenant_id explicit label в 17 metrics infrastructure/observability/metrics.py
59. [Testing] Make audit_clickhouse_enabled=True в staging+prod профилях
60. [Testing] Layer-check CI gate на каждый PR (не только pre-prod)
```

### P4 — Dead code / cleanup

```
61. [DSL] Удалить dsl/engine/plugin_registry.py deprecation-shim
62. [DSL] DSL SchemaRegistry — либо singleton, либо удалить (vs активный ServiceSchemaRegistry)
63. [DSL] policy_mixin.idempotency() + control_flow.idempotent() — слияние
64. [Data] CDC cursor S178 fix — migration path для старых persisted cursors
65. [Config] [project] version 0.20.0 → 0.21.0 (sync с roadmap)
66. [Config] Constants.py docstring — обновить "7 re-exports" → "9 re-exports"
```

---

## Verification methodology note

> **Методологическая честность**: 11 subagent'ов с чистым контекстом читали
> **только файлы своего домена**, не получали трансляции из предыдущих сессий.
> Каждая находка имеет конкретный file:line evidence. Объём проверенного
> кода — 4141 Python-файлов, ~324K LOC, в зависимости от домена (5-15 ключевых
> файлов на агента + смежные).
>
> **Что НЕ проверено в этой сессии** (явные ограничения):
> - Полный прогон test suite — pytest собирает 13,609 тестов, но unit suite
>   падает на ~58% с collection errors (`polars` missing) + каскадные failures.
>   Реальный pass-rate не измерен.
> - mypy/ruff в полном окружении — единичный прогон mypy даёт 0 errors,
>   ruff — 620 violations. Не воспроизводимо без `uv sync`.
> - pre_prod_check.py — 38 gates, но ~12 — no-op stubs (`_check_warning`).
>   Реальное прохождение 38/38 не подтверждено.
> - Sandbox/Workflow/Banking — runtime поведение под нагрузкой не измерено.
>
> **Главный урок этой сессии**: большая часть «OPEN» находок из предыдущих
> отчётов уже устранена в коде (S171–S176 циклы были эффективны по части
> security/CDC/plugins), но одновременно обнаружены новые классы проблем,
> которых не было в предыдущих обзорах: ClickHouse audit без DLQ, Workflow
> compensation worker отсутствует, multi-agent supervisor — loop вместо LLM,
> layer-check FAIL с новыми нарушениями. Документация и код расходятся —
> нужен CI-шаг, сверяющий KNOWN_ISSUES.md с реальным выводом check_layers.py/
> mypy/ruff при каждом PR.

---

## Files touched

- Создан: `docs/compose/reports/2026-08-05-multi-agent-domain-audit.md` (этот файл)

## Findings worth promoting

- **Структурный паттерн "scaffold without behavior"**: WorkerVersioningHelper,
  FlagsmithProvider, OpenFeature external provider — код есть, но default
  отключает поведение. Это класс ошибок, который audit должен явно искать.
- **Дрейф документации от кода**: 6+ источников противоречивой информации о
  состоянии проекта (KNOWN_ISSUES.md, PLAN.md, pyproject version, validator
  defaults, feature-flags). Нужен единый source of truth + CI-сверка.
- **Middleware ordering как системная проблема**: DataMasking до Auth, PII
  duplicate, double-masking — все 3 проблемы одного класса (порядок vs
  дублирование). Code review должен фокусироваться на ordering, не только
  на presence.
- **Cycle 33 retro-pattern**: находки помечаются "CLOSED", но код это не
  подтверждает (CDC, SecurityHeaders, hot_swap) — затем всплывают заново.
  Регрессионные тесты обязательны для каждого "CLOSED" пункта.