# FUNCTIONAL_SMOKE_2026-10-29 — функциональный smoke стенда dev_light

Дата: 2026-10-29 (выполнено 2026-11-02 после регресса задачи)
Стенды: **A** — контейнер `gd-app-light` (`docker-compose.light.yml`, образ `gd-integration-tools:light` от 18.08 + hotfix-патчи),
**B** — локальный `APP_PROFILE=dev_light APP_PORT=8010 .venv/bin/python manage.py run` (актуальный код репозитория).

## 1. Воспроизведённые дефекты (до фикса)

| # | Дефект | Где | Симптом |
|---|---|---|---|
| D1 | Недоступный файловый лог убивал приложение | `logging_service.py:169` (и `structlog_backend.py:318`) | `PermissionError: [Errno 13] '/app/.run/logs/dev_light.log'` → **все** HTTP-эндпоинты 500 |
| D2 | Healthcheck врал | `docker-compose.light.yml` | TCP-connect → контейнер «healthy» при падающем приложении |
| D3 | Права bind-mount `../../.run` (uid 1000) vs процесс uid 10001 | compose | лог недоступен → D1 |
| D4 | S3 не сконфигурирован, но помечался `error` | `setup_infra/health.py:139` | `/health/ready` → 503 `{"status":"down", "s3":{"status":"error", ... "NoSuch API S3"}}` |
| D5 | Redis: результат `ping()` игнорировался | `setup_infra/health.py:94` | недоступный Redis → «ok» (ложь в другую сторону) |
| D6 | NATS: хардкод `localhost:4222` | `setup_infra/health.py:201` | NATS не в профиле → `error` → readiness «down» |
| D7 | DI-Provider резолвил несуществующие атрибуты | `core/di/providers/workflow/_workflow_core.py` | `GET /api/v1/admin/workflows` → **500** (`get_main_session`, `WorkflowStateRow`) |
| D8 | `docker compose` не запускается на хосте | `.env:92` | `unexpected character "─" in variable name` (docker compose v5.6.1) — **не чинил** (`.env` не читаю) |

## 2. Что исправлено (file:line → почему)

| Файл:строка | Правка | Почему |
|---|---|---|
| `src/backend/infrastructure/external_apis/logging_service.py:169-201` | `_create_file_handler()`: `OSError` → warning + `logging.NullHandler()` | Файл лога недоступен — не повод ронять процесс; консольное логирование продолжает работать (D1) |
| `src/backend/infrastructure/logging/structlog_backend.py:312-338` | тот же guard в новом (structlog) бэкенде | Тот же дефект в primary-бэкенде: без фикса `init_application_logging` падал → приложение жило «на lazy defaults» без логов (D1) |
| `src/backend/plugins/composition/setup_infra/health.py:139-145` | S3 → `{"status":"skipped"}` при `fs.enabled=false`/`provider=local` | Отключённый опциональный компонент = `skipped`, как redis/queue/kafka (D4) |
| `src/backend/plugins/composition/setup_infra/health.py:94-104` | Redis → `skipped` при `redis.enabled=false`; `ping()==False` → `error` | Убрана ложь «ok» при мёртвом Redis (D5) |
| `src/backend/plugins/composition/setup_infra/health.py:44-70, 200-203` | NATS: endpoint из настроек профиля; не настроен → `skipped` | Хардкод `localhost:4222` делал readiness вечно «down» (D6) |
| `src/backend/core/di/providers/workflow/_workflow_core.py:107-127` | `module.get_main_session` → `module.get_main_session_manager()`; `module.WorkflowStateRow` → `module.WorkflowInstanceRow` | Оба атрибута не существуют → `AttributeError` → 500 в `GET /api/v1/admin/workflows` (D7) |
| `ops/compose/docker-compose.light.yml:57-64` | healthcheck → HTTP `GET /health/live` (urllib, код 200) | TCP-check проходил на мёртвом приложении (D2) |
| `ops/compose/docker-compose.light.yml:52-53, 94-95, 141-142` | `group_add: ["${DOCKER_GID:-1000}"]` для сервисов с `../../.run` | Безопасный вариант: UID образа (10001) сохраняется, `/app` (0750 appuser) остаётся читаемым; в supplementary-группу хоста попадает gid 1000 → файлы 0664 (gid 1000) writable (D3) |

**Почему не `user: "${DOCKER_UID:-1000}:${DOCKER_GID:-1000}"`** (вариант из ТЗ): проверено эмпирически —
`docker run --user 1000:1000` → `ModuleNotFoundError: No module named 'src'` (`/app` = `drwxr-x--- appuser:appuser`, uid≠10001 не читает код) и `Permission denied` на лог. Процесс root'ом не становится, но образ перестаёт работать. `group_add` решает задачу без смены владельца кода.

## 3. Smoke-результаты

### Стенд B — локальный, актуальный код репозитория (:8010)

