# ADR-0379 — Честный hot-reload, валидация профиля и приоритет env над .env

* Статус: Accepted (2026-10-29, wave 15, кластер W4 — «HOT RELOAD, ПРОФИЛЬ, ПРИОРИТЕТ .env»)
* Cycle: 175
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/core/config/hot_reload.py`
  - `src/backend/core/config/profile.py`
  - `src/backend/core/config/services/mqtt.py`
  - `src/backend/core/config/constants_settings.py`
  - `src/backend/entrypoints/api/v1/endpoints/admin.py` (reload-эндпоинт)
  - `config_profiles/base.yml` (секция `constants`, `rag.adaptive.multi_query`)
  - `tests/unit/core/config/{test_hot_reload,test_settings_reload,test_constants_settings,test_config_sources_priority,test_yaml_group_coverage,test_profile_focused}.py`
- **Связан с**:
  - ADR-0372 (приоритет источников конфигурации и hot-reload)
  - ADR-0375 (константы runtime-кода как конфигурация, yaml-группы в `base.yml`)
  - ADR-0371 (харденинг профилей и инварианты)
  - ADR-0362 (config-audit: orphan vs missing)
  - ADR-0364 (мёртвая конфигурация = ложь в конфиге)
  - ADR-0059 (Granian RSGI production tuning)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/core/config/config_loader.py` (кластер W1) — приоритет реального
    env над `.env` при lowercase-ключе (дефект 5, см. «Последствия»).

## Контекст

Независимый свип функционата настроек (волна 15) нашёл в кластере
hot-reload/профиль/константы остаточные дефекты:

1. **[medium] Ложный «успех» перезагрузки.** `_reload_settings` игнорировал
   отчёт `settings.reload()`. При битом YAML `reload()` возвращал
   `failed=87`, но `POST /admin/config/reload` отвечал `ok=True` — оператор
   думал, что конфигурация перезагружена.
2. **[medium] Событие ФС в том же тике, что и `start()`, терялось.**
   `create_task` только планирует запуск; без yield watcher не успевал
   подписаться на ФС, и запись файла сразу после `start()` пропадала.
3. **[medium] `MqttSettings` не перезагружался.** Инстанс создавался через
   module-level `__getattr__` и не попадал в перебор модульных синглтонов
   (`config_loader._iter_settings_singletons`) → `broker_port` не менялся.
4. **[medium] Опечатка в `APP_PROFILE` молча давала `dev`.**
   `APP_PROFILE=prodd` → профиль `dev` → `app.debug_mode=true` (fail-open).
5. **[medium] Реальный env проигрывал `.env` при lowercase-ключе.**
   `.env: app_gzip_minimum_size=777` + настоящее `APP_GZIP_MINIMUM_SIZE=999`
   → значение терялось, оставалось YAML-значение: сравнение ключей
   окружения регистрозависимо (`config_loader.py:98-109`).
6. **[medium] Инертные ключи секции `constants`.** Часть ключей менялась в
   YAML, но никто их не читал — иллюзия настраиваемости.
7. **[low] `debounce_ms` в hot-reload — это `step` watchfiles**, а `debounce`
   оставался 1600 мс: имя параметра не соответствовало поведению.
8. **[low] `_normalize` в тесте yaml-групп не разворачивал вложенные
   pydantic-модели** → ложное расхождение для `rag.adaptive`
   (dict против `AdaptiveRAGSettings`).

## Решение

### 1. Отчёт `settings.reload()` — источник истины (fail-closed)

`hot_reload.py`: добавлен публичный `ConfigReloadError(failed)`.
`register_settings_reload_callback` разбирает отчёт `settings.reload()` и
при непустом `failed` бросает `ConfigReloadError`; `trigger_reload` кладёт
список сломанных моделей в элемент `failed` отчёта. Админ-эндпоинт
`POST /admin/config/reload` при `ok=False` отвечает **HTTP 500** с полным
отчётом (в т.ч. перечнем `failed`), а не `ok=True`.

### 2. Watcher подписывается на ФС до возврата из `start()`

В `start()` добавлен `await asyncio.sleep(0)` после создания таска: один
yield цикла событий даёт watcher'у дойти до `awatch(...)` (подписка
устанавливается при первом `__anext__` генератора). Событие, случившееся в
том же тике, больше не теряется.

### 3. `MqttSettings` — полноценный модульный синглтон

`get_mqtt_settings()` дополнительно регистрирует инстанс в `globals()`
модуля (`mqtt_settings`). Ленивость сохранена (инстанс создаётся при первом
обращении), но синглон теперь виден перебору модульных синглтонов и
перезагружается in-place — ссылки потребителей остаются валидными.

### 4. Неизвестный `APP_PROFILE` — ошибка (fail-closed)

`get_active_profile()`: пустое/незаданное значение → `DEFAULT_PROFILE`;
валидное значение (регистр не важен) → профиль; **неизвестное значение →
WARNING + `ValueError`** с перечнем допустимых профилей. Приложение не
стартует с неверным профилем (fail-closed) вместо тихого отката на `dev`
(fail-open с `app.debug_mode=true`). Валидные `dev` и `dev_light` работают
как прежде.

### 5. Инертные ключи `constants` — убраны из конфигурации

