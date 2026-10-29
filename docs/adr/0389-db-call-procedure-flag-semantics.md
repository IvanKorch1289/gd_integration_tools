# ADR-0389 — Семантика флага `db_call_procedure_enabled`: отключение должно быть явным

* Статус: Accepted (2026-10-29, wave 17, кластер T4 — «db_call_procedure: ФЛАГ ВЫКЛЮЧЕН, ПРОФИЛИ С ПРОЦЕДУРАМИ»)
* Cycle: 177
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/dsl/engine/processors/db_call_procedure.py` (сообщения флага)
  - `src/backend/core/config/features/sprint5_dsl.py` (описание флага)
  - `src/backend/core/config/validator/profile_merge.py` (инвариант профиля)
  - `routes/hello_route/route.toml`, `routes/test_route_w1/route.toml` (комментарии)
  - `docs/config/SETTINGS_GUIDE.md`, `docs/integration/INTEGRATION_GUIDE.md`
  - `tests/unit/dsl/engine/processors/test_db_call_procedure.py`
  - `tests/unit/core/config/test_profile_db_call_procedure_flag.py` (новый)
- **Связан с**:
  - ADR-0380 (SQL-инъекция и fail-closed в `db_call_procedure`; default-OFF)
  - ADR-0365 (канон `validate_identifier`; `db_schema` профиля внешней БД)
  - ADR-0359 (канонический SQL-guard `validate_sql`)
  - ADR-0364 (мёртвая конфигурация = ложь в конфиге)
  - ADR-0375 (merged-валидация профиля)
  - ADR-0385 (секции БД валидируются моделями; DSN и креды внешних БД)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/dsl/builders/transport/persistence.py` — builder-метод
    `.db_call_procedure()` не проверяет флаг сам (проверка живёт в
    процессоре, шаг общий для YAML- и builder-пути);
  - `tools/checks/feature_flag_registry.toml` — реестр флагов: у
    `db_call_procedure_enabled` просроченный `expires` (2026-10-22) и
    placeholder-owner; гейт `check_feature_flag_debt.py --strict` уже красный
    по 122 флагам (pre-existing), правка реестра — вне зоны кластера;
  - `config_profiles/{dev,dev_light}.yml` — включать флаг в профили нельзя:
    ни один роут не вызывает процедуры, а `dev.yml` объявляет внешние БД →
    профиль получает WARNING (видимость вместо лишнего включения флага).

## Контекст

Волна 16 (ADR-0380) перевела `db_call_procedure_enabled` в `default=False`
и сделала чтение флага fail-closed. Остались три разрыва, из-за которых
отключённая фича выглядела «мёртвой», а её включение — неочевидным:

1. **Сообщения не объясняли, что делать.** Текст ошибки fail-closed был
   общим («`db_call_procedure is disabled`»), а при явном выключении флага
   шаг **молча** помечался как `skipped`: ни лога, ни причины в exchange.
2. **Нигде не было описано, как включить.** Докстринг процессора и
   описание флага говорили «default-OFF», но не называли ни ключ профиля
   (`features.db_call_procedure_enabled`), ни env-переменную, ни требования
   к профилю внешней БД (схема, креды, наличие процедуры).
3. **Профиль с внешними БД и выключенным флагом проходил валидацию молча.**
   `manage.py validate-profile` показывал «0 CRITICAL, 0 WARNING» для
   профиля `dev` (в нём объявлены `oracle_1` и `pg_1`), хотя вызовы
   процедур в этом окружении были бы пропущены без ошибки. Оператор узнавал
   об этом только в рантайме.

Активных роутов с шагом `db_call_procedure` нет (grep по `routes/`,
`extensions/`, `config_profiles/`): упоминания — только в комментариях
`routes/hello_route/route.toml` и `routes/test_route_w1/route.toml`.

## Решение

### 1. Сообщения называют флаг и способ его включения

В `db_call_procedure.py` введены две константы — `_FEATURE_FLAG`
(`db_call_procedure_enabled`) и `_ENABLE_HINT` (единая подсказка
`features.db_call_procedure_enabled: true` в overlay'е профиля либо env
`FEATURE_DB_CALL_PROCEDURE_ENABLED=true`).

* **fail-closed** (флаг недоступен): текст `exchange.fail(...)` теперь
  называет флаг и способ включения;
* **флаг выключен**: контроль потока не менялся (шаг пропускается, маршрут
  не падает — решение ADR-0380), но пропуск стал **явным**: WARNING-лог
  `db_call_procedure.disabled` и причина в
  `exchange.properties["db_call_procedure_skip_reason"]`.

Оба сообщения строятся из одних констант — оператор видит один и тот же
способ включения в логе, в exchange и в документации.

