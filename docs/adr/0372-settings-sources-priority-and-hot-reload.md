# ADR-0372 — Приоритет источников конфигурации и рабочий hot-reload

* Статус: Accepted (2026-10-28, cycle 172)
* **Cycle**: 172 (ревью настроек, кластер CF2 — загрузка и перезагрузка)
* **Связан с**:
  - ADR-0373 (`.env` — только секреты; `.env.example` и гейт `check_env_example.py`)
  - ADR-0362 (config-audit: orphan vs missing)
  - ADR-0363 (декларации DB-драйверов и dependency-гейт)
* **Затрагивает**:
  - `src/backend/core/config/config_loader.py` (цепочка источников, YAML-кэш, Vault-кэш)
  - `src/backend/core/config/settings.py` (`Settings.reload()`)
  - `src/backend/core/config/hot_reload.py` (честный отчёт, абсолютные пути)
  - `src/backend/plugins/composition/setup_infra/lifecycle.py` (callback перезагрузки, watcher)
  - `src/backend/entrypoints/api/v1/endpoints/admin.py` (эндпоинт `POST /config/reload`)
  - `docs/config/SETTINGS_GUIDE.md` (раздел «Приоритет источников»)
  - `tests/unit/core/config/{test_settings_reload,test_config_sources_priority,test_hot_reload,test_vault}.py`

## Контекст

Read-only ревью (4 агента, cycle 172) зафиксировало дефекты, из-за
которые hot-reload и приоритет источников конфигурации **не работали**:

1. **`settings.reload()` не существовал.** Корневой `Settings` — обычный
   `pydantic_settings.BaseSettings`, а не `BaseSettingsWithLoader`.
   `lifecycle.py` регистрировал `_reload_settings`, который делал
   `getattr(settings, "reload", None)` → `None` → callback тихо ничего не
   делал, а `POST /api/v1/admin/config/reload` отвечал
   `{"succeeded": 1, "failed": []}` — **ложный успех**.
2. **YAML-кэш не инвалидировался.** `_BASE_YAML_CACHE`/`_OVERLAY_YAML_CACHE`
   (ключ = путь) жили вечно: изменение `config_profiles/*.yml` не
   подхватывалось даже при корректном reload.
3. **Настройки заморожены на импорте.** 40+ модульных синглтонов
   (`core/config/base/__init__.py:21`, `settings.py:185`, `@lru_cache
   get_app_settings`) создаются при импорте → перечитывание источников
   не меняло значения уже созданных объектов.
4. **`.env` фактически был приоритетом №2.** Module-level
   `load_dotenv(_REPO_ROOT/".env")` доинжективал переменные в
   `os.environ` **до** сборки цепочки источников → `.env` перебивал и
   Vault, и YAML, хотя это нигде не было задокументировано.
5. **Отсутствие YAML-профиля = тихий откат на дефолты.** Docstring
   `YamlConfigSettingsLoader` обещал фатальную ошибку, но
   `FilteredSettingsSource.__call__` глотал `Exception` и возвращал `{}`.
6. **Consul перекрыт YAML.** В `settings_customise_sources` Consul стоял
   **после** YAML → «runtime-config из Consul KV» не работал; порт
   Consul терялся (`consul_addr.split(":")[0]`).
7. **Vault читался 46 раз на старте** (92 HTTP-запроса) — кэша секрета
   не было.
8. **`VAULT_ADDR`/`VAULT_SECRET_PATH` читались только из env**, хотя
   `.env.example` требует задавать их в `config_profiles/*.yml::vault`.
9. **`_is_vault_enabled` и чтение YAML шли в обход кэша** (92 из 94
   `safe_load` мимо кэша).
10. **Тестов эффекта hot-reload не было** (`test_hot_reload.py` проверял
    только регистрацию колбэков).
11. **Пути watcher'а относительные** (`Path("config_profiles")`) →
    зависели от CWD.
12. **Приоритет источников нигде не документирован.**

Решения владельца (cycle 172): «в `.env` — только секреты»; «hot-reload
должен реально работать»; «prod-профили не должны быть как dev»;
«приоритет источников должен быть задокументирован и корректен».

## Решение

### 1. Фактический приоритет источников (документирован и закреплён кодом)

`BaseSettingsWithLoader.settings_customise_sources` (выше = приоритетнее):

