# ADR-0419 — JWKS-hardening, Jinja2 sandbox, безопасный pickle и маскирование DSN (волна 24, кластер F4)

* Статус: Accepted (2026-11-02, волна 24, кластер F4 — прочая безопасность и маскирование)
* Cycle: 183 (волна 24)
* Связан с:
  - ADR-0411 (RS256/JWKS: асимметричный режим JWT и контракт ротации),
  - ADR-0412 (sidecar-DNS и endpoint-контракты — `clamd` в prod по service-DNS),
  - ADR-0378/ADR-0381 (маскирование секретов в дампах настроек),
  - ADR-0385 (env-ключи с наследованием — `SEC_*`),
  - ADR-0112/ADR-0365 (allowlist-валидация SQL-идентификаторов),
  - ADR-0382 (диалектные особенности UPSERT: MySQL/backticks, Oracle MERGE)
* Затрагивает:
  - `src/backend/core/auth/jwks_cache.py`,
  - `src/backend/core/config/security.py`, `src/backend/core/di/providers/auth.py`,
  - `src/backend/dsl/engine/processors/template_engine.py`,
  - `src/backend/dsl/engine/processors/eip/marshal/formats.py`,
  - `src/backend/core/config/external_databases/connection.py`,
  - `src/backend/infrastructure/sources/cdc_postgres_logical.py`,
  - `src/backend/dsl/engine/processors/db_crud.py`,
  - `config_profiles/prod.yml`,
  - `tests/unit/core/auth/test_jwks_cache.py`,
    `tests/unit/dsl/engine/processors/test_template_engine.py`,
    `tests/unit/dsl/engine/processors/eip/test_marshal_pickle_security.py`,
    `tests/unit/core/config/external_databases/test_connection_safety.py`,
    `tests/unit/dsl/engine/processors/test_cdc_postgres_logical.py`,
    `tests/unit/dsl/engine/processors/test_db_crud.py`,
    `tests/unit/core/config/test_adr0419_clamav_fail_open_prod.py`,
    `tests/unit/infrastructure/test_external_db_replica.py`

---

## Контекст

Мультироевой аудит (волна 24, кластер F4) нашёл в «прочей безопасности и
маскировании» семь находок разного класса:

1. **JWKS: бессрочный stale-fallback + отсутствие HTTPS/SSRF-проверки.**
   `core/auth/jwks_cache.py` при недоступности IdP возвращал последний
   успешно полученный JWKS **бессрочно**: отозванный `kid` оставался
   валидным, пока IdP не отдаст новый документ. `jwks_url` при этом шёл
   в `OutboundHttpClient` без `url_guard` и без требования HTTPS — то есть
   «тихий» downgrade на `http://` был возможен, а SSRF-вектор (metadata
   endpoint, loopback) не был отсечён.
2. **SSTI в DSL-шаблонщике.** `dsl/engine/processors/template_engine.py`
   рендерил через `jinja2.Template` **без sandbox**, тогда как
   `rpa/operations/templaterenderprocessor.py` и `html_template.py` уже
   использовали `SandboxedEnvironment`. Шаблон приходит из DSL-описания
   маршрута → `{{ ''.__class__.__mro__ }}` = чтение произвольных
   атрибутов и вызов кода.
3. **`pickle.loads` в DSL-достижимом формате.** `eip/marshal/formats.py`
   (`PickleDataFormat.unmarshal`) использовал обычный `pickle.loads` —
   полный RCE через `__reduce__`. Формат `pickle` достижим из DSL
   (`marshal`/`unmarshal` EIP), то есть payload мог прийти извне. В
   проекте уже есть канон — `core/security/restricted_unpickler.py`
   (whitelist модулей), но он в marshal не применялся.
4. **`waf.clamav_fail_open: true` в prod.** В `config_profiles/base.yml`
   стояло `clamav_fail_open: true`, prod-профиль это не переопределял →
   `manage.py validate-profile prod` давал 1 WARNING
   (`waf.clamav_fail_open_in_prod`): при недоступном clamd исходящие
   запросы проходили без AV-сканирования.
5. **Внешний `replica_dsn` не маскировался.** В
   `core/config/external_databases/connection.py` поле было plain `str`
   (в отличие от main-БД: `SecretStr` + `@field_serializer`,
   `core/config/database.py`). Проба: `model_dump()` →
   `postgresql+asyncpg://user:SUPERSECRET@...` — пароль реплики утекал в
   дамп настроек (и в admin-эндпоинт конфигурации).
