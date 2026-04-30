# Resilience (W26) — справочник

Wave 26 вводит унифицированный механизм circuit breaker'ов и
fallback-цепочек для 11 канонических компонентов (см. ADR-036).

## Архитектура

```
                ┌──────────────────────┐
                │  ResilienceCoordinator│
                ├──────────────────────┤
                │ register(component, …)│
                │ call(component, *)    │
                │ status() → dict       │
                └─────┬──────────┬──────┘
                      │          │
        ┌─────────────▼──┐   ┌──▼─────────────┐
        │ BreakerRegistry │   │ DegradationManager│
        │   (purgatory)   │   │ (graceful degrad.)│
        └─────────────────┘   └────────────────┘
```

* **Координатор** — `src/infrastructure/resilience/coordinator.py`.
* **Реестр компонентов** — `src/infrastructure/resilience/registration.py`
  (канонический список + wiring 11 компонентов).
* **Per-component wiring** — `src/infrastructure/resilience/components/
  <x>_chain.py` (по одному модулю на компонент).
* **Health-checks** — `src/infrastructure/resilience/health.py`.
* **Settings** — `src/core/config/services/resilience.py`.

## Канонические 11 компонентов

| Имя              | Primary backend            | Fallback chain                      |
|------------------|----------------------------|-------------------------------------|
| `db_main`        | PostgreSQL (asyncpg)       | `sqlite_ro` (read-only snapshot)    |
| `redis`          | Redis                      | `memcached` → `memory`              |
| `minio`          | MinIO/S3                   | `local_fs` (var/storage)            |
| `vault`          | HashiCorp Vault            | `env_keyring` (env + keyring)       |
| `clickhouse`     | ClickHouse                 | `pg_audit` → `jsonl`                |
| `mongodb`        | MongoDB (motor)            | `pg_jsonb` (app_doc_store table)    |
| `elasticsearch`  | Elasticsearch              | `sqlite_fts5` (var/db/search/)      |
| `kafka`          | Kafka (faststream)         | `redis_streams` → `memory_mq`       |
| `clamav`         | ClamAV unix/TCP            | `http_av` → `skip_warn`             |
| `smtp`           | SMTP (aiosmtplib)          | `file_mailer` (var/mail/outbox/)    |
| `express`        | Express BotX               | `smtp` → `slack`                    |

## YAML-конфигурация

Секция `resilience` в `config_profiles/base.yml`:

```yaml
resilience:
  breakers:
    db_main:        {threshold: 5, ttl: 30}
    redis:          {threshold: 5, ttl: 15}
    kafka:          {threshold: 3, ttl: 60}
    # ... остальные 8
  fallbacks:
    db_main:        {chain: ["sqlite_ro"],                  mode: auto}
    redis:          {chain: ["memcached", "memory"],        mode: auto}
    kafka:          {chain: ["redis_streams", "memory_mq"], mode: auto}
    # ... остальные 8
```

### Поля

* **`threshold`** — количество подряд идущих отказов до перехода
  breaker'а в `open` (по умолчанию `5`).
* **`ttl`** — секунды в `open` до перехода в `half-open` (по
  умолчанию `30.0`).
* **`exclude`** — qualified-имена исключений, не учитывающихся как
  failure (например, `4xx` HTTP).
* **`chain`** — упорядоченный список идентификаторов backend'ов,
  соответствующих `components/<x>_chain.py::build_*_fallbacks`.
* **`mode`** — `auto` (default) / `forced` (всегда fallback) / `off`
  (fallback выключен, отказ propagated).

### Глобальный override mode

```yaml
resilience:
  fallback_mode_override: "forced"   # для dev_light/chaos-тестов
```

При установке override — все 11 компонентов работают в указанном mode
вне зависимости от per-component настроек.

## Использование

### Регистрация при старте

`infrastructure/application/lifecycle.py::_bootstrap_resilience_coordinator`
автоматически:

1. Создаёт singleton `ResilienceCoordinator`.
2. Вызывает `register_all_components(coord, settings.resilience)` —
   wire'ит все 11 компонентов через свои `components/<x>_chain` модули.
