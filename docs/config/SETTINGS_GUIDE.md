# Settings Guide (Sprint 171 — M6.1)

> **Конфигурация, hot-reload, secrets, constants.**
> 30+ pydantic-settings модулей + Consul integration + file fallback.

## Архитектура

```
Источники (по приоритету):
  init → env → Vault → Consul → YAML → .env → file-secrets
                    ↓
            ConfigLoader (pydantic-settings)
                    ↓
              @lru_cache singleton
                    ↓
        Hot-reload (watchfiles → on_reload → Settings.reload())
                    ↓
              Services consume
```

**Слои:**
1. **YAML profiles** — `config_profiles/{base,dev,dev_light,prod,staging}.yml` (2025 lines, 152 top-level keys)
2. **ConfigLoader** — loads + merges base + env-specific
3. **pydantic-settings** — 30+ typed `*Settings` classes (`BaseSettings`)
4. **Singleton** — `@lru_cache` for each settings class
5. **Hot-reload** — `src/backend/core/config/hot_reload.py` (watchfiles)
6. **Consul** — opt-in runtime-config source (fail-silent fallback)

## Settings classes (30+)

| Module | Class | Purpose |
|--------|-------|---------|
| `core/config/settings.py` | `Settings` | Top-level aggregator |
| `core/config/base.py` | `AppBaseSettings` | App defaults |
| `core/config/ai.py` | `AIProvidersSettings` | OpenAI/MiniMax/etc. |
| `core/config/database.py` | `DatabaseConnectionSettings` | SQLAlchemy |
| `core/config/clickhouse.py` | `ClickHouseSettings` | Analytics |
| `core/config/elasticsearch.py` | `ElasticsearchSettings` | Search |
| `core/config/influxdb.py` | `InfluxDBSettings` | Time-series |
| `core/config/mongo.py` | `MongoConnectionSettings` | NoSQL |
| `core/config/rag.py` | `RAGSettings` | RAG pipeline |
| `core/config/security.py` | `SecureSettings` | Auth/AuthZ |
| `core/config/services.py` | `CacheSettings`, `FileStorageSettings` | Caching + storage |
| `core/config/plugin_loader.py` | `PluginLoaderSettings` | Plugin discovery |
| `core/config/express.py` | `ExpressSettings` | API express |
| `core/config/lineage.py` | `LineageSettings` | Data lineage |
| `core/config/dsl.py` | `DSLSettings` | DSL routing |
| `core/config/cert_store.py` | `CertStoreSettings` | TLS certs |
| `core/config/external_apis/*.py` | `*APISettings` | External API configs |
| `core/config/consul_config.py` | `ConsulConfig` | Consul source |
| `core/config/workflow.py` | `WorkflowSettings` | Temporal/LiteTemporal |
| `core/config/http_base.py` | `HttpBaseSettings` | HTTP defaults |
| `core/config/constants.py` | `Constants` | Static constants |

## Constants (Ponytail)

`src/backend/core/config/constants.py` — `Constants` dataclass:
- `ROOT_DIR`, `MOSCOW_TZ`, `RETRY_EXCEPTIONS`, `CHECK_SERVICES_JOB`, `INITIAL_DELAY`
- Re-exports from `_resilience_consts.py`:
  - `DEFAULT_CB_FAILURE_THRESHOLD`, `DEFAULT_CB_FAST_FAILURE_THRESHOLD`
  - `DEFAULT_CB_RECOVERY_SECONDS`, `DEFAULT_CB_FAST_RECOVERY_SECONDS`
  - `DEFAULT_RETRY_MAX_ATTEMPTS`, `DEFAULT_RETRY_INITIAL_BACKOFF`
  - `DEFAULT_RETRY_BACKOFF_MULTIPLIER`, `DEFAULT_RETRY_JITTER`

**Ponytail rule**: параметры processors (timeout, max_iterations) имеют sensible defaults в kwarg, не магические числа из constants.

Значения, которые действительно требуют настройки (retry/CB-пороги,
интервалы), вынесены в YAML — см. «Константы как конфигурация (ADR-0375)».

## Приоритет источников (ADR-0372)

`BaseSettingsWithLoader.settings_customise_sources` — единственное место,
где задан порядок. **Выше = приоритетнее** (побеждает остальных):