### 2. Документация флага

* `core/config/features/sprint5_dsl.py` — описание флага дополнено:
  default-OFF, ключ профиля, env-переменная, требования к профилю внешней
  БД, поведение шага при выключенном/недоступном флаге;
* `docs/config/SETTINGS_GUIDE.md` — новый раздел «Feature-флаг
  `db_call_procedure_enabled` (ADR-0389)»: таблица «что/как», поведение
  шага, требования к профилю внешней БД, описание инварианта;
* `docs/integration/INTEGRATION_GUIDE.md` — раздел «External DB DSL»:
  врезка про default-OFF, пропуск с причиной, требования к профилю и
  WARNING-валидатор.

### 3. Комментарии в `routes/*/route.toml`

Упоминание `db_call_procedure` в списке «шагов записи в БД» приведено в
соответствие: шаг существует, но выключен флагом по умолчанию, поэтому
`db.write` и не заявляется (least privilege).

### 4. Инвариант профиля → WARNING

`core/config/validator/profile_merge.py::_check_db_call_procedure_flag`:
если в merged-профиле объявлены внешние БД (`external_databases.connections[]`)
и `features.db_call_procedure_enabled` не включён — нарушение
`feature_flag.db_call_procedure_disabled` с severity **WARNING** (не
CRITICAL: внешняя БД может быть и без вызовов процедур). WARNING виден в
`manage.py validate-profile` до деплоя (exit 1 — только с `--strict`).

Сигналом служат сами внешние подключения: отдельного поля «процедура» в
конфигурации нет, а `schema` профиля (`db_schema`) — это контейнер
view/procedure/function.

## Альтернативы (отклонённые)

1. **Перевести выключенный флаг в `exchange.fail(...)`** (как
   `infra_db_query`, ADR-0366-стиль fail-closed). Отклонено: ADR-0380
   сознательно оставил «skipped» для явно выключенного флага, а зона
   кластера ограничена сообщениями; смена контроля потока — отдельное
   решение (и потенциальный breaking change для маршрутов).
2. **Оставить «молчаливый skip», только дописав в докстринг.** Отклонено:
   без WARNING-лога и причины в exchange отключение остаётся невидимым в
   проде — это и есть суть кластера.
3. **CRITICAL вместо WARNING.** Отклонено: внешняя БД в профиле не означает
   вызовов процедур; CRITICAL ронял бы `validate-profile --strict` для
   корректных профилей.
4. **Отдельный YAML-ключ «процедуры» в профиле** (`procedures: [...]`).
   Отклонено: конфигурация профиля БД не должна дублировать сведения о
   БД-схеме процедур; достаточно признака «есть внешняя БД».
5. **Включить флаг в `dev.yml`/`dev_light.yml`, чтобы WARNING не появлялся.**
   Отклонено: флаг не нужен ни одному роуту; лишнее включение флага
   исполняемого кода в БД ослабляет default-OFF-принцип.

## Последствия

* **Позитивные:** отключение видно в логе и в exchange (причина пропуска);
  тексты ошибок называют флаг и способ включения; профиль с внешними БД и
  выключенным флагом больше не проходит валидацию молча; документация
  описывает и включение, и требования к профилю внешней БД.
* **Негативные / breaking:** в `validate-profile` для профилей с внешними
  БД (сейчас — `dev`) появился WARNING; в exchange появился новый property
  `db_call_procedure_skip_reason`; WARNING-лог на каждый вызов шага при
  выключенном флаге (при выключенном флаге шаг и не должен вызываться
  часто).
* **Ограничение (ponytail):** признак «профиль может вызывать процедуры»
  определяется по наличию внешних БД — отдельной декларации процедур в
  конфигурации нет. Если появится — сигнал следует уточнить.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_db_call_procedure.py -q
.venv/bin/python -m pytest tests/unit/core/config/test_profile_db_call_procedure_flag.py -q
.venv/bin/python manage.py validate-profile dev   # 1 WARNING, exit 0
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans       # 0
.venv/bin/python tools/check_layers.py --strict               # 41 (baseline, без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0380** — default-OFF флага и fail-closed при недоступном флаге;
  настоящий ADR уточняет семантику отключения (сообщения + видимость),
  не меняя решение «явно выключенный флаг → skipped».
* **ADR-0364** — мёртвая конфигурация = ложь в конфиге: профиль с внешней
  БД и выключенным флагом больше не выглядит «зелёным».
* **ADR-0375** — merged-валидация профиля: инвариант проверяется по
  `base.yml` + overlay, а не только по overlay.
* **ADR-0385** — секция `external_databases` и её модели: `schema`
  подключения = `db_schema`, креды — через env/Vault.
