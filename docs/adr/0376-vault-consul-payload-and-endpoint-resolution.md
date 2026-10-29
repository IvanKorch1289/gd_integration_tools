# ADR-0376 — Формат payload Vault/Consul и единое разрешение endpoint Vault

* Статус: Accepted (2026-10-29, cycle 175, кластер W1)
* **Cycle**: 175 (свип функционала настроек, волна 15 — кластер W1)
* **Связан с**:
  - ADR-0372 (приоритет источников конфигурации; `VAULT_ADDR`/`VAULT_SECRET_PATH` перенесены в YAML)
  - ADR-0373 (`.env` — только секреты)
  - ADR-0375 (settings coverage / secret typing)
* **Затрагивает**:
  - `src/backend/core/config/config_loader.py` (фильтр payload, TTL кэша, флаг unreachable)
  - `src/backend/core/config/vault.py` (`vault_endpoint()`, `vault_secret_path()`)
  - `src/backend/infrastructure/application/vault_refresher.py`
  - `src/backend/infrastructure/resilience/components/secrets_chain.py`
  - `src/backend/infrastructure/secrets/vault_backend.py`
  - `src/backend/infrastructure/secrets/vault_pki.py`
  - `src/backend/core/auth/sso_registry.py`
  - `tests/unit/core/config/test_vault_source_payload.py`
  - `tests/unit/core/config/test_config_sources_priority.py` (xfail → обычный тест)

## Контекст

Независимый свип функционала настроек (волна 15) зафиксировал 6 дефектов
кластера Vault/Consul. Все они — в зоне «секреты и runtime-конфиг»:

1. **[high] Секреты из Vault НЕ применялись.** `FilteredSettingsSource._filter_data`
   требовал вложенности `payload[yaml_group]`, а рантайм-читатели
   (`infrastructure/security/vault_secrets.py:159`, `core/secrets_sources.py:103`)
   ждут ПЛОСКИЙ `data[field]`. Проба: payload `{"value": 42}` → фильтр `{}`
   (значение не применено); `{"probe": {"value": 42}}` → применено. Итог:
   единственный реальный формат хранения секретов (плоский) не работал.
2. **[high] Consul runtime-config был мёртв.** `ConsulConfigSettingsSource._load_data`
   отдаёт плоский `{field: value}` (ключи KV под `runtime/{yaml_group}/`),
   а `_filter_data` искал `raw_data.get(yaml_group)` → `{}`. Проба:
   `{'initial_delay': '999'}` → в модели оставалось YAML-значение `3600`.
3. **[high] `_VAULT_UNREACHABLE` был липким навсегда.** Флаг ставился при первой
   неудаче и НЕ сбрасывался ни в `clear_vault_cache()`, ни в `reload_settings()`
   → после «подъёма» Vault секреты не приходили до рестарта процесса.
4. **[high] Потребители Vault читали только `os.environ`.** ADR-0372 перенёс
   `VAULT_ADDR`/`VAULT_SECRET_PATH` в YAML-секцию `vault`, но
   `vault_refresher.py`, `secrets_chain.py`, `vault_backend.py`, `vault_pki.py`,
   `sso_registry.py` игнорировали её: без env-переменной Vault считался
   «не сконфигурирован» даже при заданном `config_profiles/*.yml::vault`.
5. **[medium] Кэш секретов Vault не имел TTL** → ротация секрета не видна;
   `VaultSecretRefresher.start()` при этом нигде не вызывается.
6. **[medium] `tools/check_env_example.py` не разрешает наследование** → живые
   секреты помечаются «не используются» (свип: 9 — `AI_API_KEY`,
   `AI_PASSWORD`, `AI_USERNAME`, `MINIMAX_USERNAME`, `MINIMAX_PASSWORD`,
   `EXPRESS_SECRET_KEY`, `EXPRESS_SIGNATURE_SECRET`, `TELEGRAM_SECRET_KEY`,
   `TELEGRAM_SIGNATURE_SECRET`; прогон инструмента: «20 unknown»).
   Инструмент — **вне зоны кластера**.
