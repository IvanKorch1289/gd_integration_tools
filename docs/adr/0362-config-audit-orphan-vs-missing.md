# ADR-0362 — Двусторонний аудит конфигурации: разделение orphan- и missing-классов, подключение гейта

* Статус: ACCEPTED (2026-10-27, cycle 172, Wave 13 — решения Q16 + Q17)
* Cycle: 172
* Дата: 2026-10-27
- **Затрагивает**: `src/backend/core/config/config_loader.py`,
  `tools/config_audit.py`, `tools/config_audit_allowlist.txt`,
  `config_profiles/base.yml`, `config_profiles/prod.yml`
- **Связан с**: ADR-0335 (unsafe-defaults), ADR-0336 (env-example matrix),
  ADR-0351 (логирование), ADR-0350 (удаление мёртвого кода)

## Контекст

### Механизм загрузки ТИХО отбрасывает неизвестные YAML-ключи

`FilteredSettingsSource.__call__` (`src/backend/core/config/config_loader.py:185-192`)
загружает YAML и прогоняет через `_filter_data`; при **любой** ошибке
загрузки вызывается `_handle_error` (`config_loader.py:240-243`) — там только
ERROR-лог, а `__call__` возвращает `{}` → настройки деградируют в дефолты
модели (тот же «дефолт вместо ошибки» контракт, что и раньше).

`_filter_data` (`config_loader.py:194-210`) применяет фильтр
`{k: v for k, v in group_data.items() if k in self.model_fields}`
(`config_loader.py:208`) **до** валидации pydantic. Поэтому
`extra="forbid"` в моделях (`config_loader.py:485`, `app_base.py:29`) на YAML
**не действует**: опечатка в имени ключа не вызывает ошибку — ключ просто
исчезает из конфигурации.

Следствие: опечатка в имени YAML-ключа = **тихая потеря настройки**.
Никто об этом не узнаёт: ни валидатор, ни тест, ни лог.

### Масштаб (проверено гейтом, 2026-10-27)

Прогон `tools/config_audit.py` по YAML-профилям из `HEAD` (до фикса) дал
**43 orphan-расхождения** по 4 профилям:

| Источник | Расхождения | Пояснение |
|---|---|---|
| `config_profiles/base.yml` | 10 на профиль | 8 orphan-ключей + 2 orphan-группы |
| `config_profiles/prod.yml` | +3 | orphan-ключи в секции `log` |

Детализация по профилям: dev / dev_light / staging — по 10 (8 ключей + 2 группы),
prod — 13 (8 ключей + 2 группы + 3 ключа `log`). После фикса — **0** по всем
четырём профилям.

Конкретные мёртвые записи в `base.yml`:

* `mcp.http_path` → переименован в `mcp.bind_path` (реальное имя поля);
* `mcp.sse_enabled`, `mcp.stdio_enabled`, `mcp.bind_host`, `mcp.bind_port` —
  удалены (в модели `McpSettings` их нет);
* `mqtt.require_client_auth`, `mqtt.bind_host`, `mqtt.bind_port` — удалены
  (MQTT здесь — **клиент**, а не сервер; bind_* для него бессмысленно);
* orphan-группа `http3:` — удалена целиком (модели с `yaml_group="http3"` в
  проекте нет; HTTP/3 живёт внутри `app:`);
* top-level `queue_consumer_max_prefetch` — перенесён в
  `queue.consumer_max_prefetch`.

И три мёртвых ключа в `prod.yml` (секция `log`): `compression_brotli`,
`gzip_minimum_size`, `gzip_compresslevel` — перенесены в `app:`
(см. «Последствия»).

### Два класса расхождений — разные дефекты

Аудит двусторонний: YAML → код (orphan) и код → YAML (missing). Классы
`missing-secret` / `missing-non-secret` — **другой** дефект: переменные
окружения из Settings-классов не документированы в `.env.example`. Правка
`.env*` в проекте запрещена, и объём разрыва другой — блокировать им CI
означало бы заблокировать весь репозиторий до закрытия чужой задачи.

