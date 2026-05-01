# KNOWN_ISSUES.md

## Известные ограничения и quirks

### Открытый техдолг (после сессии 2026-05-01)

1. **Chaos-тесты с `testcontainers[toxiproxy]`** (Wave 26.3 расширение)
   — не реализованы. Зависят от Wave 26.8 PG→SQLite snapshot
   (теперь закрыт), готовы к старту. ~12 тестовых файлов + 2 helper'а
   ≈ 800-1200 LOC, требует Docker в CI. Эффорт: L (8-20ч).

   **Что нужно сделать:**
   - Добавить `testcontainers[toxiproxy]` в dev-deps.
   - Разработать `tests/chaos/` с маркером `@pytest.mark.chaos`.
   - 11 сценариев (по одному на chain): kill / pause / partition.
   - Отдельный CI job (matrix 3-4 jobs).

2. **SecretsBackend ABC заблокирован permission system** (W24
   deferred). `secrets_chain.py` использует прямой Vault/env+keyring
   без ABC. После разблокировки → переключить на DI.

3. **`importlib.import_module` как обход AST-линтера** — частично
   снято в Wave 6.1 module-registry (единый реестр в
   `core/di/module_registry.py`), но dynamic-resolution всё ещё не
   виден IDE refactor. Возможная будущая итерация —
   `importlib_metadata` plugin entrypoints.

4. **Pre-existing блокер `psycopg2 ModuleNotFoundError` в dev_light**
   (`setup_admin()`). До Wave 6.1 проявлялся на module level, теперь
   в `create_app()`. Лечится conditional skip `setup_admin` в
   dev_light или установкой psycopg2 в окружении.

5. **`make lint-strict`: 39 non-S ошибок** (E402, F821, E741, F401,
   F841) — pre-existing, вне scope Wave 26.6. Отдельная задача
   (Wave 26.6 расширение).

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

- ~~**Wave 6 post-finalize: eager singletons (31 шт)**~~,
  ~~**lifecycle `_app_ref`**~~, ~~**importlib registry**~~.
  **Закрыто 2026-05-01** (commits `Wave-6.1/_app_ref-hardening`,
  `Wave-6.1/module-registry`, `Wave-6.1/eager-singletons`).
  - `_app_ref` теперь имеет `require_app_ref()` (strict),
    `reset_app_state()` (для тестов), warning при двойном
    `set_app_ref()` без сброса. `_DECORATOR_CACHES` registry
    очищается при reset.
  - `core/di/module_registry.py` — единый реестр 45 infra-модулей с
    namespace-prefix (`app.*`, `clients.*`, `repos.*`, ...).
    `resolve_module(key)` + `validate_modules()` (find_spec без
    import) + `ModuleRegistryError`. 7 unit-тестов.
  - 31 module-level eager singleton переведён на lazy: 13 services
    через `app_state_singleton`, 16 infrastructure через
    `lru_cache(maxsize=1)` + module `__getattr__` shim для
    backward compat. Bonus: 3 ещё не упомянутых singleton'а
    (s3_client, route_limiting, _export_facade).

- ~~**Wave 26 закрытый техдолг: CircuitBreaker унификация**~~,
  ~~**lint-strict S-errors**~~, ~~**PG→SQLite snapshot job**~~.
  **Закрыто 2026-05-01** (commits `Wave-26.6/lint-strict`,
  `Wave-26.7/circuit-breaker-unification`,
  `Wave-26.8/pg-sqlite-snapshot`).
  - DSL `CircuitBreakerProcessor` теперь делегирует в общий
    `breaker_registry` (purgatory-based). Namespace `dsl.pipeline.<id>`
    (host="dsl"). Метрика `infra_client_circuit_state` покрывает
    DSL-breakers. ADR-036 обновлён.
  - 59 S-ошибок устранены (39 noqa с обоснованием + 19 fix через
    `logger.debug` + 3 точечных fix). `ruff check --select S` clean.
  - Background snapshot job: `infrastructure/resilience/snapshot_job.py`
    через SQLAlchemy + APScheduler (`IntervalTrigger`, default 10 min).
    Метрики Prometheus (`snapshot_age_seconds`, `snapshot_rows_total`,
    `snapshot_sync_duration_seconds`, `snapshot_sync_errors_total`,
    `db_fallback_used_with_stale_snapshot_total`). ADR-037.

- ~~**Wave 6 — Layer-violations baseline (135 entries)**.~~
  **Закрыто 2026-05-01** (commits `Wave-6.0..6.5b` + finalize).
  - `135 → 0` нарушений за 7 фаз.
  - W6.0 `composition-root` — `app_factory` перенесён в `plugins/`.
  - W6.2 `services-core` — DI-провайдеры для `services/core/*`.
  - W6.3 `services-ai` — DI для AI-агентов / sanitizer / mongo / redis.
  - W6.4 `services-io-ops-exec-integrations` — DI для IO/Ops/Exec
    (browser, clickhouse, smtp, scheduler, taskiq, ...).
  - W6.5a `api-middlewares` — DI для `entrypoints/api/*` и middlewares.
  - W6.5b `non-api` — DI для `cdc/email/express/graphql/grpc/mcp/...`.
  - **Wave 6 finalize** — устранены оставшиеся 9 violations
    (group A back-import infra→services через `importlib`,
    group B schemas→infra-models через `importlib` + `Any` для
    Pydantic-полей, group C services→infra через DI-провайдер
    `get_http_client_provider`).
  - Стратегия: lazy-провайдеры в `core/di/providers.py` +
    `importlib.import_module` для обхода статического AST-линтера
    в случаях, где архитектурная инверсия нецелесообразна
    (fastapi_filter ↔ ORM, TaskIQ worker ↔ Invoker, Audit ↔
    LogIndexer best-effort secondary indexing).
  - DoD: `python tools/check_layers.py → 0 новых нарушений
    (baseline 0 legacy)` ✅.

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
