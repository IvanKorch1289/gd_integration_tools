# ADR-0375 — Полнота покрытия настроек, merged-валидация профиля, константы из YAML, типизация секретов

* Статус: Accepted (2026-10-28, wave 14, финальный кластер CF4)
* Cycle: 174
* Дата: 2026-10-28
- **Затрагивает**: `config_profiles/base.yml`, `manage.py`,
  `src/backend/core/config/constants_settings.py` (новый),
  `src/backend/core/config/secret.py` (новый),
  `src/backend/core/config/validator/profile_merge.py` (новый),
  `src/backend/core/config/{security,ai,lineage,influxdb,rag,auth}.py`,
  `src/backend/core/config/services/{mail,storage,ldap,cache,jupyter_hub}.py`,
  `src/backend/core/config/base/__init__.py`,
  `tests/unit/core/config/**`
- **Связан с**: ADR-0371 (инварианты prod-профилей), ADR-0372 (приоритет
  источников и hot-reload), ADR-0373 (`.env` только секреты), ADR-0351
  (orphan-ключи конфигурации)

## Контекст

Read-only ревью настроек (волна 14) зафиксировало четыре разрыва между
кодом и конфигурацией:

1. **30 из 69 yaml-групп не имели секции в `base.yml`.** Часть групп —
   secret-only по замыслу, часть — функциональные параметры (`bge`, `llm`,
   `rag_cache`, `outbox`, `dlq`, `v11`, `websocket`, …), которые без
   правки кода настроить было невозможно: параметр жёстко зашит в дефолт
   модели.
2. **`manage.py validate-profile` проверял ТОЛЬКО overlay-файл.** Рантайм
   читает `base.yml` + overlay (`_deep_merge`), поэтому инварианты prod,
   объявленные в `base.yml` (`http.ssl_verify`, `vault.addr`,
   `graphql.enable_introspection`), валидатору были не видны — «зелёный»
   отчёт CLI не означал «эффективный конфиг валиден».
3. **`consts` (`core/config/constants.py`) — только код.** Retry/CB-дефолты
   (`INITIAL_DELAY`, `RETRY_DELAY`, `MAX_RESULT_ATTEMPTS`, `DEFAULT_CB_*`,
   `DEFAULT_RETRY_*`) нельзя было изменить без релиза; YAML/Consul-загрузки
   не было.
4. **Секреты — plain `str`.** ADR-0373 типизировал `database.py` и
   `mongo.py`; остальные ~44 секретных поля оставались строками, значение
   попадало в `repr()` модели и в логи.

## Решение

### (а) Покрытие yaml-групп

`config_profiles/base.yml` получил 25 новых секций (несекретные поля
только). Значения секций **равны дефолтам моделей** — подключение YAML не
меняет поведение, параметр просто становится конфигурируемым. Поля с
loopback-дефолтом (`influxdb.url`, `policy.opa_url`,
`websocket.allowed_origins`) намеренно не вынесены: иначе merged
prod/staging унаследовал бы dev-хост (ADR-0371, loopback-гейт).

Каждая yaml-группа теперь обязана иметь секцию в `base.yml` **или** быть
перечислена в `tests/unit/core/config/yaml_group_allowlist.txt` с явной
причиной (`profile-overlay-only` / `runtime-only`). Allowlist — не список
невыполненной работы, а фиксация проектного решения: `features` (262
per-profile флага) и `workflow` (модель без полей, extension point).

Итог: 70 yaml-групп (69 исходных + новая `constants`), 68 секций в
`base.yml`, 2 записи в allowlist.

### (б) Merged-валидация профиля

`src/backend/core/config/validator/profile_merge.py` собирает merged-конфиг
(base + overlay) так же, как это делает `YamlConfigSettingsLoader`, и
прогоняет по нему `ConfigValidator`. `manage.py validate-profile` теперь:
1. проверяет синтаксис overlay-файла;
2. сливает base + overlay;
3. проверяет prod-инварианты по **merged**-значениям;
4. прогоняет `ConfigValidator` и печатает нарушения (CRITICAL → exit 1,
   WARNING → exit 1 при `--strict`).

Секции собираются через `model_construct` — валидации нет, поэтому
отсутствующие секретные поля (`secret_key`, `password`) не роняют CLI.
Неполный профиль даёт Violation `profile.incomplete`, а не трейсбек.

### (в) Константы из YAML + hot reload

