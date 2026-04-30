# KNOWN_ISSUES.md

## Известные ограничения и quirks

### Wave 26 (Resilient Infrastructure) — техдолг

1. **Миграция 65 legacy-endpoints на DSL не завершена** (W26.5).
   Закрыта только критическая инфраструктура: `DegradationMiddleware`,
   которая возвращает HTTP 503 на write-методы при `db_main` в
   fallback-режиме. Сами endpoints в `src/entrypoints/api/v1/endpoints/`
   (15 файлов, ~65 endpoints) пока не перенесены на DSL routes/actions.

   **Что нужно сделать:**
   - По 1-2 файлов за commit: notebooks → ai_feedback → tech → rag →
     admin_connectors → search → ai_tools → invocations → admin_workflows
     → dsl_routes (доработка) → imports → admin → processors_catalog →
     dsl_console.
   - `health.py` НЕ переносится (K8s-пробы должны быть raw HTTP).
   - Для каждого endpoint'а сохранить auth (`Depends`), rate-limit
     (`RedisRateLimiter`), pagination (`Page[T]`), OpenAPI metadata.
   - Snapshot-тесты `/openapi.json` до/после миграции.
   - Финальный DoD: `grep "@router\.\(get\|post\)" src/entrypoints/api/v1/
     endpoints/ | grep -v health.py → 0`.

2. **Chaos-тесты с `testcontainers[toxiproxy]` не реализованы** (W26.3
   расширение). Smoke-тесты coordinator есть, но автоматических
   сценариев «kill primary → 200 через fallback» для каждого из 11
   chain'ов — нет.

   **Что нужно сделать:**
   - Добавить `testcontainers[toxiproxy]` в dev-deps.
   - Разработать `tests/chaos/` с маркером `@pytest.mark.chaos`.
   - 11 сценариев (по одному на chain): kill / pause / partition.
   - Отдельный CI job (matrix 3-4 jobs).

3. **DSL `CircuitBreakerProcessor` ↔ infra `BreakerRegistry`** — два
   независимых state-machine. Раздельные метрики, нет агрегации.
   Унификация: либо DSL делегирует в `breaker_registry`, либо явно
   разделяется namespace (`pipeline_circuit_state` vs
   `infra_client_circuit_state`).

4. **Real background snapshot job для PG → SQLite не реализован**.
   `database_chain.py::_sqlite_ro_query` ожидает уже существующий
   `var/db/snapshot.sqlite`. Без incremental-sync fallback вернёт
   stale-данные. Потребуется: cron-job c `pgcopydb` или ручная
   `metadata.create_all(sqlite_engine)` + INSERT-на-старте.

5. **SecretsBackend ABC заблокирован permission system** (W24
   deferred). `secrets_chain.py` использует прямой Vault/env+keyring
   без ABC. После разблокировки → переключить на DI.

6. ~~**Vault недоступен в dev-окружении** — Settings-loader выводит
   ошибку при каждом запуске Python (16 раз). Pre-existing с момента
   введения VaultConfigSettingsSource. Не блокирует функционал, но
   шумит в логах.~~ **Закрыто (post-W26-techdebt)**: добавлен module-
   level флаг `_VAULT_UNREACHABLE` + один warning через `RequestException`/
   `VaultError`-handlers вместо логирования каждой попытки.

7. **`make lint-strict` показывает 91 pre-existing ошибку** (S608
   SQL injection в legacy-коде, S603/S606 в `manage.py`). Не вносить
   новые S-ошибки в W26.

8. ~~**Pre-existing синтаксис `except TypeError, ValueError:`** в
   `health_aggregator.py:101`.~~ **Закрыто (post-W26-techdebt)**: заменено
   на `except (TypeError, ValueError):` для совместимости с конвенциями
   Python 3.x (хотя Python 3.14 парсер семантически принимает оба).

## Технические особенности

- `ResilienceCoordinator` — singleton, не пере-init'ится в тестах.
  Используй `set_resilience_coordinator(None)` для очистки между
  тестами.
- `DegradationMiddleware` блокирует только writes к `db_main`. Если
  потребуется блокировать writes для других компонентов (например,
  Vault при secret-injection) — расширить `_check_blocked_components`.
- `tools/check_fallback_matrix.py` запускается в `make readiness-check`
  и проверяет консистентность `RESILIENCE_COMPONENTS` ↔ `base.yml`.

## Что проверять вручную

- При добавлении нового компонента в `RESILIENCE_COMPONENTS`:
  1. обновить `config_profiles/base.yml` (breakers + fallbacks);
  2. создать `infrastructure/resilience/components/<x>_chain.py`;
  3. зарегистрировать в `_REGISTRARS` в `registration.py`;
  4. прогнать `tools/check_fallback_matrix.py`.
- При деплое в prod: убедиться, что Prometheus собирает метрику
  `app_degradation_mode{component=...}` и в Grafana есть alert по
  `> 0`.
