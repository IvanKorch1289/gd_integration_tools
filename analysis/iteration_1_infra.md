# Итерация 1: Инфраструктура

## 1.1 Docker и контейнеры — 7/10

**Плюсы:** Multi-stage, uv, non-root (uid 10001), tini, HEALTHCHECK, 6 compose-файлов, Helm с SecurityContext, NetworkPolicy, HPA, PDB.
**Минусы:** Дрифт UID (Dockerfile 10001 vs Helm 1000), worker в Helm без проб, job-migration без securityContext, raw K8s дублирует Helm, Windows-worker без checksum на Python installer, compose без resource limits.

## 1.2 DSL ↔ Инфраструктура — 5/10

**Плюсы:** ConnectorRegistry (ADR-022), InfrastructureClient ABC, фабрики БД/S3 с fallback.
**Минусы:** `InfrastructureDSL` — 11 мертвых stub-процессоров (redis_set, clickhouse_insert и др.). Прямые импорты `infrastructure.sinks.*` в процессоры. Sink'и (gRPC/SOAP/MQ/WS) создаются per-call — нет pooling. ConnectorRegistry не охватывает основные клиенты.

## 1.3 Устойчивость — 8/10

**Плюсы:** purgatory CB, 11 fallback-цепочек, RetryBudget, AdaptiveBulkhead, TimeLimiter, chaos tests (toxiproxy), SelfHealer, DegradationManager (5 уровней).
**Минусы:** Дублирование HTTP-клиентов (HttpClient + HttpxClient), нет per-tenant bulkhead, нет deadline propagation, SmartSessionManager CB — самописный, chaos-тесты smoke-level.

## 1.4 Скорость и performance — 6/10

**Плюсы:** HTTP/2 httpx, Redis pool tuning, SQLAlchemy pool_pre_ping.
**Минусы:** `pool_use_lifo` задан в конфиге, но не прокидывается в engine. Blocking I/O в `imports.py` (polars.read_excel без to_thread). `ThreadPoolExecutor(1)` на каждый вызов guardrails. MemoryBackend с глобальным `asyncio.Lock()`. HPA worker: дрифт на 2 порядка (10 vs 1000). `.benchmarks/` пустая, perf gate warn-only.

## 1.5 Healthcheck и observability — 6/10

**Плюсы:** HealthAggregator, WorkerProbesServer, Prometheus MetricsRegistry, OTel W3C, structlog+JSON, SLO burn-rate alerts, Grafana dashboards.
**Минусы:** K8s probes пути не совпадают с кодом (/health/ready vs /ready). ProcessorHealthService — stub. MetricsRegistry default_labels отключены. OTel только ingress, нет исходящих клиентов. Только 2 дашборда. Sentry без кастомного fingerprinting.

## Библиотеки из web search
- `pyresilience` — unified resilience (retry, CB, bulkhead, rate limit, cache) в одном декораторе
- `tenacity` — mature retry с exponential backoff + jitter
- `httpx-retries` + `hishel` — HTTP caching и retry transport