`ConstantsSettings(BaseSettingsWithLoader)` с `yaml_group="constants"`:
дефолты модели == значения `consts` (дефолты берутся из
`Constants.__dataclass_fields__`, а не из инстанса — иначе применённое
YAML-значение переписало бы дефолты модели при повторном импорте).

Применение override — мутация инстанса `consts` (ссылки потребителей
`consts.X` остаются валидными). Хук — `model_post_init` модели: он
срабатывает и при обычном создании, и при `model_construct`, и — главное —
при пересборке модульного синглтона в `Settings.reload()` (ADR-0372),
который пересоздаёт синглтоны **импортированных** модулей пакета
`core.config`. Поэтому модуль `constants_settings` обязан быть импортирован
при старте — это сделано в `core/config/base/__init__.py` (не в
`core/config/__init__.py`: пакет выполняется до инициализации
`core.logging`, а создание настроек в этот момент тянет логирование и даёт
циклический импорт).

**Consul для констант НЕ используется.** Роль Consul в проекте —
DSL-переменные (`core/dsl/variable_backend.py`) и cert_store. Константы
кода — не runtime-конфигурация сервиса, а параметры кода: их место в
YAML-профиле рядом с остальными настройками. Секретов в группе нет.

Предел: значения, схваченные в момент импорта модуля как default поля
dataclass'а (`BreakerConfig.failure_threshold = consts.DEFAULT_CB_FAILURE_THRESHOLD`),
перечитывают константу один раз — на импорте. «Горячими» остаются
потребители, читающие `consts.X` в момент вызова.

### (г) Типизация секретов

23 поля типизированы как `SecretStr` (ADR-0373/ADR-0375): `security`
(`secret_key`, `api_key`), `ai.py` (8 моделей: `api_key` ×8,
`credentials` ×2), `services/mail.py` (`password`), `services/storage.py`
(`access_key`, `secret_key`), `services/ldap.py` (`bind_password`),
`lineage.py` (`auth_token`), `influxdb.py` (`token`),
`services/jupyter_hub.py` (`api_token`), `rag.py` (`qdrant_api_key`,
`embedding_api_key`), `services/cache.py` (`password`, `sentinel_password`).
Итого по проекту `SecretStr` — 29 из 50 секретных полей (6 были типизированы
в CF3).

Читатели адаптированы минимально через
`src/backend/core/config/secret.py::secret_value` (терпим к `SecretStr`,
`str`, `None` и «утиным» SecretStr-подобным объектам). Публичные
контракты не сломаны: `AuthConfig.api_key`, `JwtConfig.secret_key`,
`redis_url`, S3-параметры и HTTP-заголовки остаются строками. Computed
field `redis_url` помечен `repr=False` — пароль не должен попадать в
`repr()` модели (тот же приём, что в `database.py`/`mongo.py`).

### Owner-задачи (21 секретное поле оставлено `str`)

* **`username` (8 полей)** — не является секретом в смысле ADR-0373
  (идентификатор, а не credential), но `config_audit` считает его
  секретом. Решение: типизация `username` — отдельная задача (нужен
  аудит 37 читателей и правка публичных контрактов).
* **`clickhouse.password`, `elasticsearch.{api_key,password}`,
  `express.{secret_key,signature_secret}`, `telegram.{secret_key,signature_secret}`,
  `vault.token`, `queue.password`, `mqtt.password`,
  `skb/dadata/huggingface.api_key`** — типизация требует правки читателей
  вне `core/config` (клиенты хранилищ, messaging, внешние API) и/или
  изменения публичных DTO. Оставлено как `str` — типизация выполняется
  отдельным кластером с обновлением контрактов.
* **`database.async_connection_url` / `mongo.connection_string`** — секрет
  попадает в `repr` через computed field (в `database.py`/`mongo.py`
  `repr=False` уже стоит — исправлено в CF3).

## Последствия

* Поведение рантайма не изменилось: значения новых секций == дефолты,
  типизация секретов сохраняет строковые контракты.
* `manage.py validate-profile prod` теперь честно видит merged-конфиг:
  prod даёт 0 CRITICAL и 1 WARNING (`waf.clamav_fail_open_in_prod` —
  значение из дефолта модели, до волны невидимое CLI).
* Появился новый гейт: любая yaml-группа без секции в `base.yml` и без
  записи в allowlist роняет `test_yaml_group_coverage.py`.
* `Settings.reload()` (ADR-0372) обновляет константы в рантайме —
  правка `config_profiles/*.yml` меняет retry/CB-дефолты без рестарта.