| # | Источник | Что задаёт | Как включается |
|---|---|---|---|
| 1 | init-параметры | `Settings(...)` / `SomeSettings(value=...)` | всегда |
| 2 | env процесса | реальные переменные окружения | всегда |
| 3 | Vault (KV v2) | секреты (`vault.enabled: true`) | `vault.enabled` / `VAULT_ENABLED` |
| 4 | Consul KV | runtime-конфиг, префикс `runtime/{yaml_group}/` | `CONSUL_ENABLED=true` + `CONSUL_ADDR` |
| 5 | YAML | несекретная конфигурация | `config_profiles/base.yml` + overlay профиля |
| 6 | `.env` | **только секреты** (см. `.env.example`) | файл `<repo_root>/.env` |
| 7 | file-based secrets | docker/secrets-файлы | всегда |

**Что перекрывает что:**

| Источник | Перекрывается | Комментарий |
|---|---|---|
| env процесса | всё | в т.ч. переменные из `.env`, если значение отличается от файла |
| Vault | YAML, `.env`, file-secrets | секреты Vault важнее локального файла |
| Consul | YAML, `.env`, file-secrets | runtime-конфиг важнее статичного YAML |
| YAML | `.env`, file-secrets | несекретные значения живут только здесь |
| `.env` | file-secrets | заполняет лишь то, чего нет в YAML/Consul/Vault |

**Важно про `.env`:**

* `.env` — **отдельный источник с приоритетом №6**, а не подмена
  окружения: значения из файла не перебивают YAML/Vault/Consul.
  Значение из `.env`, совпадающее с реальной переменной окружения,
  считается реальной переменной (окружение приоритетнее файла).
* `.env` читается явно: `load_env_file()` /
  `ensure_env_file_loaded()` в `config_loader.py`; точка загрузки — **вход
  в цепочку источников** (`settings_customise_sources`), а не импорт
  модуля. CLI может вызвать `load_env_file()` раньше — вызов идемпотентный.
* Секреты в YAML быть не должно — гейт `tools/config_audit.py` и
  `tools/check_env_example.py --secrets-only`.

**Порядок загрузки в runtime:**

```
init → env → Vault → Consul → YAML → .env → file-secrets
```

**Fail-closed / fail-soft:**

* YAML — **fail-closed**: нет `config_profiles/{profile}.yml` → `RuntimeError`
  на старте (тихий откат на дефолты запрещён);
* Vault / Consul — **fail-soft**: недоступны → источник отдаёт `{}`,
  конфигурация собирается из остальных.

## Hot-reload (D-rule)

`src/backend/core/config/hot_reload.py`:
- `watchfiles.awatch` background task on `config_profiles/` (абсолютные
  пути от корня репозитория — не зависят от CWD)
- Debounce window 0.5s
- Валидация падает → старая версия остаётся
- Audit emit для всех reload events
- Feature-flag: `feature_flags.route_loader_hot_reload` (default OFF до staging)

**`Settings.reload()` (ADR-0372):** перечитывает все источники, сбрасывает
YAML-кэш и кэш секретов Vault, пересоздаёт вложенные `Settings` и
модульные синглтоны и обновляет их **in-place** (ссылки потребителей
не ломаются). Отчёт: `{"reloaded": [...], "failed": [...]}`.

**Честный отчёт:** `POST /api/v1/admin/config/reload` возвращает
`succeeded`/`failed`/`callbacks`/`ok`; отсутствие `settings.reload()` или
ошибка callback'а — это **ошибка** (`failed` непустой), а не «успех».

## Consul integration (D-rule)

**2 integration points:**
1. `ConsulCertBackend` (`src/backend/infrastructure/security/cert_store/backend_consul.py`)
   - Cert store: Consul KV v2 с `pem`, `fingerprint`, `expires_at`
   - History: single-element (Consul KV v2 не имеет native history)
   - Lazy import + fail-silent (если Consul недоступен)

2. `ConsulConfigSettingsSource` (`src/backend/core/config/config_loader.py`)
   - Hot-reload runtime-config из Consul KV
   - Opt-in через `CONSUL_ENABLED=true` + `CONSUL_ADDR`
   - Fail-silent: `load_data()` returns `{}` if unreachable
   - Prefix: `runtime/{yaml_group}/`
   - **Приоритет выше YAML** (ADR-0372) — иначе Consul-перекрывался YAML

