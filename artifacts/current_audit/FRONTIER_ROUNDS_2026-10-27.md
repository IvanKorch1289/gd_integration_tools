# Frontier-раунды доработки (Cycle 172, Wave 13)

**Дата**: 2026-10-27
**Источник**: `RE_ANALYSIS_LOGGING_CACHE_FILES_S3_2026-10-27.md` (S-1…S-32)
**Метод**: grilling (frontier-раунды). Решения — владельца; факты — исполнителя.
**Режим**: auto-режим без интерактива → рекомендации приняты по умолчанию,
каждое помечено как «решено по рекомендации, пересматриваемо».

ADR-констрейнты, действующие во всех раундах:

- ADR-0284 §1.1 / ADR-0286 §3.3 — изменение ALLOWED-матрицы слоёв = отдельный ADR.
- ADR-0354 — DSL не импортирует `services.*` напрямую, только через DI-provider.
- ADR-0166 / ADR-0351 — единственный фасад логирования `core.logging.get_logger`.
- ADR-0112 — эталон безопасной идентификации = `_safe_ident()`-паттерн (allowlist),
  глобальный `# nosec B608` отклонён.
- ADR-0282 / ADR-0297a — allowlist = baseline долга, новые нарушения не добавляем.
- ADR-0335 / ADR-0336 — новые Settings обязаны пройти гейты unsafe-defaults и env-matrix.

---

## Раунд 1 — Q1–Q7: логирование / кэш / S3 / файлы

### ❓ Q1 — Уровень логов в проде: `DEBUG` вместо `INFO`

Факты: `config_profiles/base.yml:285` → `log.level: "DEBUG"`; `prod.yml:173-193` и
`staging.yml` секцию `log:` без `level` → наследуют `DEBUG`. Модель
`LogStorageSettings.level` — обязательное поле без дефолта; значение напрямую
становится `root_logger.setLevel(...)` (`structlog_backend.py:280-282`).
В проде это = шум + риск утечки внутренних полей в audit-события ClickHouse.

Варианты: (a) `prod.yml` → `level: "INFO"`; (b) `WARNING`; (c) добавить дефолт
`INFO` в модель и убрать `DEBUG` из `base.yml`.

➡️ **Рекомендация: (a) `prod.yml` → `INFO`, `staging.yml` → `INFO`,
`dev.yml`/`dev_light.yml` остаются `DEBUG`.** Дефолт в модели не меняем: `base.yml`
— единственный носитель дефолта, а ADR-0351/0097 говорят «конфиг не должен врать».
`WARNING` отклоняем: теряются `INFO`-события аудита и трассировки.

**Решено по рекомендации.** Реализация: Q1.

---

### ❓ Q2 — `required_fields` не проверяется: конфиг врёт

Факты: `base.yml:290-294` объявляет `required_fields: [environment, hostname,
user_id, action]`. Единственный потребитель — legacy-путь
`infrastructure/external_apis/logging_service.py:89-91` (SafeFormatter). В
structlog-пути (`structlog_backend.py:391-395`) биндятся только `environment` и
`hostname`; `user_id`/`action` — 0 совпадений. То есть в прод-пайплайне
декларация не исполняется.

Варианты: (a) реализовать контракт в structlog-пути (дозаполнять отсутствующие
поля); (b) удалить `required_fields` из `base.yml` (конфиг перестаёт врать, но
legacy-путь теряет гарантию наличия полей); (c) валидировать и падать.

➡️ **Рекомендация: (a).** Семантика legacy-пути — «поле всегда присутствует,
иначе `"unknown"`». Дублируем её в structlog-пайплайне: processor, который
дозаполняет отсутствующие поля из `required_fields`. (b) отклоняем — потеряем
функциональность legacy-пути; (c) отклоняем — падать на каждой записи без
`user_id` нельзя.

**Решено по рекомендации.** Реализация: Q2.

---

### ❓ Q3 — Capability-аудит не эмитится (корутина без `await`)

Факты: `AuditService.emit` — `async`. `core/audit/facade/_base.py:54` возвращает
корутину без `await` → `RuntimeWarning: coroutine 'AuditService.emit' was never
awaited`. Цепочка: `audit_mixin.py:90 → emit_capability_check → emit_audit → svc.emit`.
Второй путь (`self._audit` в `audit_mixin.py:71`) мёртв: `get_capability_gate()`
(`gate/__init__.py:149`) не передаёт `audit=` → `self._audit is None`.
Итог: **ни одно** capability-решение не попадает в unified audit-service.