7. **[high] Реальное окружение проигрывало `.env` при lowercase-ключе**
   (регресссия из кластера W4). `os.environ` на Linux регистрозависим, поэтому
   `.env` с ключом `app_gzip_minimum_size=777` и реальное окружение
   `APP_GZIP_MINIMUM_SIZE=999` — разные переменные; pydantic схлопывает их в
   один ключ (последний побеждает), а `_dotenv_only_keys` сравнивал ключи
   регистрозависимо → «файловым» считался ключ с любым case-варианом → env
   отбрасывался, применялось YAML. Регресссия уже была зафиксирована в
   `tests/unit/core/config/test_config_sources_priority.py` как `xfail`
   (W4/ADR-0379).

## Решение

### 1. Формат payload источников (дефекты 1 и 2)

`FilteredSettingsSource` получил флаг `flat_payload` (ClassVar):

* `False` (по умолчанию) — YAML-источник: берётся секция `payload[yaml_group]`;
* `True` — Vault и Consul: payload ПЛОСКИЙ (`ключ = имя поля модели`).

Вложенный формат (`{yaml_group: {...}}`) для плоских источников тоже
поддерживается: при наличии секции с именем `yaml_group` берётся она, иначе —
сам плоский payload. Итоговый формат, зафиксированный для продакшена:

| Источник | Формат payload | Пример |
|---|---|---|
| Vault (KV v2) | плоский `{"<field>": <value>}` | `{"db_password": "s3cr3t"}` |
| Vault (KV v2), вложенный | `{"<yaml_group>": {"<field>": <value>}}` | `{"database": {"db_password": "s3cr3t"}}` |
| Consul KV | плоский `{"<field>": <value>}` | `runtime/database/initial_delay = 999` |

Плоский payload Vault/Consul — общий для всех Settings-классов, поэтому
WARNING о неизвестных ключах для плоских источников выдаётся только когда
payload относится к этой модели (хотя бы одно поле совпало) — иначе один
секрет давал бы 40+ одинаковых сообщений.

### 2. Единый helper разрешения endpoint (дефект 4)

`core/config/vault.py::vault_endpoint()` и `::vault_secret_path()` — единственная
точка разрешения адреса и пути Vault для всех потребителей. Приоритет —
 ADR-0372 §5 (продолжен):

1. реальное окружение (`VAULT_ADDR`, не значение из `.env`);
2. YAML-секция `vault` (`config_profiles/*.yml`);
3. `.env` (последний fallback).

Тот же порядок использует источник Vault в `config_loader.py` — расхождение
между «источником» и «потребителями» исключено. `VAULT_TOKEN` остаётся
только в окружении (это секрет, в YAML секретов нет).

Потребители переведены на helper: `vault_refresher.py` (`start()`,
`_check_and_refresh()`, `_check_tracked_paths()`), `secrets_chain.py`
(`_vault_resolve()`), `vault_backend.py` (`VaultConfig.from_env()`),
`vault_pki.py` (`_get_client()`), `sso_registry.py` (`HvacVaultClient`).

### 3. Липкий флаг недоступности (дефект 3)

`_VAULT_UNREACHABLE` сбрасывается в `clear_vault_cache()` (hot-reload) и в
`reload_settings()`. После reload источник Vault снова пробует подключиться:
Vault поднят → секреты приходят без рестарта; Vault не поднят → тот же
fail-soft (один WARNING за попытку).

### 4. TTL кэша секретов (дефект 5)

`_VAULT_SECRET_CACHE` хранит `(payload, expires_at)`; TTL —
`_VAULT_CACHE_TTL_SECONDS = 300.0` (тот же интервал, что у
`VaultSecretRefresher`). Истёкшая запись перечитывается → ротация секрета
видна в настройках без рестарта. `clear_vault_cache()` очищает кэш целиком.

### 5. Регистронезависимое сравнение env/`.env` (дефект 7)

Два изменения в `config_loader.py`:

