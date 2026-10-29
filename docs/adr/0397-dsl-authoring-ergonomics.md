# ADR-0397 — Эргономика авторства DSL: скаффолд, линтер, capability-гейт, вложенный YAML

* Статус: Accepted (2026-10-29, волна 19, кластер D — DX)
* Автор: coder-агент, кластер D
* Связи: ADR-0369 (достижимость шагов из YAML), ADR-0058 (JSON-Schema процессоров),
  ADR-0349 (response-binding), ADR-042/043 (манифесты), ADR-044 (модель capability),
  ADR-0393 (DB-capability-гейт, RPA-авторизация)

---

## Контекст

Волна 19 нашла в кластере «DX: скаффолд, линтер, capability-публичность,
вложенный YAML» шесть дефектов:

1. `make new-route` генерировал **незагружаемый** роут: в `route.toml` не
   было обязательного `pipelines` (`RouteManifest.pipelines`, `min_length=1`),
   в `main.dsl.yaml` был несуществующий шаг `validate_request` и шаг
   `to: {response: ...}` (у `to` — сигнатура sink-метода, а response-binding
   объявляется на верхнем уровне YAML, ADR-0349).
2. Линтер не понимал канонический V11-формат: 4 ложные ошибки на штатных
   `routes/hello_route` и `routes/test_route_w1` («нет [route].name/version/
   requires_core», «нет from+steps»), при этом реальные ошибки (неизвестный
   шаг, неверный kwarg) не ловились.
3. Capability-гейт БД-шагов был **невыразим для автора**: `db.read`/`db.write`
   не были public, поэтому subset-проверка отвергала декларацию роута
   (`Route 'demo' requests capabilities not covered … db.read('orders')`),
   а scope обязан совпадать с алиасом профиля БД.
4. Вложенные списки YAML материализовались только для
   `do_try/retry/parallel/saga/choice`: в `for_each`/`fork_join`/`switch`/
   `timeout` оставались raw-`dict` → runtime `failed: 'dict' object has no
   attribute 'process'`; невалидный JMESPath в `for_each` давал «тихий успех»
   с нулём итераций.
5. Карта capability в линтере была захардкожена: 9 из 11 ключей
   `_PROCESSOR_CAPABILITIES` не соответствовали ни одному шагу, поэтому
   `MISSING_CAPABILITY` не срабатывал для `rpa_*`/`ai_*`/`db_*`, а подсказка
   вела в форму, которую subset-проверка отвергала.
6. Покрытие подсказок и схем: `STEP_COMPLETIONS` = 55 при 438 публичных
   методах `RouteBuilder`, реестр `@processor` = 45 (13 без схемы), цель
   `make schemas` не существует.

## Решение

### 1. Скаффолд (`ops/scripts/new_route.py`)

* В `route.toml` добавлено обязательное `pipelines = ["main.dsl.yaml"]`.
* Шаг `validate_request` заменён на существующие методы `RouteBuilder`
  (`feature_flag` → `transform` → `audit`); `capabilities` приведены в
  соответствие шагам (`audit.write`).
* Response-binding перенесён на верхний уровень YAML в форме
  `to: {body: {...}}` (ADR-0349) — `to` больше не фигурирует в `steps`.
* Регрессия зафиксирована тестом: сгенерированные артефакты грузятся
  настоящими `load_route_manifest` и `load_pipeline_from_file`.

### 2. Линтер (`src/backend/dsl/cli/linter.py`)

* Манифест парсится **тем же** загрузчиком, что и `RouteLoader`
  (`load_route_manifest`); принимаются плоская форма и конверт `[route]`;
  обязательные поля — `name`, `version`, `requires_core`, `pipelines`.
* Канонический формат V11: `route_id`/`source`/`from` + `steps`
  (legacy — `processors`).