**File fallback**: если Consul disabled/unavailable → YAML profiles + pydantic-settings defaults.

## YAML config profiles

`config_profiles/`:
- `base.yml` (994 lines, 69 top-level keys) — defaults для всех
- `dev.yml` (198 lines, 15 keys) — dev environment overrides
- `dev_light.yml` (226 lines, 23 keys) — sqlite/aiosqlite dev mode
- `staging.yml` (277 lines, 22 keys) — staging-specific
- `prod.yml` (330 lines, 23 keys) — production overrides

**Inheritance**: env-specific profile накладывается поверх `base.yml`. Документировано в начале каждого профиля.

### Покрытие yaml-групп (ADR-0375)

Каждая из 70 yaml-групп (`yaml_group: ClassVar[str]`) обязана иметь
секцию в `base.yml` **или** быть перечислена в
`tests/unit/core/config/yaml_group_allowlist.txt` с явной причиной:

| Исключение | Причина |
|---|---|
| `features` | `profile-overlay-only` — 262 feature-флага задаются per-профиль |
| `workflow` | `runtime-only` — модель без полей (extension point) |

Секции в `base.yml` содержат **только несекретные поля**; значения равны
дефолтам моделей (поведение не меняется — параметр становится
конфигурируемым). Гейт: `tests/unit/core/config/test_yaml_group_coverage.py`
(плюс `tools/config_audit.py --scope orphans` → 0).

### Merged-валидация профиля (ADR-0375)

`python manage.py validate-profile <env>` валидирует **слиянный** конфиг
(`base.yml` + overlay), а не только overlay:

1. синтаксис overlay-файла;
2. merge base + overlay (`core/config/validator/profile_merge.py`);
3. prod-инварианты по merged-значениям;
4. `ConfigValidator` по merged-конфигу → CRITICAL = exit 1,
   WARNING = exit 1 при `--strict`;
5. секция `constants` — ограничения полей (`ge=0` / `gt=0`) → CRITICAL
   = exit 1 (ADR-0377).

CLI не требует секретов: секции собираются через `model_construct`.

### Профили без env-плейсхолдеров (ADR-0377)

**YAML-профили не поддерживают подстановку `${VAR:-default}`.** Загрузчик
(`core/config/config_loader.py`) читает YAML как есть, а Helm эти файлы не
шаблонизирует — плейсхолдер попадал в рантайм как есть:

* `policy.opa_url = "${OPA_URL:-http://opa:8181}"` → OPA-клиент получал
  невалидный URL, все решения становились `deny` (`opa_unavailable`);
* `policy.casbin_model_path = "${CASBIN_MODEL_PATH:-...}"` →
  `FileNotFoundError: '${CASBIN_MODEL_PATH:-/etc/casbin/model.conf}'`.

Правило: **в YAML — только литералы**, переопределение — через env
(приоритет env выше YAML, ADR-0372). Для policy-движков префикс —
`POLICY_` (`core/config/services/policy.py::PolicySettings`):

| YAML-ключ | env-переменная |
|---|---|
| `policy.opa_url` | `POLICY_OPA_URL` |
| `policy.opa_policy_name` | `POLICY_OPA_POLICY_NAME` |
| `policy.casbin_model_path` | `POLICY_CASBIN_MODEL_PATH` |
| `policy.casbin_policy_path` | `POLICY_CASBIN_POLICY_PATH` |
| `policy.engine_enabled` | `POLICY_ENGINE_ENABLED` |

Гейт: `tests/unit/core/config/test_profile_invariants.py` — в строковых
значениях всех YAML-профилей нет `${...}`.

### WAF allowlist и внешние интеграции (ADR-0377)

При `waf.strict=true` исходящий запрос к хосту вне `waf.allow_hosts`
блокируется (`core/net/waf.py` → `WafBypassError`). Поэтому в prod/staging
allowlist обязан содержать хосты внешних интеграций
(`src/backend/services/integrations/**`):