| # | Источник | Комментарий |
|---|---|---|
| 1 | init-параметры (`Settings(...)`) | единственный источник выше процесса |
| 2 | env процесса | реальное окружение > всё остальное |
| 3 | Vault (KV v2) | секреты; `vault.enabled: true` |
| 4 | Consul KV (`runtime/{yaml_group}/`) | runtime-конфиг; выше YAML (было ниже) |
| 5 | YAML (`base.yml` + overlay профиля) | несекретная конфигурация |
| 6 | `.env` (dotenv-source) | **только секреты** — ниже YAML |
| 7 | file-based secrets | последний |

Значения `.env` вынесены из env-source в отдельный dotenv-source
(`model_config.env_file` + `dotenv_filtering="only_existing"`), а
env-source (`DotEnvAwareEnvSource`) их **не видит** — иначе `.env` снова
оказался бы приоритетом №2 и перебивал Vault/YAML. Реальное окружение
(значение которого отличается от значения в `.env`) сохраняет приоритет №2.

### 2. `Settings.reload()` — пересборка in-place

`Settings.reload()` (новый метод) вызывает `reload_settings(self)`:
сбрасывает YAML-кэш и кэш секретов Vault, пересоздаёт **каждую**
вложенную модель и **каждый** модульный синглтон пакета `core.config`
(обход `sys.modules`) и переносит значения **in-place**
(`__dict__`/`__pydantic_fields_set__`), чтобы ссылки потребителей
(`app_base_settings` и т.п.) не ломались. Ошибка отдельной модели не
роняет reload — она попадает в `failed`.

### 3. Fail-closed / fail-soft

`FilteredSettingsSource.fail_closed` (ClassVar): YAML — `True`
(отсутствие `base.yml`/overlay → `RuntimeError`, приложение не стартует
на дефолтах); Vault и Consul — `False` (fail-soft: недоступен → `{}`).

### 4. Кэши

* YAML-кэш: ключ `(путь, (mtime_ns, size))` → изменение файла
  инвалидирует запись автоматически; публичный `clear_yaml_cache()`.
* Vault-кэш: секрет кэшируется по `(addr, secret_path)` → 1 чтение вместо
  46; публичный `clear_vault_cache()`.

### 5. Прочие правки

* `VAULT_ADDR`/`VAULT_SECRET_PATH`: реальное env → YAML-секция `vault` →
  `.env`; `VAULT_TOKEN` (секрет): реальное env → `.env`.
* Consul: `urlsplit` вместо `split(":")[0]` — порт и схема сохраняются.
* `ConfigHotReloader.trigger_reload` возвращает честный отчёт
  (`succeeded`/`failed`/`callbacks`/`ok`); отсутствие callback'ов — ошибка,
  а не «успех».
* `ConfigHotReloader.watch()` приводит путь к абсолютному; lifecycle
  смотрит `repo_root()/config_profiles` (не зависит от CWD).
* `register_settings_reload_callback()` (hot_reload.py) — callback,
  который **падает** с `RuntimeError`, если `settings.reload` недоступен
  (вместо тихого «успеха»).

## Альтернативы (отклонённые)

1. **Оставить `.env` в приоритете env (№2), только задокументировать.**
   Отклонено: сохраняет дефект ревью (`.env` перебивает Vault/YAML) и
   противоречит решению владельца «в `.env` — только секреты».
2. **Убрать `.env` из цепочки совсем** (только `os.environ`).
   Отклонено: ломает dev-окружение (`DB_USERNAME`, `SEC_*` идут из
   `.env`), а также 126 мест в `src/`, читающих `os.environ` напрямую.
3. **Пересоздавать `Settings` целиком на reload.** Отклонено: ломает
   ссылки на вложенные модели (40+ потребителей держат `app_base_settings`).
4. **Перенести загрузку `.env` в `manage.py`/`src/backend/main.py`.**
   Отклонено как единственное решение: файлы вне зоны кластера. Точка
   загрузки — **вход в цепочку источников**
   (`BaseSettingsWithLoader.settings_customise_sources` → идемпотентный
   `ensure_env_file_loaded()`): это явный entrypoint конфигурации, а не
   side-effect импорта модуля. CLI может вызвать `load_env_file()` и
   раньше — повторный вызов безопасен.
5. **Кэш Vault per-source-instance.** Отклонено: источник создаётся на
   каждый Settings-класс (46 штук) — кэш должен быть модульным.