Варианты: (a) сделать `emit_audit` sync-диспетчером: есть running loop →
`create_task` (fire-and-forget), нет loop → выполнить корутину до конца; (b)
перевести `emit_capability_check` в async и вызывать `await` из async-путей
(ломает sync-пути `CapabilityGate.check`); (c) подключить legacy-callback
(`audit=`), оставить unified-путь как есть.

➡️ **Рекомендация: (a).** `CapabilityGate.check` — sync, поэтому (b) невозможно
без переписывания 21 callsite. (c) отклоняем: unified audit-service — канон
(ADR-0071), дублировать канал нельзя. В sync-контексте без loop корутину надо
закрыть явно (иначе `RuntimeWarning`), а не молча терять событие.

**Решено по рекомендации.** Реализация: Q3.

---

### ❓ Q4 — `delete_by_tag` падает на RedisCluster (CROSSSLOT)

Факты: `infrastructure/cache/backends/redis.py:130` — один `delete(*str_keys)` по
всем ключам. В cluster-режиме клиент = `redis.asyncio.cluster.RedisCluster`
(`clients/storage/redis/connection_mixin.py:30-44`) → ключи из разных hash-слотов
→ `CROSSSLOT`. Тот же дефект в `RedisBackend.delete` (`redis.py:72`), а через него
— во всех вызывающих (facade, tenant_wrapper, tiered, idempotency-middleware).

Варианты: (a) удалять по одному ключу (`asyncio.gather` индивидуальных `DEL`) —
всегда cluster-safe; (b) батчинг по слоту с вычислением слота; (c) fan-out по нодам.

➡️ **Рекомендация: (a).** (b)/(c) требуют знания о topology и hash-слотов;
cluster-pipeline в redis-py сам роутит по ключу, но в тестах клиент — mock.
Индивидуальные `DEL` совместимы с любым клиентом. Потолок: N round-trip'ов —
компромисс в пользу cluster-корректности; апгрейд — pipeline с per-key командами
(требует не-mock клиента).

**Решено по рекомендации.** Реализация: Q4.

---

### ❓ Q5 — `cache_policy()` — маркер без эффекта и без предупреждения

Факты: `dsl/builders/policy_mixin.py:61-73` — `cache_policy()` только добавляет
policy-процессор; реального кэша не создаёт. Deprecated-шим `cache()`
(стр. 75-107) предупреждает `DeprecationWarning`, `cache_policy()` — нет: вызов
выглядит рабочим. ADR-0355: Option C (реальный cache через
`UnifiedCacheFacade`) отклонён «для cycle 170», может рассматриваться в cycle
180+ как **отдельный ADR**.

Варианты: (a) `RuntimeWarning` в `cache_policy()`; (b) реализовать реальный
кэш (требует отдельного ADR по ADR-0354/0355 + DI-провайдер); (c) удалить метод.

➡️ **Рекомендация: (a).** (b) — отдельный ADR и цикл; (c) ломает публичный API.
Warning должен называть канонический путь (`RouteBuilder.cache(...)`).

**Решено по рекомендации.** Реализация: Q5.

---

### ❓ Q6 — S3: presign проверяет `storage.read`; `infra_s3_get` обходит фасад

Факты:
- `services/storage/facade.py:240-242` — `presigned_url()` → `_assert_read(key)`
  → `storage.read`. Presigned-URL даёт клиенту **прямую запись** в бакет → нужна
  отдельная capability. Capability `storage.presign` в vocabulary отсутствует.
- `dsl/engine/processors/infra_s3.py:47-48` — `get_object_storage_class()(context)`
  + `storage.download(key)` → мимо `StorageFacade` → `_assert_read` не вызывается;
  `capabilities=("storage.read",)` в декораторе — метаданные без runtime-проверки.
- Проверено: **production-callers у `presigned_url` отсутствуют** (только фасад +
  tenant/fallback-обёртки), route-манифесты `storage.*` не декларируют → риск
  blanket-deny по presign отсутствует.

Варианты: (a) ввести `storage.presign` + требовать её в `presigned_url()`, и
перевести `infra_s3_get` на `StorageFacade`; (b) оставить `storage.read`;
(c) требовать `storage.write` для presign.