| Интеграция | YAML-ключ | Хост в allowlist |
|---|---|---|
| СКБ-Техно | `skb.prod_url` | `api.skb-techno.ru` |
| DaData | `dadata.base_url` | `suggestions.dadata.ru` |

Запросы этих интеграций идут **напрямую** (минуя WAF-шлюз
`http.waf_url`) — без allowlist'а они полностью не работали.
Webhook-relay (`services/integrations/webhook_relay.py`) в allowlist не
входит: цели задаются динамически, per-webhook.

Гейт: `test_profile_invariants.py` — allowlist prod/staging покрывает
хосты интеграций, и проба `WafPolicy.evaluate(url)` даёт `allowed`.

### Секция `constants` (ADR-0377)

Значения секции `constants` применяются к глобальному синглтону `consts`
при создании `ConstantsSettings` — невалидное значение роняет **старт**
процесса (`ValidationError`). Поэтому `validate-profile` проверяет секцию
явно (CRITICAL при нарушении ограничения), а валидация не трогает
рантайм-состояние: значения применяются к `consts` только при реальной
загрузке настроек, не в CLI-отчёте.

### Секция `granian` (ADR-0377)

`src/backend/core/scaling/granian_tuning.py` (`yaml_group="granian"`) живёт
вне каталога `core/config` — секция `granian:` в `base.yml` (ADR-0377)
возвращает эти 10 полей в зону yaml-конфигурации. Значения равны дефолтам
модели; env-префикс — `GRANIAN_`.

## Константы как конфигурация (ADR-0375)

`src/backend/core/config/constants_settings.py` — `ConstantsSettings`
(`yaml_group="constants"`): те же значения, что у `consts`
(`INITIAL_DELAY`, `RETRY_DELAY`, `MAX_RESULT_ATTEMPTS`, `DEFAULT_CB_*`,
`DEFAULT_RETRY_*`), но в секции `constants:` файла `base.yml`.

* значения YAML применяются к **инстансу** `consts` (мутация) — потребители
  `consts.X` видят новое значение без правки вызовов;
* hot-reload: `Settings.reload()` пересоздаёт модульный синглтон →
  `model_post_init` переприменяет значения → правка YAML меняет константы
  в рантайме;
* Consul для констант **не используется** (его роль — DSL-переменные и
  cert_store), секретов в группе нет.

Предел: значения, схваченные как default поля dataclass'а на импорте
(`BreakerConfig.failure_threshold = consts.DEFAULT_CB_FAILURE_THRESHOLD`),
обновляются только после перезапуска процесса.

## Секреты (ADR-0373 / ADR-0375)

Секретные поля конфигурации типизированы как `SecretStr`: значение
маскируется в `repr()` и в логах. Читателям, которым нужна строка,
помогает `core/config/secret.py::secret_value` (терпим к `SecretStr`,
`str`, `None`). Публичные контракты не сломаны: `AuthConfig.api_key`,
`redis_url`, HTTP-заголовки и параметры SDK остаются строками.

## D-rules (Configuration)

- **D155**: `BaseSettings` pattern (pydantic-settings + @lru_cache)
- **D156**: Hot-reload via watchfiles (debounced, locked, audited)
- **D157**: Consul opt-in (CONSUL_ENABLED), file fallback, fail-silent
- **D158**: Constants dataclass — single source for static values

## See also

- `src/backend/core/config/` — all settings classes
- `src/backend/core/config/constants.py` — Constants + re-exports
- `src/backend/core/config/constants_settings.py` — константы из YAML (ADR-0375)
- `src/backend/core/config/secret.py` — извлечение значения секрета (ADR-0375)
- `src/backend/core/config/validator/profile_merge.py` — merged-валидация профиля (ADR-0375)
- `src/backend/core/config/hot_reload.py` — hot-reload mechanism
- `src/backend/core/config/config_loader.py` — multi-source loader
- `src/backend/core/scaling/granian_tuning.py` — Granian RSGI tuning (ADR-0059)
- `src/backend/infrastructure/security/cert_store/backend_consul.py` — Consul cert backend
- `docs/adr/0375-settings-coverage-merged-validation-constants-and-secret-typing.md`
- `docs/adr/0377-profile-placeholders-waf-allowlist-and-validation.md`
