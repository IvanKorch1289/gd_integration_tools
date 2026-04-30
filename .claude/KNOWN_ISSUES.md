# KNOWN_ISSUES.md

## Известные ограничения и quirks

### Wave 26 (Resilient Infrastructure) — открытый техдолг

1. **Chaos-тесты с `testcontainers[toxiproxy]` не реализованы** (W26.3
   расширение). Smoke-тесты coordinator есть, но автоматических
   сценариев «kill primary → 200 через fallback» для каждого из 11
   chain'ов — нет.

   **Что нужно сделать:**
   - Добавить `testcontainers[toxiproxy]` в dev-deps.
   - Разработать `tests/chaos/` с маркером `@pytest.mark.chaos`.
   - 11 сценариев (по одному на chain): kill / pause / partition.
   - Отдельный CI job (matrix 3-4 jobs).

2. **DSL `CircuitBreakerProcessor` ↔ infra `BreakerRegistry`** — два
   независимых state-machine. Раздельные метрики, нет агрегации.
   Унификация: либо DSL делегирует в `breaker_registry`, либо явно
   разделяется namespace (`pipeline_circuit_state` vs
   `infra_client_circuit_state`). Документировано в ADR-036, отложено
   в W27+.

3. **Real background snapshot job для PG → SQLite не реализован**.
   `database_chain.py::_sqlite_ro_query` ожидает уже существующий
   `var/db/snapshot.sqlite`. Без incremental-sync fallback вернёт
   stale-данные. Потребуется: cron-job c `pgcopydb` или ручная
   `metadata.create_all(sqlite_engine)` + INSERT-на-старте.

4. **SecretsBackend ABC заблокирован permission system** (W24
   deferred). `secrets_chain.py` использует прямой Vault/env+keyring
   без ABC. После разблокировки → переключить на DI.

5. **`make lint-strict` показывает 91 pre-existing ошибку** (S608
   SQL injection в legacy-коде, S603/S606 в `manage.py`). Не вносить
   новые S-ошибки в W26.

### Закрытые техдолги Wave 26

- ~~**Миграция 65 legacy-endpoints на DSL** (W26.5).~~
  **Закрыто 2026-05-01** (commits `Wave-26.5/1..14` + docs).
  - 14/14 endpoint-файлов мигрированы (`notebooks → ai_feedback →
    tech → rag → admin_connectors → search → ai_tools → invocations
    → admin_workflows → dsl_routes → imports → admin →
    processors_catalog → dsl_console`).
  - `health.py` оставлен как raw HTTP по плану (K8s-пробы).
  - Стратегия: `ActionRouterBuilder + ActionSpec` для большинства,
    `router.add_api_route` для UploadFile/Form/text-plain/Depends.
  - DoD: `grep -E "^@router\.(get|post|put|delete|patch)"
    src/entrypoints/api/v1/endpoints/ | grep -v health.py → 0` ✅.

- ~~**Vault недоступен в dev-окружении** — Settings-loader выводит
  ошибку при каждом запуске Python (16 раз).~~
  **Закрыто 2026-04-30** (commit `7c639d3 post-W26-techdebt+W6.1`).
  Module-level флаг `_VAULT_UNREACHABLE` + один warning через
  `RequestException`/`VaultError`-handlers. Было 30+ ошибок на
  запуск, стало 1 warning.

- ~~**Pre-existing синтаксис `except TypeError, ValueError:`**
  в `health_aggregator.py:101`.~~
  **Закрыто 2026-04-30** (commit `7c639d3 post-W26-techdebt+W6.1`).
  Заменено на `except (TypeError, ValueError):` для совместимости
  с конвенциями Python 3.x.

- ~~**Broken `InvokeMode` import** (Wave-22-техдолг).~~
  **Закрыто 2026-04-30** (commit `e8f089d`). Pre-existing pre-W26
  bug: `src/entrypoints/api/generator/reflection.py:10` импортировал
  `InvokeMode` из `src.schemas.invocation`, но при W22-рефакторе
  символ туда не попал. `make routes/actions` через `manage.py` не
  светил баг, но любой `include_router` падал ImportError. Закрыто
  реэкспортом `InvokeMode` из `core.enums.invocation`.

- ~~**W6.1 — Очистить allowlist (4 stale записи)**.~~
  **Закрыто 2026-04-30** (commit `7c639d3`). 135 entries
  актуализировано: 2 stale удалены, 3 design-нарушения W26
  (`health.py`/`degradation.py` → `infrastructure.resilience.*`)
  зафиксированы по ADR-036.

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