* Шги валидируются **сборкой pipeline** в `try/except`
  (`INVALID_PIPELINE`): неизвестный шаг, неверный kwarg и невалидный
  вложенный список теперь находятся линтером, а не в рантайме.
* Comment-only элементы списка шагов (`None`) пропускаются — так же, как
  это делает YAML-загрузчик.

### 3. Capability-публичность (`vocabulary/defaults/base.py`, `gate/__init__.py`)

* `db.read`/`db.write` сделаны **public** при сохранении
  `scope_required=True` и `ExactAliasMatcher`. Это **отменяет** решение
  ADR-0393 («сделать db.read/db.write публичными — отклонено»): в проекте
  нет plugin-владельца core-шагов доступа к БД, поэтому декларация в
  `route.toml` была единственным выразимым способом, а не альтернативой
  плагину.
* Публичность снимает **только** declaration-time проверку
  (`check_capabilities_subset`). Рантайм-контроль не ослаблен: гейт
  по-прежнему требует декларации capability в самом роуте (в prod
  core-baseline выключен — `config_profiles/prod.yml`) и сверяет scope
  (профиль внешней БД либо имя таблицы). Декларация без scope
  отвергается (`validate_ref`).
* Сообщения об отказе стали actionable: называют требуемый scope и место
  декларации (`routes/<route>/route.toml` либо `plugin.toml` владельца).

### 4. Вложенный YAML (`src/backend/dsl/yaml_loader/build.py`)

* Вложенные списки процессоров материализуются **по конвенции**:
  разбирается аннотация параметра метода `RouteBuilder`
  (`list[BaseProcessor]` / `dict[str, list[BaseProcessor]]` /
  `list[list[BaseProcessor]]`), поэтому правило покрывает `for_each`,
  `fork_join`, `switch`, `timeout` и остальные шаги без ручного списка.
* Control-flow-шаги с bespoke-структурой (`do_try`, `retry`, `parallel`,
  `saga`, `choice`) исключены из общего разбора: их вложенные списки
  приводит `_materialize_control_flow_params` (`choice.when` — список
  `ChoiceBranch`, `saga.steps` — список `SagaStep`).
* Неверный тип вложенного параметра (dict вместо списка) — fail-fast на
  этапе load, а не runtime-падение.
* `for_each.items_path` проверяется на синтаксическую корректность
  JMESPath при загрузке.

### 5. Карта capability и каталог шагов

* Введён `src/backend.dsl.builders.step_catalog.py` — единый источник
  истины: список допустимых YAML-шагов (публичные методы `RouteBuilder`),
  карта «шаг → `required_capability`» (AST-разбор `self._add_lazy(...)` +
  реестр `@processor`) и JSON-Schema шага (реестр ADR-0058, иначе каркас по
  сигнатуре). Линтер читает карту из каталога.
* «Мягкий CI-гейт» на полноту покрытия реализован тестами
  (`tests/unit/dsl/cli/test_step_catalog.py`): каталог покрывает все
  публичные методы `RouteBuilder`, а захардкоженный список
  `STEP_COMPLETIONS` не содержит несуществующих шагов (drift-guard).

### Вне зоны кластера D (owner-задачи)

* `make schemas` и генерация `docs/reference/schemas/processors/**` —
  `make/codegen.mk` + `tools/dsl_export_schemas.py` + `docs/**` (кластер E).
  Экспортёр схем уже существует и умеет читать реестр; не хватает цели
  Makefile, CI-job'а и каталога артефактов.
* Подстановка каталога в LSP-completion —
  `tools/dsl_lsp/schema_completion.py` (вне зоны). Каталог даёт источник
  истины, подключение — отдельная задача.
* Политика core-baseline в профилях (`config_profiles/prod.yml`) не
  менялась: `dsl_capability_core_baseline_enabled: false` уже отключает
  выдачу capability «всем подряд».

## Альтернативы

