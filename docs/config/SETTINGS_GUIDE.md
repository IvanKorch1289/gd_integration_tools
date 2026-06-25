# Settings Guide (Sprint 171 — M6.1)

> **Конфигурация, hot-reload, secrets, constants.**
> 30+ pydantic-settings модулей + Consul integration + file fallback.

## Архитектура

```
Config Profiles (YAML) → ConfigLoader → pydantic-settings
                                 ↓
                         @lru_cache singleton
                                 ↓
                  Hot-reload (watchfiles → on_reload)
                                 ↓
                            Services consume
```

**Слои:**
1. **YAML profiles** — `config_profiles/{base,dev,dev_light,prod,staging}.yml` (1274 lines, 38 top-level keys)
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

## Hot-reload (D-rule)

`src/backend/core/config/hot_reload.py`:
- `watchfiles.awatch` background task on `config_profiles/`
- Debounce window 0.5s
- Per-key lock для race-free reload
- Валидация падает → старая версия остаётся
- Audit emit для всех reload events
- Feature-flag: `feature_flags.route_loader_hot_reload` (default OFF до staging)

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

**File fallback**: если Consul disabled/unavailable → YAML profiles + pydantic-settings defaults.

## YAML config profiles

`config_profiles/`:
- `base.yml` (595 lines, 37 top-level keys) — defaults для всех
- `dev.yml` (193 lines, 15 keys) — dev environment overrides
- `dev_light.yml` (212 lines, 22 keys) — sqlite/aiosqlite dev mode
- `staging.yml` (126 lines, 13 keys) — staging-specific
- `prod.yml` (148 lines, 15 keys) — production overrides

**Inheritance**: env-specific profile накладывается поверх `base.yml`. Документировано в начале каждого профиля.

## D-rules (Configuration)

- **D155**: `BaseSettings` pattern (pydantic-settings + @lru_cache)
- **D156**: Hot-reload via watchfiles (debounced, locked, audited)
- **D157**: Consul opt-in (CONSUL_ENABLED), file fallback, fail-silent
- **D158**: Constants dataclass — single source for static values

## See also

- `src/backend/core/config/` — all settings classes
- `src/backend/core/config/constants.py` — Constants + re-exports
- `src/backend/core/config/hot_reload.py` — hot-reload mechanism
- `src/backend/core/config/config_loader.py` — multi-source loader
- `src/backend/infrastructure/security/cert_store/backend_consul.py` — Consul cert backend