➡️ **Рекомендация: (a).** Отдельная capability = явный грант, fail-closed;
`storage.write` (c) неверен по смыслу (presign ≠ запись в бакет нашим аккаунтом).
ADR-обоснования у `storage.presign` нет → пишем новый ADR.

**Решено по рекомендации.** Реализация: Q6.

---

### ❓ Q7 — Файлы: allowlist только в env; сканеры его обходят

Факты:
- `dsl/engine/processors/_path_safety.py:25-33` — allowlist = env
  `DSL_ALLOWED_PATHS` (разделитель `:`), дефолт `/data/uploads`, `/data/exports`,
  `<tmp>/dsl`, `/var/data`. В `config_profiles/*` и `config/services/*` ключа нет
  → в контейнере без env переменной allowlist молча деградирует до дефолта.
- `validate_path` вызывается в **3** процессорах: `filereadprocessor.py:57`,
  `filewriteprocessor.py:69`, `rpa/operations/filedeleteprocessor.py:65`.
  **Не** вызывается в: `rpa/operations/filewatchprocessor.py`,
  `rpa/operations/filtereddirectoryscanprocessor.py`,
  `rpa/operations/filelistprocessor.py` (путь ещё и из тела запроса!),
  `dsl/engine/processors/file_watch.py` (ядро, 7 ФС-операций, `directory`
  может прийти из exchange-property),
  `dsl/engine/processors/fs_directory_scan.py` (путь из тела запроса),
  `rpa/operations/ftpuploadprocessor.py` (`local_path` читается напрямую).
- Место для конфига найдено: `core/config/dsl.py` (`DSLSettings`,
  `yaml_group="dsl"`, `env_prefix="DSL_"`); секции `dsl:` в `base.yml` нет.

Варианты: (a) allowlist → `settings.dsl.allowed_paths` (env остаётся override) +
`validate_path` ко всем ФС-процессорам; (b) только конфиг без расширения
покрытия; (c) только покрытие без переноса в конфиг.

➡️ **Рекомендация: (a).** Capability ограничивает *факт вызова*, но не *путь* —
path-allowlist и capability нужны оба. Env остаётся override (для контейнера).
Глобальный «жёсткий» allowlist для сканеров ломает легитимные RPA-сценарии
→ покрытие расширяем, а список — конфигурируем.

**Решено по рекомендации.** Реализация: Q7.

---

## Раунд 2 — Q8–Q12: БД / CDC / драйверы

### ❓ Q8 — `clickhouse_connect` не объявлен: 4 из 6 мест падают `ModuleNotFoundError`

Факты: пакет импортируется в 6 местах `src/` (`clickhouse_audit_service/service.py:119`,
`workflows/saga_history.py:40`, `hitl_history.py:64`, `cost_estimator.py:77`,
`scheduler/cron_dashboard_service.py:49`, `infrastructure/clients/storage/clickhouse_admin_client.py:45`);
в `pyproject.toml` объявлен только как mypy-override (строки 1044-1045). Fallback есть
лишь в 2 из 6 (широкий `except Exception` → молчаливая деградация).
Ограничение: lock-файл менять нельзя без согласования (AGENTS.md, Sprint 36).

➡️ **Рекомендация: (a) объявить зависимость + (b) деградация по доменной семантике
+ (c) закрыть класс «висячих зависимостей» гейтом.** (a) отклоняем — lock-чанж вне
цикла; (b) audit → fail-loud с доменной ошибкой, дашборд/админка → деградация;
(c) `tools/check_declared_dependencies.py` + allowlist (78 записей долга).

**Решено по рекомендации.** Реализация: Q8 + ADR-0363.

---

### ❓ Q9 — DSN обещает несуществующие драйверы (`psycopg2`, `pyodbc`)

Факты: `core/config/database.py:74` — дефолт sync-драйвера PG = `psycopg2` (не
объявлен, не установлен; установлен psycopg3 `psycopg`); `:252-254` — MSSQL sync =
`pyodbc` (не объявлен, не установлен); extra `db_drivers` = `oracledb`/`aioodbc`/`aiomysql`.

➡️ **Рекомендация: (a) дефолт → `psycopg` (psycopg3, sync+async); (b) fail-fast на
необъявленный/неустановленный драйвер вместо `ModuleNotFoundError`; (c) `pyodbc` в
extra — отдельная owner-задача (lock-чанж).**

**Решено по рекомендации.** Реализация: Q9 + ADR-0363.

---

### ❓ Q10 — Внешний enum обещает 7 типов БД, реализовано 2