| Эндпоинт | Код | Вывод / причина |
|---|---|---|
| GET `/health/live` | **200** | `{"status":"alive","version":"0.1.0"}` |
| GET `/health/ready` | **200** | `{"status":"ok"}`; redis/s3/kafka/nats → `skipped`, database → `ok`, errors: 0 (было 503 «down») |
| GET `/metrics` | **200** | prometheus-экспорт |
| GET `/docs` | **200** | Swagger UI |
| POST `/api/v1/auth/login` (без кредов) | **401** | `step_up_token_required` — 4xx, не 500 |
| GET `/api/v1/admin/config` (без токена) | **401** | `Authentication required` |
| GET `/api/v1/admin/workflows` (без токена) | **401** | `Authentication required` |
| POST `/api/v1/admin/workflows/trigger/nonexistent-workflow` (без токена) | **401** | не 500 |
| POST `/api/v1/auto/admin.get_config` (без токена) | **401** | не отдаёт `settings.model_dump()` |
| POST `/api/v1/invocations` (без токена) | **401** | не 500 |
| GET `/api/v1/admin/config` (admin) | **200** | конфиг; секреты замаскированы: `secure.secret_key=**********`, `vault.token=***`, `database.password=***` (44 secret-like поля: 21 masked, 23 — несекретные: таймауты, флаги, пути) |
| GET `/api/v1/admin/workflows` (admin) | **200** | `[]` — **было 500**, исправлено (D7) |
| POST `/api/v1/admin/workflows/trigger/nonexistent-workflow` (admin) | **404** | `Workflow 'nonexistent-workflow' not registered` — не 500 |
| POST `/api/v1/auto/admin.get_config` (admin, `{}`) | **200** | конфиг с маскированием |
| POST `/api/v1/auto/admin.get_config` (обычный user) | **403** | `action_permission_denied`, required `role:admin`, дамп конфига **не отдан** (E ✓) |
| POST `/api/v1/invocations` (обычный user, `action=admin.get_config`) | **403** | `action_permission_denied` (E ✓) |
| POST `/api/v1/invocations` (admin) | **200** | `status=error` («Action not registered»), не 500 |

### Стенд A — контейнер `gd-app-light` (:8000)

| Эндпоинт | Код | Вывод / причина |
|---|---|---|
| GET `/health/live` | **200** | контейнер `healthy` (healthcheck теперь HTTP) |
| GET `/health/ready` | **200** | `null` — дефект **старого образа** (`app_factory.py` без `return`), в репозитории исправлено; пересборка невозможна (нет PyPI) |
| GET `/metrics`, GET `/docs`, GET `/api/v1/auth/methods` | **200** | — |
| POST `/api/v1/auth/login` | **401** | в старом образе `/api/v1/auth/login` не в public-allowlist (исправлено в репо 2026-09-09) |
| GET `/api/v1/admin/config`, `/api/v1/admin/workflows` | **401** | — |
| POST `/api/v1/admin/workflows/trigger/...` | **403** | `csrf_token_missing` |
| POST `/api/v1/auto/admin.get_config`, `/api/v1/invocations` | **403** | `csrf_token_missing`, дамп конфига не отдан (E ✓) |
| контейнер `gd-grpc-light` | **healthy** | до фикса — crash-loop с тем же `PermissionError` |
| контейнер `gd-worker-light` | **healthy** | — |

## 4. Что осталось неработающим (после фиксов 2026-11-02)

Требуют владельца (в этой волне НЕ правились):

1. **D8 `.env:92`** — `docker compose` (v5.6.1) падает на парсинге `.env` (строка-разделитель без `#`). Обход в стенде: sanitized-копия + `--env-file` + override с `env_file: !override`. Само `.env` не трогал (запрещено).
2. **Образ от 18.08 отстаёт на 5 недель** — в контейнере не работают: `return` в `/health/ready`, public-allowlist логина, волна-25 авторизация. Пересборка невозможна (нет сети к PyPI) → валидация актуального кода выполнена на локальном стенде.

Закрыто в волне 2026-11-02 (см. §6): auto-тело → 422, маскирование
`express`/`telegram`-секретов, audit-replay без Redis, worker на SQLite.

Известное расхождение (не в скоуп фикса, требует решения владельца):
writer audit-потока (`AuditReplayMiddleware`) пишет в `audit:requests`,
а reader (`services/audit/replay_query.py` + `GET /api/v1/audit/capability`)
читает `audit:events` — канон задан ADR-0281 и docstring'ом endpoint'а.
Имена потоков не унифицированы (правка потребовала бы изменения
существующих тестов).

## 5. Что обновить (ADR / gaps)