6. **`CdcPostgresLogicalSource` не валидировал идентификаторы.**
   `table`/`slot_name`/`publication` попадали в DDL через f-string
   (`CREATE PUBLICATION {publication} FOR TABLE {table}`,
   `pg_create_logical_replication_slot('{slot}', ...)`) без
   allowlist-проверки. Класс в `src/` не инстанцируется (латентно), но
   конструктор публичный.
7. **MySQL UPSERT использовал deprecated `VALUES(col)`.**
   `db_crud.py::build_upsert_sql_mysql` — `VALUES(col)` deprecated с
   MySQL 8.0.20 и удалена в 8.4.

---

## Решение

### 1. JWKS: предельное окно stale + HTTPS-only (+ SSRF-guard)

* `JwksCache` получил параметр `max_stale_seconds` (по умолчанию
  `DEFAULT_MAX_STALE_SECONDS = 600` — консервативное окно). Stale-кеш
  допустим **не дольше** этого окна после истечения TTL; за пределами
  окна `_refresh` бросает `JwksFetchError` (fail-closed) — отозванный
  `kid` больше не остаётся валидным бессрочно. `0` — полностью без
  stale-fallback. Успешный refresh отсчитывает окно заново.
* URL проверяется **на конструкторе** (`_validate_jwks_url`):
  непустой, схема строго `https` (иначе — `JwksConfigurationError`,
  то есть ошибка конфигурации, а не молчаливый downgrade), плюс
  канонический SSRF-guard `core.net.url_guard.assert_safe_url(...,
  allow_private=True)` — отсекаются metadata-endpoint'ы и loopback-имена;
  внутренние IdP (single-label / private-IP) допускаются, так как URL —
  операторская конфигурация.
* Настройка `security.jwks_max_stale_seconds` (`SecureSettings`, env
  `SEC_JWKS_MAX_STALE_SECONDS`) пробрасывается в кеш через
  `core/di/providers/auth.py::_build_jwks_cache_or_none`.

### 2. Jinja2: `SandboxedEnvironment` вместо `Template`

`RenderTemplateProcessor` и `RenderTemplateFileProcessor` переведены на
`jinja2.sandbox.SandboxedEnvironment` (`autoescape=True` сохранён).
Sandbox блокирует доступ к «небезопасным» атрибутам (`__class__`,
`__globals__`, `__mro__`): `{{ ''.__class__ }}` больше не отдаёт
`<class 'str'>`, а `{{ ''.__class__.__mro__ }}` → `SecurityError` →
`exchange.error`. Обычные шаблоны не изменились.

### 3. Pickle: `restricted_unpickler.safe_loads`

`PickleDataFormat.unmarshal` десериализует через
`core.security.restricted_unpickler.safe_loads` (whitelist модулей:
`builtins`, `collections`, `datetime`, `dataclasses`, …). Класс вне
whitelist'а → `pickle.UnpicklingError` (fail-closed), произвольный код
не выполняется. `marshal` (сериализация) не изменён.

### 4. prod: `waf.clamav_fail_open: false`