Факты: `core/enums/database.py:6-26` — общий enum на 7 типов; внутренняя БД
(`core/config/database.py:215-288`) поддерживает все 7 (ADR-0189), внешний контур
(`core/config/external_databases/connection.py:151-175`) — только postgresql/oracle,
ошибка всплывает лишь при подключении.

➡️ **Рекомендация: (a) fail-fast на этапе конфигурации** — валидатор типа профиля
отвергает неподдерживаемые типы с понятным сообщением; общий enum НЕ сужать
(внутренняя БД их поддерживает); (b) удаление значений из enum — отклоняем.

**Решено по рекомендации.** Реализация: Q10.

---

### ❓ Q11 — CDC: имена таблиц/колонок подставляются в SQL без валидации (S-17)

Факты: `infrastructure/clients/external/cdc/strategies.py:127-129` (`table`,
`timestamp_column`) и `:323,334` (LogMiner, подстановка в строковые литералы);
`CDCSubscription` — plain dataclass без валидации; значения приходят из DSL-конфига и
из REST `POST /api/v1/cdc/subscriptions`. Эталон — ADR-0112 (allowlist-идентификаторы).

➡️ **Рекомендация: (a) allowlist-валидация в слое infrastructure + fail-fast в
`subscribe()`; (b) escape строковых литералов LogMiner; (c) валидатор — локально
(infrastructure не может импортировать services — инверсия слоёв).**

**Решено по рекомендации.** Реализация: Q11 + Q11b (`infrastructure/cdc/poll_backend.py`)
+ ADR-0360.

---

### ❓ Q12 — Capability для CDC: объявлять или нет?

Факты: `cdc_capture`/`cdc_transform` без `required_capability`; capability вида `cdc.*`
в vocabulary нет. **Runtime-проверка (Q12-факт) показала: `BaseProcessor.auth_check`
ведёт в `AuthorizationGateway.check` (sync), где единственный allow-источник — exact
in-memory policy; Casbin/OPA sync-хуков нет, `CapabilityGate.check` в этом пути не
вызывается → фактический deny для ЛЮБОГО `required_capability`.**

➡️ **Рекомендация: (a) НЕ объявлять capability** — добавление `required_capability`
сделало бы процессор нерабочим (deny-all); (b) риск инъекции закрыт Q11; (c) сам
разрыв enforcement'а — отдельный ADR + owner (ADR-0361).**

**Решено по рекомендации.** Реализация: Q11 (+ ADR-0361 на разрыв).

---

## Раунд 3 — Q13–Q15: внутренняя БД / allowlist

### ❓ Q13 — `infra_db_query`: произвольный SQL без capability и без валидации (S-27, критическая)

Факты: `dsl/engine/processors/infra_db.py:41-51` — `session.execute(self.sql)` без
`text()` (→ `ObjectNotExecutableError`) и `sm.session()` (не существует → `AttributeError`);
`required_capability` не задан; шаг достижим из YAML. Прецеденты проекта: `script_runner`
отключён целиком (RCE), `db_call_procedure` — за feature-флагом.

➡️ **Рекомендация: (a) fail-closed feature-флаг `infra_db_query_enabled` (default OFF,
стиль `script_runner`); (b) рабочее исполнение `text()` + bind-параметры + `create_session()`;
(c) канонический `_validate_sql` (multi-statement + DDL/GRANT/REVOKE) — общий модуль вместо
трёх копий; (d) capability НЕ добавлять (см. Q12).**

**Решено по рекомендации.** Реализация: Q13 + ADR-0359.

---

### ❓ Q14 — Внешняя БД: `db_query_external` и `duckdb_query` без SQL-guard

Факты: `db_query_external.py:111` — произвольный SQL к внешней БД без `_validate_sql`
(в `jdbc_query` guard есть); `duckdb_query.py:98` — произвольный SQL к embedded DuckDB
(ФС-доступ из SQL: `read_csv`/`COPY TO`/`ATTACH` — риск не ниже сетевой БД).

➡️ **Рекомендация: (a) тот же канонический guard в оба процессора; (b) feature-флаг
не вводим (ClickHouse/DuckDB — аналитика, guard достаточен); (c) capability не добавляем.**

**Решено по рекомендации.** Реализация: Q14 + Q14b (`infra_clickhouse`) + ADR-0359.

---

### ❓ Q15 — Декоративные capability-декларации + разрыв enforcement'а

