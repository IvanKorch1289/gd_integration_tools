# ADR-032 — Observability Automation (OTEL middleware, body cache, Grafana, Prometheus alerts)

- **Статус:** Accepted
- **Дата:** 2026-04-22
- **Фаза:** IL-OBS1
- **Авторы:** implementation-agent (worktree `agent-a0bbfc1f`)

## Контекст

По результатам ревью middleware stack и observability-подсистемы зафиксированы
три разрыва, блокирующие production-доводку наблюдаемости:

1. **Нет FastAPI OTEL middleware.** OTEL tracer provider инициализируется в
   `src/infrastructure/observability/tracing.py` и оборачивает DSL-процессоры,
   но на уровне HTTP-слоя span формируется только через опциональный
   `FastAPIInstrumentor` (см. `otel_auto.py`). Если `OTEL_EXPORTER_OTLP_ENDPOINT`
   не сконфигурирован или instrumentor не установлен, HTTP-входы остаются
   неинструментированными. Нет распространения `traceparent` между hop-ами,
   нет привязки `tenant.id`, `correlation.id`, `app.route_id` к HTTP-span-у.
2. **Тело запроса читается трижды.** `InnerRequestLoggingMiddleware`,
   `AuditReplayMiddleware`, `AuditLogMiddleware` независимо вызывают
   `await request.body()`. Starlette кеширует буфер через `request._receive`,
   но каждый вызов всё равно копирует bytes и триггерит асинхронный вызов
   ASGI-receive. На типичном P95 ≤ 2 мс это overhead ~0.3–0.6 мс дополнительно.
3. **Нет готовых Grafana dashboard + Prometheus alert rules в `deploy/`.**
   Текущий dashboard (`docs/grafana/dsl_dashboard.json`) ориентирован на DSL,
   но нет отдельного `Infrastructure Health` представления для
   `infra_client_*`-метрик из фазы IL1.2; alert rules находятся в
   `docs/alerts/slo_burn_rate.yml`, но не являются «infrastructure»-набором
   (circuit, pool saturation, latency P99, error rate) и не лежат в
   каноническом `deploy/prometheus/alerts/`.

## Решение

Ввести четыре артефакта + одну декомпозицию middleware:

### 1. `OtelMiddleware` — `src/entrypoints/middlewares/otel_middleware.py`

Явный FastAPI `BaseHTTPMiddleware`, который:

- Получает `tracer` через `get_tracer()` из `tracing.py`
  (переиспользуется глобальный provider из `otel_auto.py`).
- Извлекает `traceparent` из входящих заголовков, восстанавливает
  контекст через `TraceContextTextMapPropagator`.
- Создаёт span `http.{METHOD} {path}` с атрибутами:
  - `http.method`, `http.url`, `http.route`, `http.status_code`,
    `http.user_agent`, `http.client_ip`;
  - `app.tenant_id` (из `X-Tenant-ID` или `current_tenant()`);
  - `correlation.id` / `request.id` (из `request.state`);
  - `app.route_id` (если есть у DSL match).
- Инжектирует обновлённый `traceparent` в response-заголовки — downstream hops
  видят единый trace.
- Полностью защищён `try/except ImportError` — если OTEL отсутствует,
  middleware работает как no-op, не ломая pipeline.

Добавляется в **слой 4** `setup_middlewares.py`, **после**
`InnerRequestLoggingMiddleware`, **перед** `PrometheusMiddleware`.

### 2. `RequestBodyCacheMiddleware` — `src/entrypoints/middlewares/request_body_cache.py`

Однократное чтение тела запроса с кешем в `request.state.body`:

- Читает `await request.body()` один раз, сохраняет `bytes` (≤ `max_body_size`).
- Переопределяет `request._receive` замыканием, возвращающим cached body на
  последующих read-ах — это делает кеш прозрачным для endpoint-handler-ов и
  downstream middleware, даже если они напрямую вызывают `await request.body()`.
- Safety limit `max_body_size = 10 МБ` — при превышении кеш не сохраняется,
  downstream вынуждены читать потоком (не ломается контракт).

Добавляется в **слой 2** `setup_middlewares.py`, сразу **после**
`RequestIDMiddleware`. Middleware `AuditLogMiddleware`, `AuditReplayMiddleware`,
`InnerRequestLoggingMiddleware` обновлены чтобы сначала проверять
`request.state.body`, и если его нет — падать на fallback `await request.body()`
(graceful degradation, backward-compatible).

### 3. `deploy/grafana/dashboards/infrastructure_health.json`

