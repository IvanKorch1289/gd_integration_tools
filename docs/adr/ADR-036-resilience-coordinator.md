# ADR-036: ResilienceCoordinator + Per-Service Fallback Chains

- **Статус:** accepted
- **Дата:** 2026-04-30
- **Фаза:** Wave-W26 (Resilient Infrastructure)
- **Автор:** Claude (по согласованию с заказчиком)

## Контекст

Wave 26 ставит цели:

1. Каждая внешняя зависимость защищена circuit breaker'ом и имеет fallback-chain.
2. Health-check matrix покрывает 11 канонических компонентов: db_main /
   redis / minio / vault / clickhouse / mongodb / elasticsearch / kafka /
   clamav / smtp / express.
3. `/readiness` возвращает 200 при работающих fallback'ах
   (`degraded=true`), 503 — только при полном отказе.
4. Write-операции в degraded-режиме блокируются с HTTP 503 + `Retry-After`.
5. Вся инфраструктура — без техдолга, конфигурируется YAML-описанием.

В проекте уже были разрозненные resilience-механизмы:
`BreakerRegistry` (purgatory), `DegradationManager`, `RetryBudget`,
`Bulkhead`, `SelfHealer`, DSL-процессоры `CircuitBreakerProcessor` /
`FallbackChainProcessor`. Отсутствовала **единая точка координации**:
fallback-chain для каждого компонента, source-of-truth для health-
агрегатора, метрика per-component degradation.

## Рассмотренные варианты

- **Вариант А — Единый ResilienceManager (новый Gateway).** ABC в
  `core/interfaces/`, конкретный backend в `infrastructure/`. Все
  Gateway получают его через DI и делегируют resilience-обёртки.

  *Плюсы:* единая точка конфигурации, чистая архитектура.
  *Минусы:* лишний слой абстракции для одной реализации (Правило 13.4
  «нельзя делать Gateway на будущее»).

- **Вариант Б — Каждый Gateway получает свой circuit breaker внутри.**
  `CacheBackend`, `ObjectStorage` и др. оборачивают свои методы в
  `breaker_registry.guard()`; fallback-цепочки конфигурируются per-
  backend.

  *Плюсы:* локальная ответственность, проще дебаг.
  *Минусы:* дублирование, нет единой картины degradation.

- **Вариант В — Декоратор `@with_resilience` поверх services.**
  Применяется per-method; resilience «размазана» по services.

  *Плюсы:* минимум изменений Gateway.
  *Минусы:* сложно гарантировать покрытие, метрики разнородные.

## Решение

Принят **гибрид А+Б**:

- `ResilienceCoordinator` (`infrastructure/resilience/coordinator.py`) —
  **тонкий координатор без ABC** в `core/interfaces/`. Поверх
  существующих `BreakerRegistry` (purgatory) и `DegradationManager`.
  Singleton через `get_resilience_coordinator()`.
- Каждый компонент wire'ится через свой модуль
  `infrastructure/resilience/components/<x>_chain.py` (по одному
  доминирующему вызову на компонент: `audit_append`, `cache_get`,
  `db_query`, `mq_publish`, ...).
- YAML-описание `resilience.breakers` / `resilience.fallbacks` в
  `config_profiles/base.yml` — источник правды для threshold/ttl/chain.
- Метрика `app_degradation_mode{component}` (0=normal, 1=degraded,
  2=down) публикуется в Prometheus.
- `HealthAggregator` получает per-component health-checks из
  `coordinator.status()` (модуль `infrastructure/resilience/health.py`).
- `DegradationMiddleware` блокирует write-методы при `db_main` в
  fallback-режиме (HTTP 503 + Retry-After).

ABC в `core/interfaces/` намеренно НЕ создаётся: единственная
реализация, fallback-цепочки декларативны (YAML). При появлении 2-й
реализации — переедет в core с отдельным ADR (Правило 13.3).

## Последствия

### Положительные

- Единая источник правды для resilience: 11 компонентов в одном YAML-
  блоке, регистрация автоматическая в lifespan.
- Health-check matrix покрывает все 11 компонентов; deep-check показывает
  per-chain состояние (`breaker_state` / `last_used_backend` /
  `degradation`).
- Write-блокировка через middleware — single-point безопасной
  деградации без доработки каждого endpoint'а.
- Метрика `app_degradation_mode` доступна для Prometheus / Grafana
  алертов.
- Per-service breaker-профили (`threshold` / `ttl`) вместо глобальных
  констант — устраняет риск каскадных отказов на коротких spike'ах.

### Отрицательные

- ~~DSL `CircuitBreakerProcessor` (pipeline-level) и infra
  `BreakerRegistry` (client-level) — два независимых state-machine.
  Унификация — отдельная задача (W27+).~~ **Закрыто в Wave 26.7.**
  *Resolution:* DSL `CircuitBreakerProcessor` делегирует state-machine
  в shared `breaker_registry` (purgatory). Локальные `_state` /
  `_failure_count` / `_last_failure_time` / `asyncio.Lock` удалены;
  имя breaker'а — `dsl.pipeline.<route_id>` (host-label `dsl`),
  что разделяет namespace с infra-breaker'ами (`<client>@<host>`).
  Метрика `infra_client_circuit_state{client,host}` публикуется в
  Prometheus автоматически — DSL-breakers теперь видны в `/metrics` и
  доступны `HealthAggregator` через `breaker_registry.list_states()`.
- SecretsBackend ABC заблокирован permission system (W24 deferred);
  реализован обходной путь Vault → env+keyring без ABC. После
  разблокировки переключить на DI.
- Полная миграция 65 legacy-endpoints на DSL — в W26.5 закрыт только
  критический инфра-уровень (DegradationMiddleware); сама миграция —
  следующая итерация (см. KNOWN_ISSUES.md).
- W26 не вводит chaos-testing с testcontainers[toxiproxy] — это
  отложено: smoke-тестов достаточно для baseline, chaos — отдельная
  волна.

### Нейтральные

- Новых зависимостей не добавлено: используются `purgatory`,
  `tenacity`, `cachetools`, `aiosqlite`, `aiosmtplib` (все уже в
  pyproject).
- DSL apiVersion v3 не требуется — изменения чисто на уровне infra и
  entrypoints.

## Связанные ADR

- ADR-005 — Resilience patterns (foundation: purgatory, retry budget,
  bulkhead).
- ADR-022 — Connector SPI (health-check matrix, ConnectorRegistry).
- ADR-023 — Notification Gateway (fallback chain Email/SMS/Express).
- ADR-033 — Import Gateway.
- ADR-034 — DSL versioning (для контекста: W26 не меняет apiVersion).