## Решение

### (а) `_filter_data` логирует отброшенные ключи, но не валит старт

В `FilteredSettingsSource` добавлено одноразовое предупреждение:
`_warn_unknown_keys` (`config_loader.py:212-234`) — **один WARNING на
источник** (флаг `_unknown_keys_warned`, `config_loader.py:175-177`), со
списком отброшенных ключей и указанием `yaml_group`.

Рантайм-fail-loud **сознательно не вводим**: падение старта из-за лишнего
(и, возможно, безобидного) ключа опаснее потери одной настройки — старт
должен быть предсказуемым, а долг фиксируется гейтом ниже.

### (б) `tools/config_audit.py` разделён на классы и подключён как гейт

Классы расхождений (`tools/config_audit.py:76-87`):

| Класс | Что означает | Блокирует гейт |
|---|---|---|
| `orphan-group`, `orphan-key` | наш дефект: опечатка в YAML = тихая потеря настройки | **да** |
| `missing-secret`, `missing-non-secret` | другой дефект: переменные не в `.env.example` | нет |

Scope-флаги: `--scope {orphans|all}` (по умолчанию `orphans`),
`--strict` (игнорировать baseline), `--allowlist`, `--update-allowlist`,
`--json` (`tools/config_audit.py:685-736`).

Baseline известного долга — `tools/config_audit_allowlist.txt`:
**68 записей missing-класса** (все `missing-secret`; orphan-записей в
baseline нет — orphan-класс закрыт полностью).

Локальные команды: `make check-config-audit` (`make/quality.mk:168-171`),
`make check-config-audit-full` (`make/quality.mk:173-176`),
`make check-config-audit-update` (`make/quality.mk:178-180`).

### (в) CI-шаг блокирует только orphan-класс

`.github/workflows/lint.yml:122-128` — шаг «Config audit gate (config_audit)»:

```bash
uv run python tools/config_audit.py --scope orphans
```

Missing-класс печатается неблокирующей секцией (17 issue на профиль) и
остаётся в отдельной owner-задаче.

### (г) Мёртвые конкретные ключи починены

`config_profiles/base.yml`:

* секция `http3:` удалена; HTTP/3 перенесён в `app:`
  (`app.http3_enabled`, `app.http3_port` — `base.yml:42-43`);
* `mcp.http_path` → `mcp.bind_path` (`base.yml:647`);
* `mcp.sse_enabled` / `stdio_enabled` / `bind_host` / `bind_port` удалены;
* `mqtt.require_client_auth` / `bind_host` / `bind_port` удалены;
* `queue_consumer_max_prefetch` → `queue.consumer_max_prefetch`
  (`base.yml:279`).

`config_profiles/prod.yml`:

* `log.compression_brotli` / `gzip_minimum_size` / `gzip_compresslevel`
  перенесены в `app:` (`prod.yml:26`, `prod.yml:31-32`).

Результат: **0 orphan-issues по 4 профилям** (было 43).

## Альтернативы (отклонённые)

### (а) Удалять `required_fields`-подобные декларации — неприменимо

`required_fields` в `base.yml` — декларация уровня логирования, а не
YAML-ключ вне `model_fields`; orphan-аудит её не затрагивает. Речь здесь
идёт о другом: о ключах, которые загрузчик отбрасывает.

### (б) Fail-loud на неизвестный ключ в рантайме — отклонено

Падение старта приложения из-за лишнего ключа в YAML — неприемлемый риск:
конфиг могут править не-разработчики (ops), и опечатка в неиспользуемой
секции должна приводить к warning, а не к недоступности сервиса.
Предупреждение + гейт дают тот же сигнал без операционного риска.

### (в) Блокировать CI и на missing-секрет — отклонено

Разрыв другой и большой: **942 поля** у 69 Settings-классов против
**57 переменных** в `.env.example` (проверено подсчётом через
`tools/config_audit.py`). Правка `.env*` запрещена правилами проекта —
задача отдельная и не должна блокировать репозиторий.