Готовый для импорта Grafana dashboard (schemaVersion 36, Grafana 8+). Панели:

| # | Title | Type | Основная метрика |
|---|---|---|---|
| 1 | Client Pool Saturation | timeseries | `infra_client_pool_size{state="active"} / infra_client_pool_size{state="max"}` |
| 2 | Circuit Breaker State | stat | `infra_client_circuit_state` (0/1/2) |
| 3 | Client Request Latency P50/P95/P99 | timeseries | `histogram_quantile(..., rate(infra_client_request_duration_seconds_bucket[5m]))` |
| 4 | Request Rate by Outcome | timeseries | `sum by (outcome) (rate(infra_client_requests_total[1m]))` |
| 5 | Reconnection Attempts | timeseries | `rate(infra_client_reconnect_attempts_total[5m])` |
| 6 | DSL Pipeline Error Rate | stat | `100 * sum(rate(dsl_pipeline_execution_total{status="error"}[5m])) / sum(rate(dsl_pipeline_execution_total[5m]))` |

Метрики `infra_client_*` добавляются в фазе IL1.2; dashboard ссылается на них
вперёд (если Prometheus ещё не собирает их — панель покажет «No data», это
нормально).

### 4. `deploy/prometheus/alerts/infrastructure.yml`

Alert rules (Alertmanager format) для группы `infrastructure`:

- `ClientCircuitOpen` (critical, 1m)
- `ClientPoolSaturated` (warning, 5m)
- `HighClientErrorRate` (warning, 5m)
- `ClientLatencyP99High` (warning, 10m)
- `ClientReconnectStorm` (warning, 5m)
- `DslPipelineErrorBudgetBurn` (critical, 15m) — 2x burn rate
- `ConnectionPoolExhausted` (critical, 2m)

Все rules ссылаются на `infra_client_*` (будущие) + существующие
`dsl_*` / `connection_pool_utilization` метрики.

## Последствия

### Положительные

- Полное auto-tracing HTTP-запросов без необходимости ручной инструментации.
- Прозрачное распространение `traceparent` — distributed tracing работает в
  связке с `HTTPXClientInstrumentor` (уже активен из `otel_auto.py`).
- Однократное чтение тела запроса — средне-низкий выигрыш на P95 (~0.3 мс),
  но заметный выигрыш на `request.body()` в endpoint-handler-ах (больше не
  читается заново).
- Grafana dashboard + alerts сразу importable в prod-окружение клиента,
  без ручной сборки YAML/JSON.

### Отрицательные / риски

- Дополнительный middleware-hop → +1 `await` на запрос. Замеряется в
  `dsl_pipeline` latency histogram — при деградации P99 будет видно.
- Риск cardinality explosion по атрибутам OTEL-span-а (`app.tenant_id`,
  `app.route_id`). Митигация: `tenant_id` уже label bounded в метриках IL1.2,
  `route_id` — конечный set из `RouteRegistry`.
- `RequestBodyCacheMiddleware` увеличивает пиковую память: на 10 МБ body ×
  `max_concurrent_requests` в худшем случае. При проблемах — снизить
  `max_body_size` через env.
- Kернел `_receive` замыкания — starlette/FastAPI-specific API. При
  мажорном обновлении Starlette (sans-io rewrite) потребуется актуализация.

## Definition of Done

- [x] `docs/adr/ADR-032-observability-automation.md` создан.
- [x] `src/entrypoints/middlewares/otel_middleware.py` добавлен.
- [x] `src/entrypoints/middlewares/request_body_cache.py` добавлен.
- [x] `src/entrypoints/middlewares/setup_middlewares.py` обновлён: слои 2 и 4.
- [x] `audit_log.py`, `audit_replay.py`, `request_log.py` читают
  `request.state.body` first.
- [x] `deploy/grafana/dashboards/infrastructure_health.json` создан
  (≥ 6 панелей, Grafana 8+).
- [x] `deploy/prometheus/alerts/infrastructure.yml` создан (≥ 5 alert rules).
- [x] Все Python-файлы проходят `ast.parse` (syntax ok).
- [x] JSON / YAML валидны (`json.load` / `yaml.safe_load`).
- [x] Коммит с префиксом `[phase:IL-OBS1]`.

## Ссылки

- ADR-001 (DSL central abstraction).
- IL1.2 (infra metrics — `infra_client_*`).
- `src/infrastructure/observability/tracing.py`, `otel_auto.py`, `metrics.py`.
- `docs/grafana/dsl_dashboard.json`, `docs/alerts/slo_burn_rate.yml` —
  не заменяются, дополняются.