* **Оставить `db.read`/`db.write` непубличными (позиция ADR-0393).**
  Отклонено: probe ревью показал, что декларация роута отвергается
  subset-проверкой, а plugin-владельца core-доступа к БД не существует —
  автор не может выразить намерение. Ослабление контроля компенсировано
  обязательным scope и fail-closed рантайм-гейтом.
* **Оставить захардкоженную карту capability в линтере.** Отклонено:
  источник истины — `required_capability` процессора; ручной список
  разъехался с API (9 из 11 ключей — несуществующие шаги).
* **Перечислять вложенные параметры поимённо (`for_each`, `fork_join`,
  …).** Отклонено: список разъезжается с API так же, как capability-карта;
  аннотации `RouteBuilder` уже описывают контракт.
* **Генерировать STEP_COMPLETIONS в `tools/dsl_lsp/schema_completion.py`.**
  Отложено: файл вне зоны кластера; каталог даёт источник истины, а
  подключение к LSP/CI — owner-задача (см. «Проверка»).

## Последствия

* **Позитивные**: `make new-route` даёт загружаемый роут; линтер молчит на
  канонических роутах и ловит реальные ошибки; автор может объявить
  `db.read`/`db.write` с алиасом ресурса и получает внятную ошибку при
  несовпадении; вложенные шаги перестают падать в рантайме; карта
  capability и каталог шагов не расходятся с API.
* **Издержки**: `db.read`/`db.write` в `route.toml` требуют явного scope;
  авторы существующих роутов с `db.*` без scope получат ошибку загрузки
  (fail-closed, ожидаемо). Каталог шагов импортирует пакет процессоров —
  первый вызов линтера дороже прежнего (кеш в процессе).
* **Предел**: JMESPath проверяется на синтаксику; «путь не совпал с данными»
  определяется только в рантайме (данных на этапе load нет) — потолок
  текущего подхода, апгрейд — семантическая проверка в рантайме
  `ForEachProcessor`.
* **Совместимость**: `db.read`/`db.write` стали public — обновлены
  фикстуры набора public-capabilities и subset-проверки в тестах.

## Проверка

* `tests/unit/tools/test_new_route_scaffold.py` — манифест и pipeline
  сгенерированного роута грузятся настоящими лоадерами.
* `tests/unit/dsl/cli/test_linter.py` — канонический формат, неизвестный
  шаг, неверный kwarg, scope-аварианты для `db.*`/`rpa_*`.
* `tests/unit/dsl/cli/test_step_catalog.py` — полнота каталога, отсутствие
  drift'а LSP-completion, покрытие схемами.
* `tests/unit/dsl/yaml_loader/test_nested_materialization.py` — вложенные
  списки `for_each`/`fork_join`/`switch`/`timeout`, fail-fast на невалидном
  JMESPath.
* `tests/unit/core/security/capabilities/test_db_capability_scope.py` —
  public + обязательный scope, сверка scope с профилем, actionable-ошибки.
* `tools/config_audit.py --scope orphans` → 0; `tools/check_layers.py
  --strict` → 41 (документированный baseline, моих файлов в списке нет);
  `tools/check_docstrings.py src --max-allowed 0` → 0;
  `tools/check_decorative_capabilities.py --ci` → 0 новых.
* Pre-existing падение вне зоны: `tests/unit/tools/
  test_py3_syntax_migration.py::test_no_py2_except_pattern_anywhere`
  (Py2-синтаксис `except A, B:` в 4 файлах: `rpa/operations/
  httprequestprocessor.py`, `infrastructure/storage/s3.py`,
  `tests/unit/infrastructure/logging/test_factory_level_environment.py`).
* Pre-existing: стейл-запись allowlist в
  `tools/check_decorative_capabilities_allowlist.txt`
  (`infra_db.py::InfraDbQueryProcessor` — из ADR-0393); гейт `--ci` не падает.

## Связи

ADR-0369, ADR-0058, ADR-0349, ADR-042, ADR-043, ADR-044, ADR-0393.