## Последствия

### Позитивные

- Опечатка в YAML-ключе больше не исчезает молча: WARNING со списком ключей
  + `yaml_group` в логе (`config_loader.py:229-234`).
- Гейт в CI ловит **новые** orphan-расхождения до мержа; baseline долга
  зафиксирован и не даёт долгу расти.
- Мёртвые ключи в `base.yml` / `prod.yml` починены — 43 → 0.

### Негативные

- **Prod реально включает Brotli и gzip 512/6.** До переноса значения жили
  в секции `log:`, которая их не читает, — фактически применялись дефолты
  `app:` из `base.yml` (`gzip_minimum_size: 300`, `gzip_compresslevel: 9`,
  `base.yml:32-33`) и `compression_brotli` оставался `False`. Теперь
  middleware читает `settings.app.compression_brotli`
  (`src/backend/entrypoints/middlewares/setup_middlewares.py:358`),
  `settings.app.gzip_minimum_size` (`setup_middlewares.py:381`) и
  `settings.app.gzip_compresslevel` (`setup_middlewares.py:382`) — поля
  объявлены в `src/backend/core/config/base/app_base.py:264-283`.
  **Это изменение поведения prod-профиля** (сжатие включается, уровень
  gzip меняется 9 → 6, порог 300 → 512): проверено на нагрузке перед
  выкаткой.
- Missing-класс (17 issue на профиль) остаётся незакрытым — он видим, но
  не блокирует.

### Нейтрально

- `--strict` (scope=all) по-прежнему падает на любых расхождениях — это
  инструмент полного аудита, не CI-гейт.

## Проверка после реализации

```bash
# 1. Гейт: 0 orphan-расхождений по всем профилям
uv run python tools/config_audit.py --scope orphans
# ожидаемо: «Расхождений конфигурации: 0 новых (scope=orphans; …)»

# 2. Полный аудит — missing-класс виден, но не блокирует
uv run python tools/config_audit.py --scope all

# 3. Контроль регрессии: на HEAD-YAML гейт должен показать 43 orphan-issue
uv run python tools/config_audit.py --profiles-dir /tmp/cfg_head/config_profiles
# ожидаемо: «НОВЫЕ расхождения конфигурации (scope=orphans): 43»

# 4. Юнит-тесты загрузчика и гейта
uv run pytest tests/unit/core/config/test_config_loader_unknown_keys.py \
                tests/unit/core/config/test_no_orphan_config_keys.py \
                tests/unit/tools/test_config_audit.py -q
```

## Статус реализации

**Cycle 172 (Wave 13).** Реализовано полностью: решения (а), (б), (в), (г) —
`_warn_unknown_keys` в `config_loader.py`, разделение классов и CLI-флаги в
`tools/config_audit.py`, baseline `tools/config_audit_allowlist.txt` (68
записей), CI-шаг в `.github/workflows/lint.yml:122-128`, починка ключей в
`config_profiles/base.yml` и `config_profiles/prod.yml`.

## Followup (owner-задачи)

1. **Missing-класс** (68 записей baseline, 17 issue на профиль): переменные
   окружения из Settings-классов не документированы в `.env.example`.
   Правка `.env*` запрещена правилами проекта — задача отдельная.
2. **`tools/config_audit_allowlist.txt`**: после закрытия missing-класса
   baseline очищается; `--scope all` становится блокирующим.
3. **Регулярный прогон `--scope all`** (например, раз в спринт) — чтобы
   missing-долг не рос незамеченным.

## Связи с другими ADR

- ADR-0335 — гейт unsafe-defaults конфигурации (смежный класс: дефолты,
  которые маскируют отсутствие явного значения).
- ADR-0336 — Configuration matrix: required secrets & unknown vars (смежный
  missing-класс).
- ADR-0351 — статус фасада логирования (настройки `log:` — объект этого
  ADR: именно в `log:` жили три мёртвых ключа сжатия).
- ADR-0350 — удаление мёртвого кода (тот же принцип: не оставлять
  неисполняемые декларации).