Факты: 138 деклараций `capabilities=` без runtime-проверки (зонд аудита); рабочий
предикат — `required_capability`; **но он = deny-all** (см. Q12). Гейтов на этот класс
в репозитории нет.

➡️ **Рекомендация: (a) НЕ расширять capability-охват до починки enforcement-пути;
(b) закрыть класс гейтом `tools/check_decorative_capabilities.py` + allowlist (фактический
baseline — 45, а не 138: 138 — широкое предикатное число зонда); (c) разрыв
`auth_check → sync gateway без policies/Casbin/OPA/CapabilityGate` — отдельный ADR
(ADR-0361) с владельцем.**

**Решено по рекомендации.** Реализация: Q15 + ADR-0361.

---

## Раунд 4 — Q16–Q18: конфиг / инъекция

### ❓ Q16 — Механизм тихого отбрасывания YAML-ключей

Факты: `core/config/config_loader.py:198` — ключи вне `model_fields` отбрасываются
молча (`extra="forbid"` на YAML не действует: фильтр до валидации); ошибка загрузки
конфига тоже глушится (`__call__` → `_handle_error` → `{}` → деградация в дефолты).
Инструмент `tools/config_audit.py` существует, даёт exit 1 и НЕ подключён к CI.

➡️ **Рекомендация: (a) WARNING о отброшенных ключах вместо тишины (fail-loud в рантайме
отклоняем — падение старта из-за лишнего ключа опаснее); (b) `config_audit` как гейт:
orphan-класс блокирует, missing-класс — отдельный дефект и не блокирует;
(c) подключение к make + CI; (d) allowlist-база.**

**Решено по рекомендации.** Реализация: Q16 + ADR-0362.

---

### ❓ Q17 — 10 мёртвых ключей в `base.yml` (+ 3 в `prod.yml`)

Факты: `http3:` — секция без модели (HTTP/3 живёт в `app:`); `mcp.http_path` →
правильное поле `bind_path`; `mcp.sse_enabled/stdio_enabled/bind_host/bind_port` —
в модели нет и в коде не читаются; `mqtt.require_client_auth/bind_host/bind_port` —
в модели нет (MQTT здесь клиент); `queue_consumer_max_prefetch` (top-level) —
дубликат `queue.consumer_max_prefetch`; `log.compression_brotli/gzip_*` — читаются
middleware'ом как `settings.app.*`.

➡️ **Рекомендация: (a) удалить мёртвые ключи, (b) переименовать/перенести живые
(`mcp.bind_path`, `queue.consumer_max_prefetch`, `log.* → app.*`), (c) результат:
0 orphan-issue по 4 профилям (было 27-30).** Побочный эффект (фиксируется в ADR):
prod теперь РЕАЛЬНО включает Brotli и gzip 512/6 — раньше значения игнорировались.

**Решено по рекомендации.** Реализация: Q17 + ADR-0362.

---

### ❓ Q18 — SQL-инъекция через подставляемые имена

Факты: `sqlite_doc_store.py:160` — ключ фильтра в JSON-path (payload `x') OR 1=1 OR ('1'='1`
обходит WHERE — runtime-доказательство аудита); `search_chain.py:53,57` — `index` без
валидации (идёт в имя файла и FTS-таблицы); `immutable_audit.py` — `table_name` без
валидации. Плюс 6 кандидатов, найденных при инвентаризации (clickhouse insert/bulk
writer/query builder, dlq cleanup_job, inbox_writer, слабая проверка в `storage_ext`).

➡️ **Рекомендация: (a) allowlist-валидация идентификаторов (ADR-0112) во всех местах;
(b) канонический helper в `core/utils/sql_identifiers.py` (core — единственный слой,
доступный и infrastructure, и dsl); (c) точечные `# nosec B608` с обоснованием вместо
модульных suppress'ов (глобальный suppress отклонён); (d) `SqliteDocStore` не удаляем —
задокументированный dev/test-бэкенд.**

**Решено по рекомендации.** Реализация: Q18 + Q18b (6 кандидатов).

---

## Итог по раундам