* `_dotenv_only_keys()` — ключ считается «из файла» только если НИ ОДИН его
  регистрозависимый вариант в окружении не содержит другого значения.
  Раньше достаточно было совпадения по точному регистру, и реальное
  окружение (в другом регистре) терялось;
* `_env_vars_for_source()` — env-source больше не берёт карту pydantic
  «последний побеждает»: для каждого логического ключа выбирается вариант,
  значение которого ОТЛИЧАЕТСЯ от значения `.env` (реальное окружение
  приоритетнее файла). Если такого варианта нет — ключ «из файла» и в
  env-source не попадает (его отдаёт dotenv-source ниже YAML).

Итог: `APP_GZIP_MINIMUM_SIZE=999` (окружение) побеждает `app_gzip_minimum_size=777`
(`.env`), а YAML по-прежнему выше `.env` (ADR-0372). Регресссия W4/ADR-0379
переведена из `xfail` в обычный тест.

## Альтернативы (отклонённые)

1. **Требовать вложенный payload и отдавать вложенный из Vault/Consul.**
   Отклонено: плоский формат — фактический (KV v2 отдаёт плоский dict, его
   же ждут рантайм-читатели `vault_secrets.py`/`secrets_sources.py`).
   Приведение к вложенному ломало бы совместимость с ними.
2. **YAML-приоритет над env в `vault_endpoint()`.** Отклонено: адрес Vault —
   операционный override (k8s ConfigMap), а ADR-0372 §5 уже закрепил
   «реальное env → YAML → `.env`»; тот же порядок даёт `VaultSettings.addr`,
   иначе источник и потребители смотрели бы в разные Vault.
3. **Сброс `_VAULT_UNREACHABLE` только в `reload_settings()`.** Отклонено:
   `clear_vault_cache()` — публичный hot-reload API, вызывается и без
   полного reload; флаг должен сбрасываться в обоих местах.
4. **TTL на стороне потребителей (refresher) вместо кэша источника.**
   Отклонено: кэш источника — то, что отдаёт значения в Settings; без TTL
   там ротация не видна даже при работающем refresher'е.
5. **Вынести `vault_endpoint()` в отдельный модуль без `VaultSettings()`.**
   Отклонено: лишняя абстракция; `core/config/vault.py` — каноническое
   место для настроек Vault.
6. **Чинить только `_dotenv_only_keys()` (без пересборки env-source).**
   Отклонено: pydantic схлопывает case-варианты в один ключ «последний
   побеждает» — без пересборки карты значение из `.env` (lowercase) всё
   равно перебивало бы реальное окружение (uppercase).
7. **Приводить `.env` к верхнему регистру при загрузке.** Отклонено:
   меняет имена переменных, которые 126+ мест в `src/` читают напрямую из
   `os.environ` (ADR-0372) — слишком широко для этого кластера.

## Последствия

* **Позитивные:** секреты из Vault реально применяются к настройкам;
  Consul runtime-config перекрывает YAML (как и обещает ADR-0372); после
  подъёма Vault секреты приходят по hot-reload без рестарта; ротация
  секрета видна в течение TTL; потребители Vault уважают YAML-конфиг;
  реальное окружение больше не теряется из-за другого регистра ключа
  в `.env` (W4/ADR-0379).
* **Негативные (требуют release-note):**
  (а) плоский payload Vault теперь применяется к полям моделей — если в
  секрете есть ключ, совпадающий с именем поля настройки (например
  `password`), значение из Vault перекрывает YAML/env. Это ожидаемое
  поведение (Vault — источник секретов, приоритет №3), но требует
  ревизии существующих секретов;
  (б) при отсутствии `VAULT_ADDR` в окружении потребители Vault теперь
  видят адрес из YAML (`http://127.0.0.1:8200` в base-профиле) — вместо
  «Vault не сконфигурирован». Для `vault_refresher` это означает запуск
  фонового refresh-loop в dev-профиле (цикл безвреден: ошибки логируются);
  (в) WARNING о неизвестных ключах для плоских источников выдаётся только
  для «своих» payload — опечатка в имени поля одиночного секрета без
  других совпадений останется незамеченной (её ловит
  `tools/config_audit.py` для YAML);
  (г) регистронезависимое сравнение env/`.env` меняет приоритет для ключей,
  которые есть в `.env` И в окружении в разном регистре: раньше
  окружение отбрасывалось, теперь оно побеждает файл (тот же приоритет,
  что у ADR-0372: реальное окружение выше `.env`).