- `docs/roadmap/PROD_READINESS_GAPS.md`: закрыть/переоткрыть позиции по health-компонентам (контракт `skipped` vs `error`) и по правам bind-mount в light-стенде.
- `docs/roadmap/FINAL_REPORT.md` + `docs/roadmap/PROGRESS_LEDGER.md`: запись об инфраструктурном hotfix 2026-10-29 (D1–D7) и обновление вердикта prod-readiness.
- ADR-036 (health-probe семантика): дополнить контрактом компонентов — отключённый опциональный сервис = `skipped`, `error` только для реально сконфигурированного и упавшего; `skipped` не роняет readiness.
- ADR-0378 (маскирование): зафиксировать, что plain-`str` секреты в конфиг-моделях — риск утечки через admin-config. **Частично закрыто** (express/telegram → `SecretStr`); остальные plain-`str` credential'ы (`vault.token`, `skb_api.api_key`, `dadata_api.api_key`, `queue.password`, …) — вне скоупа волны.
- Новый ADR не нужен (это hotfix без архитектурного изменения).

## 6. Фиксы волны 2026-11-02 (3 остаточных дефекта smoke)

### 6.1 `POST /api/v1/auto/<action>` с мусорным телом → 422 (не 500)

| Файл:строка | Правка | Почему |
|---|---|---|
| `src/backend/entrypoints/api/generator/auto_register.py:141-176` | тело читается в `_read_payload()` (141), вид тела запоминается | 500 ронялся из-за `TypeError` в `method(**payload)` — мусорное тело оборачивалось в `{"data": ...}` и не подходило к сигнатуре action'а |
| `src/backend/entrypoints/api/generator/auto_register.py:246-262` | `TypeError`/`ValidationError` из dispatch → `HTTPException(422)` с `detail` (код `invalid_request_body`, ожидаемые/полученные поля) | 422 вместо 500: тело не проходит контракт action'а — это ошибка клиента, а не сервера |
| `src/backend/entrypoints/api/generator/auto_register.py:264-272` | `_is_binding_error()` — только ошибки связывания аргументов → 422 | настоящий баг внутри бизнес-логики action'а остаётся 500 (не маскируется под ошибку клиента) |

Тесты: `tests/unit/api/test_auto_register_invalid_body.py` (8) — мусорное тело
(list/string/number/bool) → 422, лишнее поле → 422, валидные запросы → 200.

### 6.2 `express`/`telegram`-секреты → `SecretStr` + маскирование

| Файл:строка | Правка | Почему |
|---|---|---|
| `src/backend/core/config/integration_base.py:138-163` | `signature_secret: SecretStr` + `field_serializer` (`***`) | значение утекало открытым текстом в `GET /api/v1/admin/config` |
| `src/backend/core/config/integration_base.py:180-196` | `secret_key: SecretStr` + `field_serializer` (`***`) | то же для `express.secret_key` / `telegram.secret_key` |
| `src/backend/core/config/telegram.py:63-77` | `token` → `secret_value(self.secret_key)` | публичный контракт остался строкой `{bot_id}:{secret}` |
| `src/backend/core/config/auth.py:85` | `secret_key=_secret_value(express.secret_key)` | `ExpressJwtConfig.secret_key` — публичная строка, не ломаем |
| `infrastructure/notifications/adapters/{express,telegram}.py`, `infrastructure/clients/external/express.py`, `dsl/engine/processors/{express,telegram}/_common.py` | `secret_value(settings.secret_key)` на границе DTO | рирантайм-значение нужно клиентам как строка |

Тесты: `tests/unit/core/config/test_integration_secret_masking.py` (20) —
тип `SecretStr`, маска `***` в `model_dump()`, отсутствие plaintext в
admin-config, публичные контракты (`token`, `AuthConfig`) не сломаны.

### 6.3 Audit-replay без Redis + worker на SQLite

| Файл:строка | Правка | Почему |
|---|---|---|
| `src/backend/core/di/module_registry.py:113-116` | зарегистрирован DI-ключ `clients.storage.redis_streams` | `resolve_module` падал с «Неизвестный ключ infrastructure-модуля» — audit-записи не писались ни на одном профиле |
| `src/backend/infrastructure/clients/storage/redis_streams.py` (новый) | stream-транспорт: Redis Streams (`redis.enabled=true`) или in-memory (`dev`/`dev_light`) | для не-redis транспорта подключение к Redis не требуется; контракт `add_to_stream`/`read_stream` одинаков для обоих |
| `src/backend/infrastructure/workflow/worker.py:216-256` | `_resolve_listener_dsn()` → `None` для не-PG DSN + понятный warning | LISTEN/NOTIFY — механизм PostgreSQL; asyncpg не понимает `sqlite+aiosqlite` (`invalid DSN`) |
| `src/backend/infrastructure/workflow/runner.py:390-410` | guard в `_listen_loop()` | push-path отключается на месте, worker работает в backup-polling режиме |

Решение по worker'у (осознанное): **worker на SQLite поддерживается** —
polling-путь (backup-poll pending-инстансов) работает на любой СУБД;
отключается только push-path LISTEN/NOTIFY, у которого аналога в SQLite нет.

Тесты: `tests/unit/infrastructure/storage/test_stream_transport.py` (8),
`tests/unit/infrastructure/workflow/test_worker_listener_dsn.py` (4).