3. Регистрирует health-checks через
   `register_resilience_health_checks(get_health_aggregator(), coord)`.

### Прямой вызов

```python
from src.infrastructure.resilience import get_resilience_coordinator

coord = get_resilience_coordinator()
result = await coord.call("db_main", sql="SELECT 1")
```

При OPEN-breaker'е coordinator прозрачно идёт по chain (`sqlite_ro`).

### Snapshot состояния

```python
from src.infrastructure.resilience import resilience_components_report

report = resilience_components_report()
# {
#   "db_main": {
#     "status": "ok",
#     "details": {
#       "breaker_state": "closed",
#       "fallback_mode": "auto",
#       "chain": ["sqlite_ro"],
#       "last_used_backend": "primary",
#       "degradation": "normal"
#     }
#   },
#   ...
# }
```

## Метрики (Prometheus)

* **`app_degradation_mode{component}`** — gauge per-component:
  * `0` = normal (primary, breaker closed),
  * `1` = degraded (fallback active),
  * `2` = down (все backend'ы исчерпаны).
* **`infra_client_circuit_state{client,host}`** — состояние breaker'а.

Алерты:

```promql
sum by (component) (app_degradation_mode > 0)
```

## HTTP endpoints

* **`GET /liveness`** — process-only, 200 пока процесс жив.
* **`GET /readiness`** — 200 при работающем сервисе (включая degraded);
  503 — только при наличии компонентов в `down`.
* **`GET /startup`** — 200 когда DSL-маршруты и actions
  зарегистрированы.
* **`GET /components?mode=fast|deep`** — детальный отчёт. `deep` плюс
  per-chain статус.

### Пример deep-отчёта

```json
{
  "status": "degraded",
  "components": { ... },
  "resilience_chains": {
    "db_main": {
      "status": "degraded",
      "details": {
        "breaker_state": "open",
        "chain": ["sqlite_ro"],
        "last_used_backend": "sqlite_ro",
        "degradation": "degraded"
      }
    }
  }
}
```

## DegradationMiddleware

`src/entrypoints/middlewares/degradation.py`. Блокирует write-методы
(POST/PUT/PATCH/DELETE) при `db_main` в fallback-режиме:

```http
HTTP/1.1 503 Service Unavailable
Retry-After: 30
X-Degradation-Mode: write-blocked

{
  "status": "degraded",
  "reason": "write blocked: components in fallback mode — db_main",
  "retry_after_seconds": 30
}
```

Bypass-prefix'ы (метрика, health, audit) определены в
`DEGRADATION_BYPASS_PREFIXES`.

## Guard-проверки

```bash
make readiness-check  # включает tools/check_fallback_matrix.py
```

Проверяет:

* все 11 компонентов из `RESILIENCE_COMPONENTS` присутствуют в
  `resilience.breakers` / `resilience.fallbacks`;
* нет «лишних» компонентов в YAML, не объявленных в коде;
* у каждого компонента непустая `chain`.

## Тестирование

Smoke-проверки фиксируются в `tests/unit/resilience/` (TBD); chaos-
тестирование с `testcontainers[toxiproxy]` — отдельная итерация (см.
KNOWN_ISSUES.md).

## Не вошло в W26 (откладывается)

1. **Полная миграция 65 legacy-endpoints на DSL** — закрыт только
   инфра-уровень (DegradationMiddleware). Требуется поэндпоинтный
   перенос на DSL routes/actions с сохранением auth/rate-limit/
   pagination/OpenAPI.
2. **Chaos-тесты с testcontainers[toxiproxy]** — структурированные
   сценарии «kill primary → 200 через fallback» для всех 11 chain'ов.
3. **Унификация DSL `CircuitBreakerProcessor` ↔ infra
   `BreakerRegistry`** — единая метрика `circuit_state` для pipeline-
   и client-уровня.
4. **Реальное background-job'ы для snapshot'а PG → SQLite** —
   incremental sync для актуальности fallback-данных.
5. **SecretsBackend ABC разблокировка** — после permission-fix
   переключить `secrets_chain` на DI вместо прямого env+keyring.

См. `.claude/KNOWN_ISSUES.md` (раздел W26).