`DEFAULT_CB_FAST_FAILURE_THRESHOLD` / `DEFAULT_CB_FAST_RECOVERY_SECONDS`
не имеют потребителя (fast-circuit-breaker'а в проекте нет) → удалены из
`FIELD_TO_CONSTANT`, из модели `ConstantsSettings` и из `base.yml`;
кодовые дефолты остались в `constants.py`. Остальные ключи живы:
`INITIAL_DELAY` / `RETRY_DELAY` / `MAX_RESULT_ATTEMPTS` читает
`extensions/core_entities/orders/workflows/orders_dsl.py`,
`DEFAULT_CB_*` / `DEFAULT_RETRY_*` — `core/resilience/*` и
`infrastructure/resilience/supervisor.py`. Закреплено гейтом
`test_every_constants_key_has_a_consumer` (скан потребителей `consts.<ИМЯ>`):
инертный ключ больше нельзя добавить молча.

### 6. `debounce`/`step` приведены к смыслу

`debounce_ms` (по умолчанию 1600) передаётся в `debounce` watchfiles —
окно группировки изменений; период опроса ФС вынесен в константу
`_WATCH_STEP_MS = 50` (`step`).

### 7. `_normalize` разворачивает вложенные pydantic-модели

`tests/unit/core/config/test_yaml_group_coverage.py`: `_normalize` приводит
`BaseModel` к `model_dump()`, поэтому секции с вложенными моделями
(`rag.adaptive`) сравнимы с дефолтами. Группа `rag` добавлена в перечень
групп, значения которых обязаны совпадать с дефолтами моделей; расхождение
в одном слове промпта (`по одной на строку` → `по одной на строке`)
выровнено в `base.yml` по дефолту модели.

## Альтернативы (отклонённые)

1. **Оставить `failed` в отчёте, но отвечать `200 ok=True`.** Отклонено:
   оператор не отличит успешную перезагрузку от битого YAML.
2. **Ловить ошибки YAML только в админ-эндпоинте.** Отклонено: файловый
   watcher вызывает тот же callback — ошибка должна быть в общем механизме.
3. **Для неизвестного `APP_PROFILE` откатываться на `dev_light`.**
   Отклонено: `dev_light` — тоже не-production профиль (`debug_mode=true`),
   тихий даунгрейд prod-деплоя опаснее явного отказа стартовать.
4. **Игнорировать неизвестный `APP_PROFILE`, но писать WARNING.** Отклонено:
   fail-open сохраняется (профиль `dev` поднимается), WARNING в логе легко
   потерять.
5. **Оставить инертные ключи `constants` «на будущее».** Отклонено: мёртвая
   конфигурация — ложь в конфиге (ADR-0364); ключ без потребителя убран.
6. **Разворачивать вложенные модели в `tools/config_audit.py`.** Отклонено:
   инструмент вне зоны кластера; дефект — в тестовом хелпере.
7. **Переименовать `debounce_ms` в `step_ms`.** Отклонено: параметр
   действительно задаёт окно группировки; переименование скрыло бы
   расхождение, а не устранило его.

## Последствия

* **Позитивные:** `POST /admin/config/reload` больше не врёт; событие ФС в
  первом тике не теряется; `MqttSettings` перезагружается; опечатка в
  `APP_PROFILE` приводит к отказу старта с понятным сообщением, а не к
  неявному `debug_mode=true`; в конфигурации не осталось ключей без
  потребителей (закреплено гейтом).
* **Негативные / breaking:** опечатка в `APP_PROFILE` теперь блокирует
  старт процесса (в dev это тоже верно — профиль задаётся явно);
  `constants.default_cb_fast_*` больше не принимаются из YAML (кодовые
  дефолты `consts.DEFAULT_CB_FAST_*` сохранены); значение
  `rag.adaptive.multi_query.prompt_template` в YAML выровнено с дефолтом
  модели (одно слово).
* **Вне зоны (кластер W1, `config_loader.py`):** реальный env должен
  побеждать `.env` независимо от регистра ключа. Минимальный фикс —
  в `load_env_file` не подменять `os.environ[key]`, если уже есть
  case-вариант с другим значением, и в `_dotenv_only_keys` считать ключ
  «файловым» только если ни один case-вариант в `os.environ` не содержит
  другого значения (сейчас сравнение регистрозависимо). Регрессия
  зафиксирована в `test_config_sources_priority.py` как `xfail` с указанием
  владельца фикса.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/config/test_hot_reload.py \
    tests/unit/core/config/test_settings_reload.py \
    tests/unit/core/config/test_constants_settings.py \
    tests/unit/core/config/test_config_sources_priority.py \
    tests/unit/core/config/test_yaml_group_coverage.py \
    tests/unit/core/config/test_profile_focused.py -q -p no:randomly
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/check_layers.py --strict                 # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0 # 1 pre-existing
```

## Связи с другими ADR

* **ADR-0372** — источники конфигурации и hot-reload: этот ADR закрывает
  оставшуюся ложь в отчёте о перезагрузке и регистрирует ещё один
  модульный синглтон в переборе hot-reload.
* **ADR-0375** — константы как конфигурация: инертные ключи удалены из
  `constants`, гейт «у ключа есть потребитель» не даёт вернуться к иллюзии
  настраиваемости.
* **ADR-0371** — профили: fail-closed на неизвестном `APP_PROFILE`
  продолжает линию «плохой профиль не должен тихо работать».
* **ADR-0362 / ADR-0364** — мёртвая конфигурация и различение
  orphan/missing: инертные ключи убраны, гейт `config_audit` остаётся
  источником правды по опечаткам в YAML.
* **ADR-0059** — Granian RSGI: секция `granian` в `base.yml` живёт вне
  `core/config` (модель — в `core/scaling`), поэтому `config_audit` не
  видит её модель и считает секцию orphan-группой (вне зоны кластера —
  фикс в `tools/config_audit.py`).
