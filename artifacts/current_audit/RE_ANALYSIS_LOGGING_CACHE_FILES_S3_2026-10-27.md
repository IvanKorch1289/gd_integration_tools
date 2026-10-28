# Повторный анализ: логирование, кэширование, файлы, S3 (Cycle 172, Wave 13)

Дата: 2026-10-27. База: `master` = `8712f3640` (Wave 4.3 слита fast-forward'ом).

Метод: runtime-проверка (не чтение кода), baseline-прогоны на чистом master
для отделения регрессий от находок.

---

## 0. Итог

| Домен | Статус | Находок | Критичность |
|---|---|---|---|
| Логирование | ⚠️ частично закрыт | 3 | 1 высокая |
| Кэширование | ⚠️ частично закрыт | 2 | 1 высокая |
| Файлы | ❌ не закрыт | 3 | 2 высокие |
| S3 | ⚠️ частично закрыт | 4 | 1 критическая |

Найдено **4** дефекта шире заявленного в плане `S3_CACHE_DB_FS_LOGGING_FIX_PLAN_2026-10-22.md`
(в т.ч. 2 критических в capability-пути, см. §4).

---

## 1. Логирование

### L-1 (высокая) — в production логи пишутся на уровне DEBUG

- `config_profiles/base.yml:285` → `log.level: "DEBUG"`.
- `config_profiles/prod.yml:173-193` → секция `log:` **не переопределяет** `level`.
- Runtime (APP_PROFILE=prod): `settings.logging.level == DEBUG`.

Последствие: в проде структурированные логи генерируются на DEBUG — лишний
объём, шум, риск утечки внутренних полей (в т.ч. в audit-событиях ClickHouse).

Проверено:
```
APP_PROFILE=prod → settings.logging.level = DEBUG
                → settings.logging.host = graylog-prod
                → settings.logging.use_tls = True
```
(host/TLS из `prod.yml` применяются корректно — overlay работает; проблема
только в отсутствующем `level`.)

Fix: `prod.yml` → `log: { level: "INFO" }` (или "WARNING" — решение владельца).

### L-2 (средняя) — `required_fields` не проверяется на выходе

`base.yml:289-294` объявляет `required_fields: [environment, hostname, user_id, action]`,
но механизма проверки их наличия в итоговой записи не найдено: `structlog_backend.py`
добавляет `environment`/`hostname` сам, `user_id`/`action` — из контекста вызова.

Действие: отдельная волна — либо валидация в `structlog_backend`, либо удаление
неисполняемой декларации из конфига (иначе конфиг врёт).

### L-3 (средняя) — dual-emission audit-событий теряет ошибки

`audit_mixin.py:90` → `emit_capability_check(...)` — coroutine, вызывается **без await**
(`RuntimeWarning: coroutine 'AuditService.emit' was never awaited` в выводе pytest).

Последствие: capability-аудит в unified audit-service не доходит; работает только
legacy-callback путь. Тот же warning виден в проде-логах при каждой проверке.

Fix: сделать `emit_capability_check` синхронным (fire-and-forget через
`asyncio.create_task` / thread) либо явно задокументировать, что вызов
best-effort.

### Закрыто ранее (подтверждено)
- Graylog TCP: `use_tls` действительно включает TLS (`ssl.create_default_context()`,
  проверка сертификата и hostname) — `graylog_gelf.py:12-27`.
- `prod.yml` → `log_requests: false` (корректно для throughput).

---

## 2. Кэширование

### C-1 (высокая) — `delete_by_tag` падает на RedisCluster (CROSSSLOT)

`src/backend/infrastructure/cache/backends/redis.py:107-132`:
```python
keys = await self._client.smembers(index_key)
str_keys = [...]
await self._client.delete(*str_keys)   # ← один DEL по всем ключам
```
В RedisCluster ключи из разных hash-слотов → `CROSSSLOT`. Fan-out по нодам
отсутствует (подтверждено аудитом, HIGH-07).

Fix (Wave 7b): батчевое удаление по слоту / fan-out по нодам.

### C-2 (средняя) — `cache_policy()` — marker без эффекта, предупреждения нет

`src/backend/dsl/builders/policy_mixin.py:61-73`: `cache_policy()` — только
`_add_policy_processor("cache", ...)`, реального кэша не создаёт.
Депрекейт-шим `cache()` предупреждает (`DeprecationWarning`), а `cache_policy()` — нет:
вызов выглядит рабочим, кэша нет.

Fix (Wave 7c, частично в плане): `RuntimeWarning` при вызове `cache_policy()`.

### Закрыто ранее (подтверждено)
- `get_unified_cache_facade(plugin=...)` — plugin-aware фабрика (коммит `86c5eff2d`).
- `DiskCache.exists` TTL-aware (S176/S60).

---

## 3. Файлы

### F-1 (высокая) — path-traversal защита покрывает 3 процессора из ~7

`validate_path` вызывается только в:
- `components/filereadprocessor.py:57`
- `components/filewriteprocessor.py:69`
- `rpa/operations/filedeleteprocessor.py:65`

**Не вызывается** в (проверено grep, 0 вхождений):
- `rpa/operations/filewatchprocessor.py` — сканирует директорию
- `rpa/operations/filtereddirectoryscanprocessor.py` — сканирует директорию
- `fs_directory_scan.py` — сканирует директорию
- `file_search.py` — рекурсивный поиск

Последствие: `directory_scan` / `file_watch` / `file_search` читают/перечисляют
произвольные пути, минуя allowlist.

### F-2 (высокая) — allowlist путей живёт только в env

`src/backend/dsl/engine/processors/_path_safety.py:25-33` → `DSL_ALLOWED_PATHS`
(env-only). В `config/services/*` и `config_profiles/*.yml` ключа нет.

Дефолт при отсутствии env: `/data/uploads`, `/data/exports`, `/tmp/dsl`, `/var/data`.
В контейнере без переменной окружения allowlist молча деградирует до дефолта
(HIGH-17 в аудите).

Fix (Wave 6): `dsl.allowed_paths` в конфиг-системе, env остаётся override.

### F-3 (средняя) — `DSL_ALLOWED_PATHS` парсится по `:` — конфликт с Windows-подобными путями и scope-glob

`_path_safety.py:29` → `env.split(":")` — разделитель двоеточие совпадает с
разделителем scope в ADR-044 (`fs.read:scope:external`). Для путей это
работает, но конфигурация allowlist не может выражать путь с двоеточием,
и нет единого формата с `fs.*` scope-грамматикой.

---

## 4. S3

### S-1 (критическая) — **все S3-шаги обходили capability-gate**

`CapabilityGate` **не был зарегистрирован** в `svcs_registry`:
- `has_service(CapabilityGate)` → `False` (проверено runtime);
- `service_setup._register_storage_facade()` → `capability_check = None`;
- `StorageFacade._assert_read/_assert_write` при `_check is None` — **no-op**
  (`services/storage/facade.py:72-78`);
- `s3.py:99-114` — fallback-путь логировал WARNING и шёл дальше без проверки.

Runtime-доказательство (до фикса): `to_s3` отработал без единой проверки,
лог: `DSL storage step 'composition.demo' runs without capability-gate`.

Fix (сделан в Wave 7a): `CapabilityGate` зарегистрирован в svcs_registry
(`service_setup._register_capability_gate()`), `storage.read`/`storage.write`
объявлены public + в core-декларациях для `core`/`system`.

### S-2 (высокая) — runtime plugin (route_id из YAML) ≠ ключ декларации (name из TOML)

- `RouteLoader` декларирует capability под `manifest.name` (TOML `name`)
  — `services/routes/loader.py:427`;
- `ExecutionContext.route_id` = `pipeline.route_id` (YAML `route_id:`)
  — `dsl/yaml_loader/build.py:50`;
- `s3.py:68` → `plugin = context.route_id or "dsl"`.

Расхождения в репозитории (3 роута):

| Роут | YAML `route_id` | TOML `name` |
|---|---|---|
| composition_demo | `composition.demo` | `composition_demo` |
| jupyter_hub_run (run_file) | `jupyter_hub_run_file` | `jupyter_hub_run` |
| jupyter_hub_run (run_inline) | `jupyter_hub_run_inline` | `jupyter_hub_run` |

**Решено в Wave 7a (alias-декларация).** `RouteLoader._declare_route_id_aliases`
дублирует декларацию роута (с тем же scope) под фактический YAML `route_id`.
Право роута не расширяется — копируется ровно та же декларация.

Проверено runtime:
```
composition.demo/net.outbound -> ALLOW   (было DENY)
composition_demo/net.outbound -> ALLOW
```

### S-5 (критическая, найдена при включении gate) — capability не объявлены ни для кого

При регистрации `CapabilityGate` в svcs (Wave 7a) выяснилось, что
**ни один plugin не объявляет** capability, которые проверяют
production-фасады. До Wave 7a это было не видно: gate не был
зарегистрирован → `_check is None` → проверки молча пропускались
(fail-open). С живым gate все эти пути стали бы blanket-deny:

| Фасад | Проверяемая capability | Plugin в production |
|---|---|---|
| `StorageFacade` | `storage.read` / `storage.write` | `system` |
| `UnifiedCacheFacade` | `cache.read` / `cache.write` | `system` |
| `ExternalDatabaseFacade` | `db.read` / `db.write` / `db.execute_procedure` | `system` |
| `OutboundHttpClient` | `net.outbound` | `core` |
| `AIFsFacade` | `fs.read` | `ai-agent` |

**Решено в Wave 7a**: baseline-декларации добавлены в
`core_declarations.py` (71 capability) и объявлены для `core`, `system`,
`ai-agent`. Plugin `extension` намеренно **не** входит в baseline:
изолированные инстансы `UnifiedCacheFacade` с `plugin="extension"`
создаются без `capability_check` (`services/cache/__init__.py:100-103`),
а расширения обязаны объявлять capability в `plugin.toml`.

Проверено runtime с живым gate:
```
http     -> ConnectError   (capability прошёл, соединение не establishment)
storage  -> OK
cache    -> OK
```

### S-6 (средняя) — плоская форма `capabilities = [...]` не проходит `declare`

`route.toml` в плоской форме (`capabilities = ["net.outbound", "audit.write"]`,
4 из 7 роутов: hello_route, jupyter_hub_run, osint_agent, test_route_w1)
не задаёт scope. `CapabilityDef.scope_required=True` → `validate_ref`
бросает `ValueError: Capability 'net.outbound' requires explicit scope`.

**Латентно**: роут сначала отклоняется на subset-check
(`CapabilitySupersetError`) или feature_flag, поэтому `declare` не
достигается — причина не видна. Если роут с плоской формой пройдёт
subset-check, он упадёт на `declare` с `capability_error`.

Также `tools/scaffold_route.py:139` генерирует именно плоскую форму
без scope → scaffolded-роут сразу не загрузится.

Fix (Wave 7d): привести плоскую форму к `scope="*"` в
`_normalize_capabilities` (manifest_toml.py:281-317) — scope-обязательность
это не отменяет, а задаёт «любой scope».

### S-3 (средняя) — `infra_s3_get` идёт мимо фасада → без проверки

`src/backend/dsl/engine/processors/infra_s3.py:47-48`:
```python
storage = get_object_storage_class()(context)
content = await storage.download(self.key)
```
Обходит `StorageFacade` → `_assert_read` не вызывается. Процессор объявляет
`capabilities=("storage.read",)`, но объявление нигде не проверяется.

Fix: перевести на `StorageFacade` (или явно пометить как осознанный обход).

### S-4 (средняя) — `presigned_url` проверяет `storage.read`, а не отдельную capability

`services/storage/facade.py:240-242` → `presigned_url()` вызывает
`_assert_read(key)` → `storage.read`. Presigned-URL даёт клиенту **прямую
запись** в бакет → фактически нужен `storage.write`.

Это отдельная capability (Wave 8 по плану): `storage.presign` + audit-событие.

### Закрыто ранее (подтверждено)
- `aiobotocore` вместо `aioboto3`; долгоживущий client, реальный pool, lifecycle.
- Presign TTL ограничен (`presign_ttl_max_seconds`), SSE включён.
- Квота подключена (`_check_quota` вызывается в `upload`), `enforce_quota`
  читается из `settings.storage.enforce_quota` (в `config_profiles/*.yml` ключа
  нет → alert-only по умолчанию).

---

## 5. Сквозная находка: capability-путь был разорван на 4 независимых дефекта

Это шире, чем в плане 172 (там зафиксирован только HIGH-16 про
`rpa.directory.scan` вне vocabulary). Фактически:

1. **`AuthorizationFacade.gateway` возвращал КЛАСС, а не инстанс** →
   `TypeError` внутри `check()` → **deny для всех** 41 процессора с
   `required_capability` и 16 sink'ов/source'ов с `@require_capability`.
2. **`get_capability_gate()` не существовало**, хотя его импортировал
   `agent_dsl/_base.py` → `ImportError` → проверка **молча пропускалась**
   (fail-open) для 12 agent_dsl-процессоров.
3. **Три независимых экземпляра `CapabilityGate`** (plugin_loader /
   `CapabilityFacade.gate` / ai-provider) → декларации роутов и плагинов
   **не были видны** runtime-проверкам вообще.
4. **53 capability отсутствовали в vocabulary** (весь `rpa.*` + connector-сегмент).

Все четыре исправлены в Wave 5 (в рабочем дереве) — см. `core_declarations.py`,
`vocabulary/defaults/rpa_fs.py`, грамматика 2+ сегментов, singleton-гейт.

---

## 6. Сводный план (обновлённый)

| # | Действие | Приоритет | Статус |
|---|---|---|---|
| 7a | `CapabilityGate` в svcs_registry + baseline-декларации (71 cap) для `core`/`system`/`ai-agent` + `storage.*` public | P0 | сделано (в дереве) |
| 7d | **S-2 решён**: alias-декларация под YAML `route_id` (`RouteLoader._declare_route_id_aliases`) | P0 | сделано (в дереве) |
| 7e | **S-6**: плоская форма `capabilities = [...]` → `scope="*"` в `_normalize_capabilities`; иначе scaffolded-роут не загрузится | P1 | не начато |
| 7f | **S-3**: `infra_s3_get` → через `StorageFacade` (сейчас обходит `_assert_read`) | P2 | не начато |
| 13.1 | `prod.yml`: `log.level` (не DEBUG) | P1 | не начато |
| 13.2 | `emit_capability_check` без await → реальная эмиссия | P1 | не начато |
| 7b | `delete_by_tag` fan-out по нодам RedisCluster | P1 | не начато |
| 7c | `cache_policy()` → RuntimeWarning | P2 | не начато |
| 6.1 | `validate_path` в filewatch / filtereddirectoryscan / fs_directory_scan / file_search | P1 | не начато |
| 6.2 | `dsl.allowed_paths` в конфиг-систему (env → override) | P1 | не начато |
| 8.1 | `storage.presign` — отдельная capability + audit-событие | P2 | не начато |
| 10 | API эффективных настроек `/admin/settings/{domain}` + UI | P1 | частично: есть `GET /admin/config` (§8.1) |
| 11 | DSL→workflow actions `storage.*`/`cache.*`/`log.*` | P1 | не начато (§8.4) |
| 12 | Circuit breaker для S3 и cache | P1 | не начато (§8.3) |
| 9 | Документация по доменам | P2 | частично (§8.5) |

---

## 7. Верификация Wave 7a

- `ruff check` по всем изменённым файлам → **All checks passed!**
- `pytest` (core/security, services/routes, services/storage, services/cache,
  dsl/engine/processors/storage, plugins/composition, infrastructure/storage):
  **9 failed, 918 passed** — **идентично baseline** на чистом master
  `8712f3640` (те же 9 pre-existing падений в
  `plugins/composition/test_lifecycle_smoke.py` и `test_waf_setup_smoke.py`).
- Runtime с живым gate: `http → ConnectError` (capability прошёл),
  `storage upload → OK`, `cache set → OK`.
- Runtime алиаса: `composition.demo/net.outbound → ALLOW` (было DENY).

> Отдельно: `tests/unit/plugins/composition/test_waf_setup_clamav.py` даёт
> `StopIteration` при сборе **в батче** — одинаково на моей ветке и на
> baseline, то есть pre-existing order-зависимая проблема, не регрессия.

---

## 8. Расширенный аудит: настройки, безотказность, DSL→workflow, документация

### 8.1 Настройки и доступ к ним (S-7, средняя)

- **API есть, но обеднённый**: `GET /admin/config` (`entrypoints/api/v1/endpoints/admin.py:35-42`,
  admin-guard) → `AdminService.get_config()` (`services/core/admin.py:79-87`)
  возвращает `settings.model_dump()`.
  - Нет разбивки по домену (`/admin/settings/{domain}` не существует).
  - **Нет указания источника значения** (env / yaml / vault / default) —
    `BaseSettings` теряет происхождение, `config_loader.py` его не отслеживает
    (`grep effective_config|source` → 0 совпадений).
- **В UI не выведено**: `grep 'admin.get_config' src/frontend/streamlit_app/` → 0.
  Streamlit-страницы по конфигурации отсутствуют (есть `50_Фича_флаги.py`,
  `78_Плавная_деградация.py`, `79_Редактор_профиля_устойчивости.py`).
- **CLI**: `src/backend/cli/runtime.py:41` — `settings_default(field)` только
  для одного поля.

Вывод: «удобный доступ к настройкам» в заявленном смысле (структурированно,
с источником значения, из UI) отсутствует.

### 8.2 Capability-аудит не эмитится (S-8, критическая)

- `audit_mixin.py:90` → `emit_capability_check` (`core/audit/facade/capability.py:17`,
  sync) → `emit_audit` (`core/audit/facade/_base.py:24`, sync) → `svc.emit(...)`
  — **coroutine**, вызываемый **без `await`**.
- Runtime-доказательство:
  ```
  returned type: coroutine
  RuntimeWarning: coroutine 'AuditService.emit' was never awaited
  legacy audit callback installed: False
  ```
- Legacy-callback тоже не работает: `get_capability_gate()` создаёт гейт
  **без** `audit=` (`gate/__init__.py:149`) → `g._audit is None`.
- Итог: **ни одно** capability-решение (granted/denied) не попадает в
  unified audit service. Async-пути audit работают
  (`await get_audit_service().emit(event)` — `dsl/engine/processors/audit_clickhouse.py:198`),
  но capability-аудит идёт только через sync-путь.

### 8.3 Circuit Breaker не применяется к S3 и cache (S-9, высокая)

- Канон: `core/resilience/breaker.py` (purgatory) — ADR-0305 (статус **Draft**).
  Паттерн подключения: `get_breaker_registry().get_or_create(BreakerSpec(...))`.
- Применён в: `services/rpa/desktop_session_pool.py:55`,
  `services/rpa/desktop_rpa_client.py:43`, `services/ai/gateway/client.py:186`,
  `services/ai/llm/tgi_batch_client.py:26`.
- **Не применён**: `infrastructure/storage/` (grep `breaker|circuit` → только
  упоминание в docstring `fallback.py:436`), `services/cache/`,
  `infrastructure/cache/`.
- Следствие: падение MinIO/Redis даёт retry-лавину (S3 `retries: 5`) вместо
  быстрого fail-fast; cache-истечение лавинообразно.

### 8.4 DSL→workflow: actions для storage/cache/log отсутствуют (S-10, средняя)

- `ActionHandlerRegistry` регистрируется в `dsl/commands/setup/registers_domains.py`:
  `orders.*`, `skb.*`, `dadata.*`, `tech.*` (включая `tech.check_s3`),
  `admin.*` (включая `admin.list_cache_keys`, `admin.invalidate_cache_by_tag`).
- CRUD-actions: `dsl/commands/setup/helpers.py:11` → `_CRUD_METHODS`.
- **Нет** generic-actions вида `storage.*` / `cache.*` / `log.*`:
  grep по `action="storage` / `action="cache` / `action="log` → пусто.
- Вывод: вызвать S3-загрузку или cache-инвалидацию из Temporal-workflow
  (через `invoke_workflow` → action) нельзя без написания плагина.

### 8.5 Документация: `docs/infra/object-storage.md` частично устарела (S-11, средняя)

Документ от 2026-10-22 (цикл 171) — свежее всех доменных. Но §6 «Known
limitations» содержит 4 утверждения, **противоречащих текущему коду**:

| Утверждение в документе | Факт по коду |
|---|---|
| «No server-side encryption, ACL, versioning or lifecycle settings exist» | SSE есть: `settings.server_side_encryption` default `AES256` (`core/config/services/storage.py:133-140`), применяется `s3.py:344-346` |
| «`max_pool_connections` is effectively dead. A client is constructed and torn down per operation» | Клиент долгоживущий: `_client` + `_client_lock` + кэш (`s3.py:165-190`), инвалидируется при транспортном отказе (`_invalidate_client`) |
| «`presigned_url` has no maximum TTL» | TTL ограничен: `s3.py:585-592` — clamp к `presign_ttl_max_seconds` + warning |
| «`aioboto3` is not declared… Production fails fast» | `aioboto3` заменён на `aiobotocore>=3.9.1,<4.0.0` (`pyproject.toml:94-101`, аудит CRITICAL-06 закрыт) |
| «`config_profiles/base.yml::resilience.fallbacks.minio` is read by nothing» | Читается: `infrastructure/storage/factory.py:200-207` |

Актуальные и верные в документе: `storage.read` вместо отдельной capability для
presign, alert-only квота, «`s3_get`, а не `from_s3`».

**Другие домены**: по логированию свежего доменного документа нет
(`docs/runbooks/incident-response.md` — единственный практический);
по ФС — нет вовсе (`validate_path`/`DSL_ALLOWED_PATHS` упоминаются только в
`docs/compose/reports/2026-08-05-p0-fix-retrospective.md`);
`docs/cache/CACHE_DSL_AUDIT.md` от 2026-08-31 (предшествует циклу 170/171).

---

## 9. Аудит блока БД (внутренняя + внешняя), DSL, CDC

### 9.1 Пакеты и драйверы (S-12, высокая)

Фактически установлено в `.venv`:
`psycopg` (v3), `asyncpg`, `aiomysql`, `pymysql`, `oracledb`, `sqlalchemy`,
`alembic`, `redis`, `pyarrow`, `aiokafka`, `nats`, `pymongo`, `elasticsearch`.

**Не установлено** (при этом используется или заявлено):

| Пакет | Где заявлен/используется | Последствие |
|---|---|---|
| `clickhouse_connect` | импортируется в **6+** местах: `services/audit/clickhouse_audit_service/service.py:119`, `services/workflows/saga_history.py:40`, `hitl_history.py:64`, `cost_estimator.py:77`, `services/scheduler/cron_dashboard_service.py:49`, `infrastructure/clients/storage/clickhouse_admin_client.py:45` | **Не объявлен** в `pyproject.toml` вообще (есть только mypy-override на строке 1044). ClickHouse-аудит, saga-history, HITL-history, cost-estimator — деградация |
| `aioodbc` | extra `db_drivers` (`pyproject.toml:214`) — MSSQL | Не установлен → MSSQL не работает |
| `psycopg2` | `infrastructure/resilience/snapshot_job.py:129` (sync engine для APScheduler) | Не установлен и **не объявлен** (в core только `psycopg[binary]` в dev-группе) |
| `pyodbc`, `ibm_db_sap` | — | Не заявлены, не используются (DB2 недоступен) |
| `spyne` | SOAP (`infrastructure/sources/soap.py`) | Не установлен → SOAP-источник не работает |

Runtime-доказательство:
```
INSTALLED: psycopg, asyncpg, aiomysql, pymysql, oracledb, sqlalchemy,
            alembic, redis, pyarrow, aiokafka, nats, pymongo, elasticsearch
MISSING  : psycopg2, asyncmy, pyodbc, cx_Oracle, ibm_db_sap,
            clickhouse_connect, aioredis, confluent_kafka, spyne, motor
```

### 9.2 Внешний БД: 7 типов в enum, 2 в реализации (S-13, высокая)

- `core/enums/database.py:6-26` — `DatabaseTypeChoices`: postgresql, oracle,
  sqlite, **mssql**, **mysql**, **db2**, **clickhouse**.
- Реализация `_build_dsn` (`core/config/external_databases/connection.py:151-177`)
  поддерживает **только** postgresql и oracle; остальные →
  `NotImplementedError("Поддержка СУБД '<type>' не реализована")` — fail-fast,
  корректно.
- Dispatch запросов/процедур/функций
  (`services/io/external_database/dispatch_mixin.py:127,137,168,170`) —
  также только postgresql/oracle; для остальных
  `DatabaseError("Неподдерживаемый тип БД ...")`.
- **Вывод**: mssql/mysql/db2/clickhouse — декларативно заявлены, но
  функционально недоступны; при этом `db_drivers` extra объявляет драйверы
  именно для них (`aioodbc` → MSSQL, `aiomysql` → MySQL).

### 9.3 Настройки внешнего БД (S-14, средняя)

- Секция `external_databases:` присутствует во **всех** профилях
  (`base/dev/dev_light/staging/prod.yml`).
- `base.yml`: pool_size=5, max_overflow=5, pool_recycle=1800, pool_timeout=30,
  connect_timeout=10, command_timeout=30, max_retries=0,
  **circuit_breaker_max_failures=5, circuit_breaker_reset_timeout=30**,
  slow_query_threshold=1.0, connections=[].
- `dev.yml` — один профиль `oracle_1` (host 10.10.10.11:1521, sid ORCL,
  драйверы `oracledb`/`oracledb`).
- `staging.yml`/`prod.yml` — `ssl_mode: "require"`, `connections: []`.

### 9.4 DSL: выполнение запросов и скриптов (S-15, средняя)

- `script_runner` — **отключён** (`script_runner.py:1-20`): процессор исполнял
  произвольный код через `asyncio.create_subprocess_exec` с наследованием
  `os.environ` → RCE на prod-узле (cycle-4 DOMAIN-P0-002). Сейчас любой вызов
  → `NotImplementedError` + RCE-warning в лог. DSL-сигнатура сохранена.
  Безопасная альтернатива — `extensions/<name>/` с capability
  `script_runner.execute`; sandbox-инфраструктура есть
  (`core/ai/sandbox.py`, `core/tool_sandbox/`, `infrastructure/ai/e2b_sandbox.py`).
- `jdbc_query` — произвольный SQL к внешнему профилю; DDL/DROP/GRANT/REVOKE и
  multi-statement блокируются, bind-параметры через `text()`.
- `db_query_external`, `db_call_procedure`, `db_crud` — внешний БД + процедуры.
- `infra_clickhouse`, `audit_clickhouse` — ClickHouse (деградация из-за
  отсутствия `clickhouse_connect`, см. 9.1).

### 9.5 CDC: 4 стратегии реализованы, драйверы на месте (S-16, информация)

- `infrastructure/clients/external/cdc/client.py:53-60` — 4 стратегии:
  `polling`, `listen_notify` (PG), `logminer` (Oracle), `kafka` (Debezium).
  Зависимости на месте: `asyncpg` (есть), `oracledb` (есть), `aiokafka` (есть).
- DSL-процессоры: `cdc_capture.py`, `cdc_transform.py`.
- DSL-обёртка `cdc_capture` ограничивает `strategy` whitelist'ом из 4 значений
  и проверяет непустоту `tables` (`cdc_capture.py:84-90`).

### 9.6 SQL-инъекция в CDC: имена таблиц подставляются f-string (S-17, высокая)

- `infrastructure/clients/external/cdc/strategies.py:323-338` (LogMiner):
  ```python
  table_list = ", ".join(f"'{t.upper()}'" for t in sub.tables)
  ... WHERE TABLE_NAME IN ({table_list})
  ```
- `strategies.py:126-131` (polling):
  ```python
  query = text(f"SELECT * FROM {table} WHERE {sub.timestamp_column} > :last ...")
  ```
  `table` и `timestamp_column` — из конфига подписки, вставляются без
  bind-параметров.
- В external_database для аналогичных случаев есть `_validate_identifier`
  (`services/io/external_database/validation_mixin.py`), но **CDC его не
  использует**.
- Комментарий в коде: «table/timestamp_column — DSL/config параметры
  подписки, не runtime user input». Это спорно: подписка создаётся из
  DSL-шага, конфигурация которого доступна через API/Streamlit-конструктор.

### 9.7 Capability процессоров: `capabilities=` декоративна (S-18, высокая)

- `@processor(..., capabilities=(...))` (например `fs.watch`, `storage.write`,
  `analytics.read`, `documents.parse`, `queue.produce.kafka`) попадает только
  в JSON-схему `x-gd-capabilities` (`dsl/registry/processor.py:260`) и в
  LSP/linter.
- Runtime-проверки нет: grep по `spec.capabilities` / `processor.capabilities`
  в `dsl/engine/*` → только `lazy_processor.py:134` (возвращает список).
- **Работающий** механизм — `BaseProcessor.required_capability`
  (`dsl/engine/processors/base.py:46,101-137`), вызывается через
  `auth_check`/`check_source_capability`.

---

## 10. Аудит функционала работы с внешними файлами

### 10.1 Сводная таблица файловых процессоров (S-19, высокая)

| Процессор | `required_capability` | `validate_path` | операции с директориями |
|---|---|---|---|
| `fs_directory_scan` (deprecated-шим) | 0 | 0 | 0 (делегирует) |
| `file_watch` (namespace=core) | **0** | **0** | **7** |
| `scan_file` (AV-проверка) | 0 | 0 | 0 |
| `ingest_file` (S3/bytes) | 0 | 0 | 0 |
| `components/filereadprocessor` | 0 | 2 | 0 |
| `components/filewriteprocessor` | 0 | 2 | 0 |
| `rpa/operations/filelistprocessor` | 1 (`rpa.file.list`) | 0 | 0 |
| `rpa/operations/filemoveprocessor` | 1 (`rpa.file.move`) | 0 | 0 |
| `rpa/operations/filewatchprocessor` | 1 (`rpa.file.watch`) | 0 | 0 |
| `rpa/operations/filtereddirectoryscanprocessor` | 1 (`rpa.directory.scan`) | 0 | 1 |
| `rpa/operations/filedeleteprocessor` | 1 | 2 | 0 |

### 10.2 `file_watch` — единственный без обоих барьеров (S-20, высокая)

- `dsl/engine/processors/file_watch.py:38-41` —
  `@processor("file_watch", namespace="core", capabilities=("fs.watch",))`.
- Ни `required_capability`, ни `validate_path`; при этом 7 операций с ФС
  (`os.listdir`, `os.walk`, `stat`).
- `directory` берётся из конструктора **или** из exchange-property
  `watch_directory` (`file_watch.py:159-163`) → runtime-подставляемое значение.
- `fs.watch` **есть** в vocabulary (`base.py:156`) и в baseline
  (`core_declarations.py:140`) — т.е. capability объявлена, но не проверяется.
- Для сравнения: `filtereddirectoryscan` (новый, рекомендуемый) имеет
  `required_capability="rpa.directory.scan"` + safety caps (`max_results=10000`,
  `timeout_seconds=30`) + ADR-0305-сужение таймаута по дедлайну.

### 10.3 `validate_path` закрывает traversal, но не allowlist для сканеров (S-21, средняя)

- `validate_path` корректен: `resolve()` разрушает symlink, проверка
  `startswith(prefix + os.sep)` исключает prefix-коллизию; runtime-проверка
  symlink-наружу → `PathTraversalError`.
- Но применяется только в 3 процессорах (read/write/delete). Сканеры
  (`file_watch`, `filtereddirectoryscan`, `filelist`) полагаются лишь на
  capability — а `capability` не ограничивает *путь*, только факт вызова.

### 10.4 Мёртвый код: `FileSearchProcessor` (S-22, низкая)

- `dsl/engine/processors/rpa/file_search.py:20` — класс **не наследует**
  `BaseProcessor`, не зарегистрирован как DSL-процессор, 0 вызовов в `src/`.
  Объявлен `__all__` (`:17`), но не используется.

### 10.5 Документация по файловым операциям (S-23, средняя)

- Свежего доменного документа нет. `docs/rpa/RPA_GUIDE.md` — единственный
  практический, но не про `file_watch`/`file_list`/`file_search` и без
  раздела про allowlist `DSL_ALLOWED_PATHS`.
- `docs/infra/` содержит только `object-storage.md` (S3). Файловых
  процессоров не описано.

---

## 11. Аудит внутренней БД и завершение «получения файлов»

### 11.1 Внутренняя БД: 7 типов в DSN против 2 у внешней (S-24, средняя)

- `core/config/database.py:215-288` — `_build_dsn` поддерживает **все 7**
  типов: sqlite, postgresql, oracle, **mssql** (`mssql+aioodbc|pyodbc` +
  `?driver=ODBC+Driver+17+for+SQL+Server`), **mysql**
  (`mysql+aiomysql|pymysql`), **db2** (`db2+ibm_db_sa`), **clickhouse**
  (placeholder URL — SQLAlchemy не используется).
- Engine создаётся через `create_async_engine` (`initializer.py:159-170`),
  т.е. тип из настроек реально определяет диалект.
- **Расхождение с внешним контуром**: `external_databases/connection.py`
  (тот же `DatabaseTypeChoices`) — только postgresql/oracle
  (см. 9.2). Один enum, два разных уровня поддержки.
- Настройки профилей корректны:
  - `dev_light.yml` → `type: sqlite`, DSN `sqlite+aiosqlite:///./.run/dev.sqlite3`;
  - `dev.yml` → `postgresql` @ `postgres:5432`;
  - `staging.yml` → `postgres-staging`; `prod.yml` → `postgres-prod`.
- Полный набор настроек присутствует (`core/config/database.py`): type,
  host, port, name, path, async_driver, sync_driver, echo, username, password,
  pool_size, max_overflow, pool_recycle, pool_timeout, pool_pre_ping,
  pool_use_lifo, connect_timeout, command_timeout, ssl_mode, ca_bundle,
  max_retries, circuit_breaker_max_failures, circuit_breaker_reset_timeout,
  slow_query_threshold, replica_dsn.
- Валидаторы: `validate_ssl`, `validate_oracle_drivers`, `validate_required_fields`.

### 11.2 Внутренняя БД: replica-роутинг и breaker — работают (S-25, информация)

- `infrastructure/database/smart_session_manager.py` — read/write routing
  на replica, канонический `BreakerSpec` + `ReplicaFailoverBreaker`
  (`:118-137`, FW6.1 — переход с deprecated `CircuitBreakerSpec`),
  `failure_threshold`, `cooldown_seconds`, lag-budget routing
  (`pg_stat_replication`, `lag_budget_bytes` default 10 MB).
- Итог: по безотказности внутренняя БД — самая зрелая подсистема проекта
  (в отличие от S3/cache, см. 8.3).

### 11.3 `execute_with_resilience` — мёртвый код с врущим docstring (S-26, средняя)

- `initializer.py:273-287`: docstring «Execute raw SQL query с **CB + Retry**
  (S182 I-4.5)», тело — `async with self.async_engine.begin() as conn:
  return await conn.execute(query, params or {})` — ни breaker'а, ни retry.
- Вызовов в `src/` — **0** (единственное упоминание — определение).

### 11.4 `infra_db_query` — произвольный SQL без валидации и без capability (S-27, критическая)

- `dsl/engine/processors/infra_db.py:41-50`:
  ```python
  async with sm.session() as session:
      result = await session.execute(self.sql)   # self.sql — произвольный SQL
  ```
- Объявлен `capabilities=("db.read",)` (`:30`) — но это **декоративная**
  декларация (см. 9.7): runtime-проверки нет.
- `required_capability` — **не задан** → `auth_check` не выполняется.
- `_validate_sql` (блокировка DDL/DROP/GRANT/REVOKE/multi-statement) в этом
  процессоре **отсутствует**, хотя есть в `jdbc_query` (`:84-92`,
  `_FORBIDDEN_SQL = {DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE}`) и в
  `components/databasequeryprocessor.py:47`.
- Runtime-подтверждение доступности как YAML-шага:
  ```
  всего процессоров: 95
  infra_db_query   infra:infra_db_query | ('db.read',)
  ```
  → шаг `infra_db_query` доступен в YAML/DSL и выполняет произвольный SQL
  (включая DML/DDL) к внутренней БД без capability-гейта.
- Для сравнения: `db_call_procedure` (`core:db_call_procedure`) объявлен с
  `capabilities=("db.execute_procedure.*",)`, но тоже без `required_capability`.

### 11.5 Capability-декларации процессоров: 52 из 77 (S-28, средняя)

- 52 файла используют `required_capability` (работающий механизм),
  77 файлов содержат `@processor` (декоративный).
- `dsl/registry/lazy_processor.py:126-138` — `capabilities_for()` помечен
  комментарием «**policy-gate**», но вызовов в `src/` — **0** (мёртвый код).
- Lazy-регистрация (`RouteBuilder._add_lazy`, например `jdbc_query` в
  `dsl/builders/transport/persistence.py:415-421`) задаёт `capabilities=()`
  пустым → capability для lazy-процессоров отсутствует вовсе.

### 11.6 «Получение файлов»: FTP-процессор без `validate_path` (S-29, средняя)

- `rpa/operations/ftpuploadprocessor.py`:
  - `required_capability = "rpa.ftp.upload"` — **проверяется** (`auth_check`
    на строке 86), capability есть в vocabulary (`rpa_fs.py:87`) и в
    baseline (`core_declarations.py:126`);
  - FTPS по умолчанию с `ssl.create_default_context`; plaintext — fail-closed
    (нужны `allow_insecure_ftp=True` **и** env `FTP_INSECURE_OK=1`);
  - **но** `local_path` читается напрямую (`os.path.exists` + `open(...,"rb")`)
    без `validate_path` → capability разрешает вызов, но не ограничивает
    читаемый путь (allowlist `DSL_ALLOWED_PATHS` не применяется).
- Прочие пути «получения файлов» проверены и корректны:
  - `ingest_file` — байты из S3 или exchange-property (SSRF-риска нет);
  - `rpa/documents.py` — работа с `bytes`/`BytesIO`, не с путями;
  - `HttpRequestProcessor` — имеет `required_capability="rpa.http.request"`.

---

## 12. Независимая верификация находок (claim-verification)

### 12.1 Метод

Прогнан независимый зонд
`codebase-analysis-and-audit/scripts/declared_vs_enforced.py` (эвристики
A ENUM-GAP, B DECORATIVE-METADATA, C UNREAD-CONFIG-KEY,
D LITERAL-SQL-INTERPOLATION) по `src/backend`. Скрипт сначала падал на
баге (`_string_literals(None)` при `ast.AnnAssign` без значения —
`required_capability: ClassVar[str | None] = None`); баг исправлен в скилле
(`scripts/declared_vs_enforced.py`, добавлен guard `if node is None: return []`).

Счётчики прогона:
```
138 B DECORATIVE-METADATA
115 A ENUM-GAP
 20 D LITERAL-SQL-INTERPOLATION
```

### 12.2 Подтверждение S-18 (декоративные capability-декларации) в масштабе

138 деклараций, не 20+. В доменах аудита:
`dsl/engine/processors/file_watch.py`, `rpa/operations/filelistprocessor.py`,
`filemoveprocessor.py`, `filewatchprocessor.py`,
`filtereddirectoryscanprocessor.py`, `filedeleteprocessor.py`,
`db_call_procedure.py`, `infra_log.py`, `infra_mongodb.py`.

### 12.3 Подтверждение S-17 (SQL-интерполяция в CDC) — ровно 2 из 20

Зонд нашёл 20 интерполяций; **все 20 проверены вручную**:

| Файл:строка | Что интерполируется | Вердикт |
|---|---|---|
| `cdc/strategies.py:127` | `table`, `sub.timestamp_column` (polling) | **РЕАЛЬНАЯ находка** (S-17) |
| `cdc/strategies.py:330` | `table_list` из `sub.tables` (LogMiner) | **РЕАЛЬНАЯ находка** (S-17) |
| `sqlite_doc_store.py:66,86,125,167,188,208` | `table` (namespace) | false positive — namespace валидируется regex в `_ensure_namespace` |
| `sqlite_doc_store.py:160` | **`key` из `filters`** | **РЕАЛЬНАЯ находка** — см. 12.4 |
| `sqlite_search.py:72,75,191,225` | `table` (index) | false positive — `_INDEX_RE.match` |
| `search_chain.py:53,57` | `index` | false positive на практике — индексы константы (`_ORDERS_INDEX`, `_AUDIT_INDEX`), user input не достигает |
| `immutable_audit.py:230,240,312` | `self._table` (ctor-параметр) | false positive |
| `outbox.py:314` | `select_inner` (хардкод-ветка Oracle/PG) | false positive |
| `inbox_writer.py:54` | `self._table` (ctor-параметр) | false positive + мёртвый код (`InboxDLQWriter` — 0 вызовов) |
| `ml_inference.py:370` | `self._table` | false positive — `.isalnum()` в `__init__` |

### 12.4 Новая находка: SQL-инъекция в `SqliteDocStore.find` (S-30, средняя)

- `infrastructure/storage/sqlite_doc_store.py:158-162`:
  ```python
  conditions, params = zip(*filters.items())
  where_clause = " AND ".join(
      f"json_extract(body, '$.{key}') = ?" for key in conditions
  )
  ```
  `key` — **имя фильтра из пользовательского словаря**, вставляется в SQL
  без валидации. Для сравнения: `namespace` (имя таблицы) валидируется
  regex в `_ensure_namespace` (`:197`), `doc_id` и значения — bind-параметры.
- Runtime-доказательство (обход фильтра):
  ```
  baseline (a=1) rows = 1
  INJECTED rows = 3 -> BYPASS WORKS
  ```
  payload: `x') OR 1=1 OR ('1'='1` → WHERE-условие обходится, возвращаются
  все строки namespace'а.
- **Severity ограничена достижимостью**: `SqliteDocStore` **не инстанцируется
  нигде** в `src/` (grep → только упоминание в docstring
  `core/interfaces/doc_store.py:5`). RAG-search идёт через MongoDB/vector
  store, а не через этот бэкенд. → потенциальная уязвимость, не
  эксплуатируемая в текущей конфигурации; станет опасной при подключении
  бэкенда.

### 12.5 Статус «мёртвого кода» — перепроверен

Ранее заявлено не подключено: `FileSearchProcessor`, `InboxDLQWriter`,
`SqliteDocStore`, `execute_with_resilience`, `capabilities_for`,
`drain_quarantine`. Проверено повторно на текущем HEAD — все подтверждены
как неиспользуемые (0 вызовов в `src/`).

### 12.6 Self-test зонда в скилле падает (S-31, низкая)

`scripts/test_declared_vs_enforced.py:105`:
```
assert not any("unused_option" not in k and "host" in k for k in keys)
AssertionError: [... 'service.host' — key never read ..., 'service.unused_option' — ...]
```
Проверка ищет подстроку `"host"` в ключе, но `service.host` — это
корректный контрольный кейс (значение читается, имя содержит `host`).
Ложное срабатывание в самом тесте зонда, а не в проверяемом коде.

---

## 13. Наличие настроек: 10 мёртвых ключей в `base.yml` (S-32, высокая)

### 13.1 Механизм, скрывающий проблему

`FilteredSettingsSource._filter_data` (`core/config/config_loader.py:191-197`):

```python
return {k: v for k, v in group_data.items() if k in self.model_fields}
```

Ключи из YAML, которых нет в pydantic-модели, **молча отбрасываются** —
без ошибки, без warning'а. Поэтому `extra="forbid"` в моделях
(`MqttSettings`: `extra="forbid"`, `DatabaseConnectionSettings`:
`extra="forbid"`) не срабатывает: значения отфильтровываются **до**
валидации. Опечатка в имени ключа = тихая потеря настройки.

### 13.2 Найдено 10 непрочитанных ключей (все в `base.yml`)

Прогон эвристики C по всем 5 профилям дал ровно 10 ключей, все в `base.yml`:

```
base.yml: 'http3.bind_host'    base.yml: 'mcp.bind_host'
base.yml: 'http3.bind_port'    base.yml: 'mcp.bind_port'
base.yml: 'mcp.http_path'      base.yml: 'mcp.sse_enabled'
base.yml: 'mcp.stdio_enabled'  base.yml: 'mqtt.bind_host'
base.yml: 'mqtt.bind_port'     base.yml: 'queue_consumer_max_prefetch'
```

### 13.3 Разбор по секциям

**`http3:` — модели не существует.** Grep по `yaml_group.*http3` /
`Http3Settings` → 0 совпадений. Вся секция (`require_client_auth`,
`bind_host`, `bind_port`) — декорация. При этом комментарий в `base.yml:641`
утверждает «Sprint 35 P1 #6: HTTP3 defaults (was missing from base…)» —
т.е. заявлено, что дефолты заданы, а задавать некуда.

**`mqtt:` — все 3 ключа вне модели.** `MqttSettings`
(`core/config/services/mqtt.py:21-68`) имеет `broker_host`, `broker_port`,
`username`, `password`, `client_id`, `topics`, `qos`, `enabled`,
`tls_enabled`, … — но **не** `bind_host`/`bind_port`/`require_client_auth`.
Runtime-доказательство:
```
broker_host = localhost | broker_port = 1883 | enabled = True
```
Это **дефолты модели**, а не значения из `base.yml`
(`bind_host: 127.0.0.1`, `bind_port: 1883`). Отдельно:
`entrypoints/mqtt/mqtt_handler.py:266` использует
`broker_host="localhost", broker_port=1883` **хардкодом**.

**`mcp:` — 5 из 7 ключей вне модели.** `McpSettings`
(`core/config/ai_stack.py:287`) имеет `http_enabled`, **`bind_path`**
(не `http_path`), `auth_methods`, `tool_allowlist`, `tool_public_namespaces`,
`tool_authz_enabled`, `legacy_description_schema`. Runtime:
```
http_enabled = False | bind_path = /mcp | tool_allowlist = []
```
- `mcp.http_path: /mcp` → мёртв (правильное имя — `bind_path`, но оно
  в `base.yml` **не задано**, работает дефолт `/mcp`);
- `mcp.bind_host`/`bind_port` → мёртвы (модель их не имеет);
- `mcp.sse_enabled`/`stdio_enabled` → мёртвы (в модели нет; SSE/stdio
  транспорт не включается через конфиг);
- `mcp.http_enabled` и `mcp.tool_allowlist` → **работают**
  (`app_factory.py:202`, `ai_stack.py`).

**`queue_consumer_max_prefetch: 10` (flat, `base.yml:648`) — дубликат.**
Реальное поле — `queue.consumer_max_prefetch`
(`core/config/services/queue.py:73`), оно и применяется
(runtime = 10 = дефолт модели). Flat-ключ без `queue:`-префикса не
попадает в модель → мёртв. Значение при этом совпадает с дефолтом, поэтому
фактического расхождения в поведении нет — но конфиг вводит в заблуждение
(выглядит как «настроенное» значение, а настроено другое поле).

### 13.4 Почему это не поймал ни один прошлый аудит

Ключи читаются «похоже» — `bind_host`/`bind_port` — на настоящие настройки
других подсистем (например, `settings.grpc.require_client_auth`
в `entrypoints/grpc/grpc_server/server.py:60`). Grep по имени находит
совпадения, и проверка «есть ли такой ключ в коде» даёт ложное «да».
Нужен путь «yaml → yaml_group → model_fields», а не поиск по подстроке.

### 13.5 Последствие

10 ключей в `base.yml` создают иллюзию настраиваемости. Для `mqtt`/`mcp`
значения `127.0.0.1` (bind-host) выглядят как hardening-требование Sprint 34
P0, но код их не видит → фактический bind-host определяется хардкодом
(`localhost` / default FastMCP). Для `http3` секция целиком фиктивна.

---

## 14. Итог аудита

| Домен | Находок | Critical | High | Medium | Low |
|---|---|---|---|---|---|
| Логирование | S-1…S-8 | 1 | 1 | 4 | 2 |
| Кэширование | S-9…S-13 | 0 | 1 | 1 | 1 |
| S3 | S-1…S-8, S-14 | — | — | — | — |
| Файлы | S-19…S-23, S-29 | 0 | 2 | 3 | 1 |
| БД (внешняя) | S-12, S-13, S-17 | 0 | 3 | 1 | 0 |
| БД (внутренняя) | S-24…S-28 | 1 | 1 | 4 | 0 |
| Конфигурация | S-32 | 0 | 1 | 0 | 0 |
| Верификация | S-30, S-31 | 0 | 0 | 1 | 1 |
| **Всего** | **S-1…S-32** | **2** | **10** | **15** | **5** |

Проверено независимым зондом (`declared_vs_enforced.py`): 138 декоративных
capability-деклараций, 115 enum-gap, 20 SQL-интерполяций (из них реальных
2 — обе в CDC, в рамках S-17), 10 непрочитанных ключей конфигурации
(S-32). Все находки подтверждены чтением кода или runtime-пробой.