`config_profiles/prod.yml` переопределяет `clamav_fail_open: false`
(fail-closed) — `validate-profile prod` → 0 CRITICAL, 0 WARNING.
**Осознанное решение по «неразрешимому конфликту»:** конфликта нет.
В prod `clamd` — развёрнутый sidecar (`waf.clamav_host: "clamd"`,
service-DNS, `deploy/k8s/service.yaml`), поэтому «clamd недоступен» —
не штатный режим, а инцидент, и цена правильной реакции (блокировка
исходящих запросов) ниже цены молчаливого пропуска сканирования.
Escape-hatch для платформ без clamd — **явный**
`waf.clamav_enabled: false`: сканер не подключается вовсе, и
`fail_open` становится нерелевантным (в этом режиме валидатор
warning'а не выдаёт). Это выбор, а не молчаливый fail-open.

### 5. Внешний `replica_dsn` → `SecretStr` + маскирование

`ExternalDatabaseConnectionSettings.replica_dsn` типизирован
`SecretStr | None`; добавлены `@field_serializer` для самого поля и для
computed-поля `replica_async_connection_url` — в `model_dump()` /
`model_dump_json()` пароль заменён на `***`
(`mask_url_password`). Рабочее значение доступно через
`get_secret_value()`; инициализатор движка реплики уже умеет работать с
`SecretStr` (`_reveal_dsn`).

### 6. CDC: allowlist-валидация идентификаторов

`CdcPostgresLogicalSource.__init__` валидирует `table`, `slot_name`
(по умолчанию `cdc_<table>`) и `publication` (по умолчанию `pub_<table>`)
каноническим `core.utils.sql_identifiers.validate_identifier`
(`[A-Za-z_][A-Za-z0-9_]*`) — fail-fast на конструкторе, до обращения к
БД. Квалифицированные имена (`public.orders`) отклоняются: имя
publication/slot из них строить нельзя, а `CREATE PUBLICATION` требует
голый идентификатор.

### 7. MySQL UPSERT: row-alias вместо `VALUES(col)`

`build_upsert_sql_mysql` строит
`INSERT INTO t (...) VALUES (...) AS new ON DUPLICATE KEY UPDATE c = new.c`
(row-alias доступен с MySQL 8.0.19). Попутно исправлен no-op-клауз:
вместо невалидного `c = c` (ссылка на несуществующую колонку) —
`conflict_key = new.conflict_key`.

---

## Альтернативы

* **Оставить stale-fallback бессрочным.** Отклонено: именно это и было
  находкой — отозванный ключ продолжал бы приниматься неограниченно
  долго. Компромисс «лучше старый JWKS, чем 5xx» сохранён, но он
  ограничен явным окном (10 минут по умолчанию) и настраивается.
* **Запретить stale-fallback полностью.** Отклонено: при кратковременной
  недоступности IdP это превращается в полный отказ верификации JWT.
  Fail-closed без окна — это режим `max_stale_seconds=0`, он доступен.
* **Проверять JWKS URL по `assert_safe_url(..., allow_private=False)`.**
  Отклонено: сломал бы внутренние IdP (single-label хосты и private-IP)
  и приводил к отказу на старте приложения. Выбран `allow_private=True`:
  блокируются metadata-endpoint'ы и loopback-имена, а HTTPS-only
  закрывает классический plain-HTTP SSRF на metadata.
* **Валидировать JWKS URL только в `HttpJwksFetcher`.** Отклонено:
  ошибка обнаружилась бы уже при первом запросе, а не при старте.
  Fail-fast на конструкторе — «ошибка конфигурации», как требовал аудит.
* **Оставить `pickle`, но потребовать «trusted provenance» от
  вызывающего.** Отклонено: «проверьте, что данные доверенные» —
  непроверяемое требование; формат достижим из DSL, значит payload может
  прийти извне. Канон `restricted_unpickler` уже есть в проекте —
  применён.
* **Отклонить формат `pickle` целиком.** Отклонено: формат нужен
  round-trip'у внутри кластера; whitelist-десериализация закрывает RCE
  без отказа от фичи.
* **В prod оставить `fail_open: true` и закрыть warning в валидаторе.**
  Отклонено: warning прав — поведение реально fail-open; менять надо
  конфигурацию, а не валидатор (валидатор вне зоны кластера).
* **`AS new` в UPSERT vs `ON DUPLICATE KEY UPDATE c = new.c` для MySQL
  < 8.0.19.** Отклонено: MySQL < 8.0.19 вне поддерживаемого контура
  (ADR-0407/ADR-0412 — современный стек); `VALUES()` в 8.4 удалена.

---

## Последствия

* Отозванный `kid` перестаёт быть валидным бессрочно: предельное окно
  stale (по умолчанию 600 с) настраивается
  `security.jwks_max_stale_seconds` / `SEC_JWKS_MAX_STALE_SECONDS`.
* `jwks_url` вида `http://...` больше не «работает молча» — приложение
  падает на старте с `JwksConfigurationError`. Для внешних развёртываний
  с `http://` IdP это изменение поведения (требуется HTTPS).
* Внутренние IdP, доступные по `https` (в т.ч. single-label/private-IP),
  продолжают работать; `localhost`/`metadata.*` как хост JWKS — отклонены.
* DSL-шаблоны рендерятся в sandbox: шаблоны, полагавшиеся на доступ к
  «приватным» атрибутам объектов, перестанут работать (в проекте таких
  шаблонов нет).
* `pickle`-формат marshal больше не десериализует произвольные классы:
  payload с кастомным классом → `UnpicklingError` (в проекте
  round-trip использует только dict/list/str/дата-время).
* Пароль внешнего `replica_dsn` больше не утекает в `model_dump()` и
  admin-эндпоинт конфигурации; рабочее значение не изменилось.
* `CdcPostgresLogicalSource` принимает только «простые» идентификаторы
  (без `schema.`-квалификации) — класс латентный, потребителей в `src/`
  нет.
* MySQL UPSERT требует MySQL ≥ 8.0.19 (row-alias).
* Линтер слоёв: новых межслойных импортов нет (`core/auth → core/net`,
  `dsl → core/security`, `infrastructure → core/utils` — core→core и
  нижние слои), baseline `tools/check_layers.py --strict` остался 41.

---

## Проверка

* `tests/unit/core/auth/test_jwks_cache.py` — HTTPS-only (http/ftp/пусто →
  `JwksConfigurationError`), SSRF-guard (metadata-хост отклонён), https
  принимается; stale-окно: внутри окна — stale отдаётся, за окном —
  `JwksFetchError`, `max_stale_seconds=0` — fallback выключен, успешный
  refresh продлевает окно.
* `tests/unit/dsl/engine/processors/test_template_engine.py` — SSTI:
  `__class__` не утекает, `__mro__`/`__globals__` → `exchange.error`
  (SecurityError), файловый шаблон — тоже sandbox; обычные шаблоны
  работают.
* `tests/unit/dsl/engine/processors/eip/test_marshal_pickle_security.py` —
  `__reduce__`-payload отклонён (`UnpicklingError`), dict/list/datetime
  десериализуются, round-trip marshal работает.
* `tests/unit/core/config/external_databases/test_connection_safety.py` —
  пароль `replica_dsn` маскируется в `model_dump()`/`model_dump_json()`,
  computed-поле `replica_async_connection_url` — тоже; рабочее значение
  доступно.
* `tests/unit/dsl/engine/processors/test_cdc_postgres_logical.py` —
  небезопасные `table`/`slot_name`/`publication` отклоняются (в т.ч.
  квалифицированные имена).
* `tests/unit/dsl/engine/processors/test_db_crud.py` — MySQL UPSERT:
  `VALUES(col)` не используется, есть `AS new` и `c = new.c`, no-op-клауз
  валиден.
* `tests/unit/core/config/test_adr0419_clamav_fail_open_prod.py` — в prod
  `clamav_fail_open is False`, warning'а валидатора нет; base остаётся
  fail-open; при `clamav_enabled: false` warning не выдаётся.
* Гейты: `ruff check`/`ruff format` — чисто по моим файлам;
  `manage.py validate-profile prod` → 0 CRITICAL, 0 WARNING;
  `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` → 41 (baseline не изменился);
  `tools/checks/mypy_budget.py` → OK; `tools/check_docstrings.py` → 0
  missing; `mypy` по изменённым исходникам → Success.

---

## Открытое (owner-задачи)

1. **Прод-конфигурация JWKS.** Владелец: безопасность/платформа.
   Критерии: в prod задан `security.jwks_url` по **https**;
   `security.jwks_max_stale_seconds` выбран осознанно (окно не длиннее
   максимального времени отзыва ключа в IdP); JWKS-endpoint доступен из
   контура приложения; процедура отзыва `kid` (ADR-0411) учитывает окно
   stale. **Проверить фактические HTTPS-URL у заказчика** — старые
   `http://`-конфигурации теперь падают на старте.
2. **ClamAV в prod.** Владелец: эксплуатация/платформа. Критерии:
   sidecar `clamd` развёрнут и доступен по service-DNS `clamd` (иначе
   — явное `waf.clamav_enabled: false` в prod, а не тихий fail-open);
   алерт на недоступность clamd (fail-closed → исходящие запросы
   блокируются).
3. **Внешние БД с `replica_dsn`.** Владелец: эксплуатация. Критерии:
   для внешнего контура `replica_dsn` (если используется) задан
   фактический DSN; в дампах/логах пароль не виден (проверено тестом).
4. **Индекс ADR.** `docs/adr/INDEX.md` не редактировался (правило
   кластера) — индекс перегенерируется отдельной операцией
   (`tools/generate_adr_index.py`).

---

## Связи

* ADR-0411 — RS256/JWKS: источник ключа и контракт ротации (`kid`).
* ADR-0412 — sidecar-DNS: `clamd` в prod адресуется по service-DNS.
* ADR-0378/ADR-0381 — маскирование секретов в дампах настроек
  (`SecretStr` + `@field_serializer`).
* ADR-0385 — env-ключи с наследованием: `SEC_JWKS_MAX_STALE_SECONDS`.
* ADR-0112/ADR-0365 — allowlist-валидация SQL-идентификаторов
  (`core.utils.sql_identifiers`).
* ADR-0382 — диалектные особенности UPSERT (MySQL/backticks).
* `core/security/restricted_unpickler.py` — канон безопасной
  десериализации pickle (whitelist модулей).
* `core/net/url_guard.py` — канон SSRF-политики для исходящих URL.
* `core/utils/sql_identifiers.py` — канон валидации SQL-идентификаторов.