| Раунд | Вопросы | Реализовано | ADR |
|---|---|---|---|
| 1 | Q1–Q7 (лог/кэш/S3/файлы) | 7 (+2 follow-on: CROSSSLOT в raw-клиентах, `supports_presigned`) | ADR-0357, ADR-0358 |
| 2 | Q8–Q12 (БД/CDC/драйверы) | 5 (+2 follow-on) | ADR-0360, ADR-0363 |
| 3 | Q13–Q15 (внутренняя БД/allowlist) | 3 | ADR-0359, ADR-0361 |
| 4 | Q16–Q18 (конфиг/инъекция) | 3 (+1 follow-on: 6 SQL-кандидатов) | ADR-0362 |

Открытые owner-задачи (вне цикла, требуют согласования): объявление
`clickhouse_connect` и `pyodbc` в extra (lock-чанж, Sprint 36); починка
enforcement-пути `required_capability` (ADR-0361); покрытие `.env.example`
(968 переменных Settings vs 57 задокументированных).

---

# Согласование открытых задач (гриллинг, раунды 1–2)

Отдельный гриллинг-проход по открытым задачам после закрытия Wave 13.
Решения — владельца; факты — исполнителя. `AskUserQuestion` в auto-режиме
недоступен → раунд оформлен планом (`plans/lockjaw-warpath-kate-bishop.md`),
одобрение получено через ExitPlanMode.

## Раунд 1 (независимые)

| Q | Вопрос | Решение | Статус |
|---|---|---|---|
| Q1 | Что делать с диффом Wave 13 (140 файлов)? | Разбить на ~14 атомарных коммитов по доменам | ✅ выполнено |
| Q2 | Разрешён ли lock-чанж (`clickhouse_connect` + `pyodbc`)? | Да, объявить оба | ✅ выполнено |
| Q3 | Чинить ли enforcement-путь `required_capability` (ADR-0361)? | Отложить: глобальная семантика авторизации → отдельный ADR + владелец | ⏸ отложено (G12) |
| Q4 | Конфиг-долг (`.env.example`, missing-secret)? | Оставить неблокирующим: matrix-гейт уже exit 0, 27 unknown — advisory | ⏸ отложено |

**Факты, изменившие решения:**
- `uv lock --check` проходит (679 → 681 пакет после объявления) — lock-чанж
  технически выполним; правка `pyproject.toml` + `uv.lock` выполнена.
- `tools/check_env_example.py --matrix` → **exit 0**: требуемые секреты
  задокументированы (часть ADR-0336 устарела). Остались 27 unknown (только при
  `--strict`) и 910 не-секретных переменных без документации — объём отдельной
  инициативы, не блокер.
- `tools/check_dsn_drivers.py` **не был подключён** к CI и давал exit 1 из-за
  availability-части → добавлено разделение scope (как в `config_audit`).

## Раунд 2 (зависимые)

| Q | Вопрос | Решение | Статус |
|---|---|---|---|
| Q5 | Мёртвый код — удалять? | Удалить `execute_with_resilience`, `FileSearchProcessor`, `capabilities_for`; `SqliteDocStore` и `InboxDLQWriter` оставить (аудит ошибся) | ✅ ADR-0364 |
| Q6 | Консолидация allowlist-хелперов | Свести к `core/utils/sql_identifiers.py`; `services/io/external_database` — отдельная задача (смена типа исключения) | ✅ ADR-0365 |
| Q7 | Флаг `infra_db_query_enabled` | Оставить OFF до починки enforcement-пути | ✅ зафиксировано в ADR-0359 |
| Q8 | DuckDB/PG-файловые команды | Расширить guard: `ATTACH/DETACH/COPY/INSTALL/LOAD/EXPORT/IMPORT` + файловые функции | ✅ ADR-0359 (дополнение) |
| Q9 | `check_dsn_drivers` в CI | Подключать после Q2, блокирующий scope = declarations | ✅ `--scope declarations` |

## Новые ADR

| ADR | Тема |
|---|---|
| ADR-0363 (дополнение) | объявление `clickhouse_connect`/`pyodbc` — выполнено, G11 частично закрыт |
| ADR-0364 | удаление мёртвого кода Wave 13 |
| ADR-0365 | единый канон валидации SQL-идентификаторов |
| ADR-0359 (дополнение) | расширение SQL-guard файловыми командами и функциями |

## Итог

Открытых задач, требующих решения владельца, не осталось. Остались
зафиксированные follow-up'ы: `ibm_db_sa` (проприетарный), перенос
`psycopg[binary]` в `db_drivers`, починка enforcement-пути (G12), канонизация
`services/io/external_database` (6 копий `_IDENT_RE`), документирование 910
переменных в `.env.example`.