* **Долги (вне зоны кластера W1):**
  1. `tools/check_env_example.py` — научить разрешать наследование
     (`.env.example` → профиль/наследование), иначе живые секреты
     помечаются «не используются» (дефект 6; прогон: «20 unknown»).
     **Владелец инструмента.**
  2. `VaultSecretRefresher.start()` нигде не вызывается — точка подключения
     фонового refresh-loop живёт в слое plugins/lifecycle
     (`plugins/composition/di.py`, `setup_infra/lifecycle.py`). **Вне зоны.**
  3. `tools/config_audit.py --scope orphans` → 4 расхождения
     `orphan-group:*:granian` (модель `core/scaling/granian_tuning.py` вне
     сканируемых каталогов). **Вне зоны, pre-existing.**

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/config/test_vault_source_payload.py \
    -q -p no:randomly -p no:plugins
.venv/bin/python -m pytest tests/unit/core/config -q -p no:randomly -p no:plugins
.venv/bin/python -m ruff check src/backend/core/config/config_loader.py \
    src/backend/core/config/vault.py \
    src/backend/infrastructure/application/vault_refresher.py \
    src/backend/infrastructure/resilience/components/secrets_chain.py \
    src/backend/infrastructure/secrets/vault_backend.py \
    src/backend/infrastructure/secrets/vault_pki.py \
    src/backend/core/auth/sso_registry.py \
    tests/unit/core/config/test_vault_source_payload.py \
    tests/unit/core/config/test_config_sources_priority.py
.venv/bin/python tools/check_layers.py --strict          # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
.venv/bin/python tools/config_audit.py --scope orphans    # 4 × granian (pre-existing)
```

Red→green (фактический прогон):

* **RED** (старое поведение, воспроизведено симуляцией):
  `test_flat_payload_is_applied`, `test_unknown_flat_keys_are_ignored`,
  `test_consul_value_wins_over_yaml` (payload-фильтр требовал вложенности),
  `test_cleared_by_clear_vault_cache` (липкий флаг),
  `test_default_ttl_is_300s` / `test_expired_entry_is_reread` / `test_fresh_entry_is_reused`
  (не было TTL) → **8 failed, 4 passed**;
  отдельно — старое регистрозависимое сравнение env/`.env`:
  `test_real_env_wins_over_lowercase_dotenv_key` (в обоих файлах) и
  `test_case_variant_with_other_value_is_not_file_only` → **3 failed, 39 passed**.
* **GREEN** (после фикса): `test_vault_source_payload.py` → **15 passed**;
  `test_vault_source_payload.py` + `test_config_sources_priority.py` → **42 passed**
  (регресссия W4 переведена из `xfail` в обычный тест).

Pre-existing падения (не связаны с кластером W1): `granian` orphan-groups
(4 профиля), `core/interfaces/test_{repositories,integrations}.py` —
`Protocol` runtime_checkable, а также порядок-зависимые падения в
`plugins/composition` (lifespan smoke).

## Связи с другими ADR

* **ADR-0372** — приоритет источников: этот ADR продолжает §5 (env → YAML →
  `.env`) и доводит его до потребителей Vault, которые ADR-0372 не охватил.
* **ADR-0373** — «`.env` — только секреты»: `vault_endpoint()` не поднимает
  `.env` выше YAML; `VAULT_TOKEN` остаётся только в окружении.
* **ADR-0375** — покрытие настроек и secret typing: формат payload Vault
  зафиксирован здесь, типизация секретов — там.
* **ADR-0379** (W4) — регресссия «реальный env проигрывает `.env` при
  lowercase-ключе» закрыта здесь: дефект был в `config_loader.py`
  (сравнение ключей регистрозависимо), тест лежал как `xfail` и переведён
  в обычный.