## Последствия

* **Позитивные:** hot-reload реально работает (YAML → значение →
  `Settings.reload()` → обновлённые in-place объекты); админ-эндпоинт
  больше не врёт; отсутствие YAML-профиля валит старт вместо тихой
  работы на дефолтах; Consul runtime-config стал работать; старт — 2
  HTTP-запроса к Vault вместо 92; приоритет источников документирован в
  `SETTINGS_GUIDE.md`.
* **Негативные (breaking, требует release-note):**
  (а) `VaultSettings.secret_path` в окружениях, где `.env` переопределял
  YAML, теперь берётся из `config_profiles/*.yml::vault` (YAML выше
  `.env`) — для dev это `secret/data/gd_integration_tools`;
  (б) ключи, присутствующие и в `.env`, и в YAML, теперь определяются
  YAML-значением;
  (в) при отсутствии `config_profiles/{profile}.yml` приложение падает на
  старте (fail-closed) вместо тихой работы на дефолтах.
* **Долги:** (1) вызов `load_env_file()` из CLI (`manage.py`,
  `src/backend/main.py`) — **вне зоны кластера** (сейчас загрузка
  происходит во входе в цепочку источников, этого достаточно для старта);
  (2) `docs/config/HOT_RELOAD.md`
  устарел (описывает gap, закрытый в cycle 1) — **вне зоны**;
  (3) `feature_flags` (`core/config/features/*`) — обычный `BaseSettings`,
  `.env` для него не является источником — **вне зоны**;
  (4) ADR-0373 уже выносит несекретные ключи из `.env.example`.
* **Вне зоны кластера CF2:** `src/backend/main.py`, `manage.py`,
  `src/backend/cli/*`, `core/config/features/*`, `docs/config/HOT_RELOAD.md`,
  `.env.example`, `docs/adr/INDEX.md`.

## Проверка

```bash
# NOTE: после `uv sync --all-extras` плагин `deepeval` (pytest11) ломает
# старт pytest: `langchain.schema` отсутствует → добавляем `-p no:plugins`.
.venv/bin/python -m pytest tests/unit/core/config -q -p no:randomly -p no:plugins
.venv/bin/python -m ruff check \
    src/backend/core/config/config_loader.py \
    src/backend/core/config/settings.py \
    src/backend/core/config/hot_reload.py \
    src/backend/plugins/composition/setup_infra/lifecycle.py \
    src/backend/entrypoints/api/v1/endpoints/admin.py \
    tests/unit/core/config
.venv/bin/python tools/check_layers.py --strict          # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
.venv/bin/python tools/config_audit.py --scope orphans    # 0
.venv/bin/python tools/check_declared_dependencies.py
```

Red→green (фактический прогон):

* **RED** (на `HEAD`): `test_settings_reload.py` и
  `test_config_sources_priority.py` не собираются
  (`ImportError: cannot import name 'clear_yaml_cache'` /
  `'DotEnvAwareEnvSource'`), плюс 4 падения:
  `test_hot_reload.py::test_watch_makes_relative_path_absolute`,
  `::test_trigger_reload_without_callbacks_reports_failure`,
  `::test_trigger_reload_reports_callbacks_count`,
  `test_vault.py::test_defaults` → `4 failed, 15 passed, 2 errors`.
* **GREEN** (после фикса): `58 passed` в кластерных файлах;
  `tests/unit/core/config` → `729 passed, 1 failed`
  (падение `test_features_dsl.py::test_dsl_field_count` — RPA-кластер).

Поведение на `HEAD` (для протокола): `settings.reload` —
`callable = False`; `trigger_reload()` без callback'ов возвращает
`{"succeeded": 0, "failed": []}` (ложный «успех»); у
`YamlConfigSettingsLoader` нет `fail_closed`.

## Связи с другими ADR

* **ADR-0373** — «`.env` — только секреты»: этот ADR закрепляет
  приоритет `.env` ниже YAML; ADR-0373 чистит состав `.env.example` и
  добавляет гейт `tools/check_env_example.py --secrets-only`.
* **ADR-0362** — `orphan` vs `missing` в config-audit: YAML-секции
  обязаны состоять только из живых полей моделей.
* **ADR-0363** — декларации DB-драйверов: `DatabaseConnectionSettings`
  перечитывается на reload, поэтому опечатки в драйверах видны сразу.
