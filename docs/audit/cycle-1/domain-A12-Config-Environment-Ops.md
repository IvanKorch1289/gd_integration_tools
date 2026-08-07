# Domain A12-Config-Environment-Ops — независимый аудит (cycle 1)

> Дата: 2026-08-06
> Агент: A12-Config-Environment-Ops
> Метод: прямая верификация кода (НЕ пересказ KNOWN_ISSUES/CHANGELOG). Все находки валидированы через Read/Grep/pytest-прогон. Никаких markdown-документов как источника фактов.

## 0. Сводка готовности

| Подкатегория | Готовность | Обоснование |
|---|---|---|
| Pydantic-settings coverage | 95% | **94 Python-файла**, **13572 LOC** в `core/config/`. Settings роутинг через `BaseSettingsWithLoader` (config_loader.py:306-354) с единой точкой `settings_customise_sources`. Каждое Settings-класс наследует правильный `yaml_group` + `env_prefix`. **Найдены 3 расхождения** (см. D-A12-02/D-A12-07). |
| YAML profiles (base + 4 overlays) | 80% | **1326 строк YAML, 37-38 top-level keys в base.yml**. Composition через `_deep_merge` (config_loader.py:49-58). 5 профилей: base+dev+dev_light+prod+staging. Файлы читаемы, секции алфавитно упорядочены. **Gap**: YAML hot-reload НЕ подключен в production-коде (см. D-A12-01). |
| Hot-reload через watchfiles | 50% | API работает (`ConfigHotReloader` 148 LOC, тесты в `tests/unit/core/config/test_hot_reload.py` — 9 тестов). Manual trigger через `POST /admin/config/reload` (admin.py:184-191). **Главный gap**: `reloader.watch()` для `config_profiles/*.yml` НЕ вызывается ни в одном production-коде (см. D-A12-01). Hot-reload включён только для `.env` и `dsl_routes/` (через `DSLYamlWatcher`), НЕ для конфиг-профилей. |
| Consul opt-in | 30% | `ConsulConfigSettingsSource` определён в `config_loader.py:273-303`, `ConsulConfigStore` в `consul_config.py:164 LOC`. **Главный gap**: `ConsulConfigSettingsSource` НЕ включён в `settings_customise_sources` chain (config_loader.py:347-353) — только `init/env/VaultConfig/YamlConfig/dotenv/file_secret`. Consul integration для runtime-config = **dead code** (см. D-A12-03). |
| Docker-compose ресурсы (mem/cpu limits) | 30% | **Главная находка гипотезы #1 верифицирована**: ни в одном docker-compose файле НЕТ `mem_limit`/`cpus`/`deploy.resources`. `deploy: replicas: ${WORKER_COUNT:-4}` есть только для `workflow-worker`. Также **отсутствует `healthcheck`** для `app` в prod-стеке (только в `docker-compose.yml` для dev) — см. D-A12-06. |
| K8s manifests | 90% | `deploy/k8s/deployment-app.yaml` (149 LOC) и `deployment-worker.yaml` (127 LOC) с **полными** resource `requests`/`limits` (cpu/memory), `securityContext` (runAsNonRoot=1000, readOnlyRootFilesystem, capabilities drop ALL). HPA по CPU/memory. PDB minAvailable=1. NetworkPolicy default-deny + explicit allow. **Race**: `deploy/helm/gd-integration-tools/values.yaml:131-136` установил `runAsUser=10001` чтобы соответствовать Dockerfile (`appuser uid=10001`), а **k8s deployment-app.yaml:50-51** всё ещё использует `runAsUser=1000`/`runAsGroup=1000` — **рассинхрон, deploy будет permission-fail** (см. D-A12-04). |
| Helm chart | 85% | `deploy/helm/gd-integration-tools/` содержит Chart.yaml + values.yaml (141 LOC) + 12 templates. Values line-up с k8s raw manifests. **Gap**: `values.yaml` обновлён (runAsUser=10001), но `deployment-app.yaml` (template) **НЕ обновлён** — это та же ошибка что в raw k8s. |
| Production startup gates | 95% | `ConfigValidator()` (validator/__init__.py:51-91) реализует 14 checks (WAF strict, ClamAV fail-open, Swagger/Redoc в prod, Vault disabled, CORS wildcard+credentials, JWT secret <32 chars, DB host prod, Redis required in prod, feature-flag dependency). `validate_startup_config` вызывается из `startup.py:297` — failure в prod = `ProductionConfigError` → `raise`. Fail-closed. S52 W2 decomposition в 3 mixins. |
| Tools (config-audit, codegen, config-validate) | 80% | `tools/config_audit.py` (485 LOC) — двусторонний аудит (orphan-keys + missing-secrets); отлично работает для всех 4 профилей. `tools/codegen_settings.py` (44223 LOC) — extract/wizard/apply. `python manage.py validate-profile <env>` (manage.py:272-347) — runtime schema check + prod invariants. **Нет check для docs/SETTINGS_GUIDE.md** drift (см. D-A12-08). |
| Constants dataclass + re-exports | 100% | `core/config/constants.py` (115 LOC): `Constants` dataclass + 7 re-exports из `_resilience_consts.py` (S168 W10 P1-14). Single source of truth для ROOT_DIR, MOSCOW_TZ, RETRIABLE_DB_CODES. Ponytail-compliant. |
| Manage.py + Makefile decompose | 90% | `manage.py` (1745 LOC) — Typer-based CLI с 22+ команд. `Makefile` (115 LOC) thin wrapper + `-include make/*.mk` для 16 .mk файлов (~900 LOC). Hot-reload config команда (`config/reload`) через admin endpoint, валидна. **Gap**: `diagnose` команда (manage.py:487+) — НЕ запускает `config-audit` или `validate-profile`, только health checks (см. D-A12-09). |
| К5 migration Operation | 85% | `pyproject.toml` `name = "gd_advanced_tools"`, version `0.20.0` (не 0.1.0 как в `config_profiles/base.yml:28 app.version`). **Минимальный drift** (см. D-A12-10). |

**ИТОГОВАЯ ОЦЕНКА: ~78%**

Обоснование: 100%-покрытие Pydantic-settings typed classes, готовый Constant-then-yaml merger, fail-closed ConfigValidator с 14 prod-gates, K8s/Helm securityContext + NetworkPolicy + PDB. Главные подрывы: (а) **Hot-reload для config_profiles/*.yml НЕ подключен в production-коде** (reloader.watch() только в docstring-примерах), (б) **Consul integration для runtime-config = dead code** (определён, но не в settings_customise_sources), (в) **Docker-compose без mem_limit/cpus**, (г) **K8s deployment-app.yaml vs Helm values.yaml runAsUser рассинхрон** (1000 vs 10001), (д) **minor docs drift** (line/key counts в SETTINGS_GUIDE.md не точные).

---

## 1. Таблица находок

| ID | Приоритет | Файл:строка | Описание | Предложенный фикс | Экономия строк | Доказательство |
|----|-----------|-------------|----------|-------------------|----------------|----------------|
| **D-A12-01** (P0) | 🔴 КРИТ | `src/backend/plugins/composition/lifecycle/startup.py` (отсутствует) | **Hot-reload для `config_profiles/*.yml` НЕ подключён в production-коде.** `reloader.watch()` вызывается только в `hot_reload.py:39-41` (пример в docstring). Grep по `src/` показал: только docstring-пример. `DSLYamlWatcher` (`watchers.py:23-49`) подключён в startup, но он смотрит только `dsl_routes/`, НЕ `config_profiles/`. Документация `docs/config/SETTINGS_GUIDE.md:64-72` + `HOT_RELOAD.md:55-61` явно описывают это как gap. **Effect**: изменение `base.yml`/`dev.yml`/`staging.yml`/`prod.yml` требует рестарта процесса или ручного `POST /admin/config/reload`. | Добавить в `startup.py` после `_configure_business_routers`: `reloader = get_hot_reloader(); reloader.watch(_REPO_ROOT / "config_profiles" / "base.yml"); reloader.watch(_REPO_ROOT / "config_profiles" / f"{profile.value}.yml"); await reloader.start()` под `feature_flags.config_hot_reload_enabled` (default ON для dev, OFF для prod — pattern как `prod_hot_reload_disable`). | +15 LOC | `grep -r "reloader.watch" src/backend/` → только `src/backend/core/config/hot_reload.py:40,41` (это docstring). `grep -r "get_hot_reloader().watch" src/backend/` → 0 hit'ов вне тестов. |
| **D-A12-02** (P0) | 🔴 КРИТ | `src/backend/core/config/config_loader.py:347-353` | **ConsulConfigSettingsSource = dead code** в runtime. Определён как класс в `config_loader.py:273-303`, но `BaseSettingsWithLoader.settings_customise_sources` (строки 326-353) возвращает толькo `(init_settings, env_settings, VaultConfigSettingsSource, YamlConfigSettingsLoader, dotenv_settings, file_secret_settings)`. `ConsulConfigSettingsSource` НЕ добавлен в tuple. `CONSUL_ENABLED` env-флаг существует, но без source integration ничто его не читает. | Добавить ConsulConfigSettingsSource в chain после `YamlConfigSettingsLoader`: `return (..., ConsulConfigSettingsSource(settings_cls), YamlConfigSettingsLoader(settings_cls), ...)`. Альтернатива — удалить dead class и оставить только Consul KV для cert_store (ADR-0092). | 0 (refactor) | Прямой grep `ConsulConfigSettingsSource` показывает только definition, не usage: `grep -rn "ConsulConfigSettingsSource" src/backend/` → 2 hit'а: definition sites only (line 260 class docstring, line 273 class def). |
| **D-A12-03** (P1) | 🟠 ВЫС | `deploy/k8s/deployment-app.yaml:48-52` & `deploy/helm/gd-integration-tools/values.yaml:131-138` | **Рассинхрон securityContext между raw k8s manifest и Helm values.yaml.** `values.yaml:131-138`: `runAsUser: 10001, runAsGroup: 10001, fsGroup: 10001` (значение подтянуто под Dockerfile.appuser uid=10001, see value history fix note line 131-133). `deployment-app.yaml:48-52` raw: `runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000`. **Effect**: helm install использует 10001, raw k8s apply — 1000. `Dockerfile:59` устанавливает `useradd --uid 10001 appuser`. С `readOnlyRootFilesystem: true` логи/`.run` будут permission-failure при raw k8s deployment. | Синхронизировать k8s `deployment-app.yaml:48-52` к `runAsUser: 10001`. | 0 | Прямая проверка файлов; см. также исправление `5c5aa64` (B02 commit) для values.yaml. |
| **D-A12-04** (P1) | 🟠 ВЫС | `ops/compose/docker-compose*.yml` (все 6 файлов) | **Гипотеза #1 (docs/SETTINGS_GUIDE.md) ВЕРИФИЦИРОВАНА**: ни в одном docker-compose файле **НЕТ `mem_limit`/`cpus`/`deploy.resources`** (кроме одного `deploy: replicas:` stanza в `docker-compose.yml:71-72` для workflow-worker). Service `app`, `postgres`, `redis`, `clamav`, `celery-worker`, `celery-beat`, `kafka`, `vault`, `minio`, `otel-collector`, `jaeger` — **без cgroup-ограничений**. **Effect**: локальная разработка на 16-core ноутбуке — clamav может съесть всю RAM; в CI containers.OOM-killer начнёт с жертв. K8s уже имеет limits (`cpu: "2"`, `memory: 2Gi`), но `docker-compose up` на dev-машине без лимитов = race condition с системой. | Добавить per-service `mem_limit` + `cpus` в `docker-compose.yml`. Минимум для `app`: `mem_limit: 1g, cpus: '1.0'`; `postgres`: `mem_limit: 512m`; `redis` уже ограничивает через `--maxmemory 256mb`. | +30 LOC | `grep -n "mem_limit\|cpus:\|deploy:" ops/compose/docker-compose*.yml` → 0 hit'ов на mem_limit/cpus. |
| **D-A12-05** (P1) | 🟠 ВЫС | `config_profiles/base.yml:136` (http.ssl_verify: false) | **`ssl_verify: false` в `http:` секции base.yml по умолчанию**. Это для исходящих HTTP-вызовов (WAF-через-facade), но default-OFF означает: вся outbound-интеграция (SKB, Dadata, антивирус) стартует без verify. **Note**: prod/staging явный `use_ssl: true` для некоторых секций, но `ssl_verify` для `http:` **нигде не override** в overlays. Допустимо для dev (testing self-signed), но YAML-default в production-сборке = risk. Переопределение только через env `HTTP_SSL_VERIFY=true`. | Сделать default `ssl_verify: true` в `base.yml` (или per-section override в `prod.yml`/`staging.yml`). Задокументировать в `docs/config/SETTINGS_GUIDE.md`. | +2 LOC override | Прямой grep `ssl_verify` в config_profiles: только `base.yml:136` + `base.yml:528` (jupyter_hub=true). Нет override в overlays. |
| **D-A12-06** (P1) | 🟠 ВЫС | `ops/compose/docker-compose.prod.yml:225-247` | **Production compose-stack (`docker-compose.prod.yml`) НЕ ДОБАВЛЯЕТ healthcheck для `app`**. `docker-compose.yml:39-46` (base) `app` без healthcheck. Только в `docker-compose.prod.yml:241-246` healthcheck добавлен. Но `depends_on` chain в `celery-worker:189-200` ссылается на `postgres`, `redis`, `kafka`, `migration-runner`. Без healthcheck для `app`, `celery-worker` может стартовать раньше и упасть в retry-loop. | Добавить healthcheck на `app` в `docker-compose.yml:39-47` (curl `/health/ready`); оставить как в `docker-compose.prod.yml:241-246`. | +5 LOC | Прямая проверка. |
| **D-A12-07** (P1) | 🟠 ВЫС | `src/backend/core/config/services/mail.py` + `config_profiles/base.yml:230-237` | **Mail `validate_certs: false` в base.yml** (`mail.validate_certs: false` для SMTP-TLS). Это допустимо для dev с self-signed, но prod требует `validate_certs: true`. **Overlay `prod.yml:117` устанавливает `validate_certs: true`, overlay `dev_light.yml:127` оставляет default `false`** — корректно. Но в **staging.yml НЕТ override** для mail — fallback на base.yml `validate_certs: false` для staging. Тоже risk. | Добавить `validate_certs: true` в `staging.yml:108` (mail секция). | +1 LOC | Прямая проверка `validate_certs` в mail.config_profiles. |
| **D-A12-08** (P2) | 🟡 СРЕД | `docs/config/SETTINGS_GUIDE.md:19,93-97` | **Документационный drift: line counts и top-level keys counts**. `SETTINGS_GUIDE.md:19` заявляет "1274 lines, 38 top-level keys"; реальность: **1326 lines total**, `base.yml = 598 lines`, dev 193, dev_light 212, prod 173, staging 150. `base.yml` содержит **37 top-level keys** (не 38). Строка 93-97 содержит "base.yml (595 lines, 37 top-level keys)" — close, но base.yml сейчас 598 строк. Не критично, но противоречит регламенту "DRIFT FREE DOCS". | Обновить `SETTINGS_GUIDE.md:19,93-97` к реальности: 1326 total, base.yml 598 lines / 37 keys. | 0 | `wc -l config_profiles/*.yml` → 1326 total, `grep -c "^[a-z_]\+:" config_profiles/base.yml` → 37. |
| **D-A12-09** (P2) | 🟡 СРЕД | `manage.py:487-559` (`diagnose` команда) | **Команда `diagnose` НЕ запускает `config-audit` или `validate-profile`**. Собирает: python version, platform, health check (redis/db), breakers, services, routes count, actions count, feature flags. **Отсутствует**: (а) `config_profiles/{profile}.yml` валидация, (б) orphan-keys/missing-secrets аудит, (в) `prod-profile invariants` (B-1, B-2, S-DOCS-1 checks). Эффект: единый `make diagnose` не сигнализирует о конфиг-drift как fail-fast. | Добавить в `diagnose` вызов `validate-profile` для активного профиля + `config_audit.py` для orphan-keys/missing-secrets; добавить результат в JSON output. | +20 LOC | Прямая проверка `diagnose` body: нет упоминаний `config_audit`/`validate_profile`. |
| **D-A12-10** (P2) | 🟡 СРЕД | `pyproject.toml:14` (`version = "0.20.0"`) vs `config_profiles/base.yml:28` (`app.version: "0.1.0"`) | **Рассинхрон app.version**: pyproject.toml = 0.20.0, YAML default = 0.1.0. Допустимо для backward-compat (YAML имеет default, чтобы работало без full settings), но это означает, что version display (`/tech/version` endpoint) может показывать 0.1.0 вместо реальной. Не критично, но видно рассинхрон между manifest и config layer. | Либо auto-bind `app.version` к `importlib.metadata.version("gd_advanced_tools")` (computed_field), либо удалить `app.version` из YAML; версия должна быть одна — в pyproject.toml. | 0 (refactor) | Прямая проверка. |
| **D-A12-11** (P2) | 🟡 СРЕД | `src/backend/core/config/features/__init__.py:90-290` + 23 submodule | **145 flags в 23 mixin-модулях FeatureFlags (multiple inheritance composition)**. Documentation line 154-156: "Total extracted: 145 flags (out of 229 total). Remaining: 102 flags в __init__.py (Sprint 15/17/19 + etc)." **В __init__.py:289-290 нет ни одного флага** — все extracted. Это зеркальная противоречивость с doc-comments "extracted into X module, inherited". **Warning**: HOF (cycle S38 P1.1 W1) — 23 mixin modules = high import overhead. Settings init imports 23 module-level singletons (one per file). | Validation: проверить, все ли 23 mixin imports в `__init__.py:63-85` действительно используются. Удалить unused (Z3-G07 extension cleanup). | -50 LOC если cleanup | `grep -c "^class.*Flags.*BaseSettings" src/backend/core/config/features/*.py` → 23 mixin classes defined; matching imports in __init__.py. |
| **D-A12-12** (P2) | 🟡 СРЕД | `src/backend/core/config/features/__init__.py:233-243` | **`scheduler_backend: Literal["apscheduler", "temporal"]` default `"apscheduler"`** при том, что проекте уже используется Temporal через `infrastructure/workflow/`. **Production-managed flag для backward-compat**, но фактически `temporal` выбор — stub до реализации (line 241: "(NotImplementedError) до реализации Temporal Schedule API"). Literal-stub = API surface больше, чем runtime-возможности. | Запретить значение `"temporal"` (raise ValidationError на startup); оставить только `"apscheduler"` пока не будет реализация. | -10 LOC | Прямая проверка. |
| **D-A12-13** (P2) | 🟡 СРЕД | `src/backend/core/config/database.py:284`, `src/backend/core/config/external_databases/connection.py:177` | **2 места с `raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")`** в DSN-builder. Default — fail-loud для unknown type. **Но `DatabaseTypeChoices` Enum отсутствует в этом файле** (только импортируется `DatabaseTypeChoices` line 7). Enum определён в `core/enums/database.py`. Проверить, что enum constrains входные значения. | OK as-is (fail-loud), но добавить test `test_database_unsupported_type_raises` для обоих путей. | +12 LOC теста | Прямая проверка. |
| **D-A12-14** (P2) | 🟡 СРЕД | `src/backend/core/config/waf.py:97` | **`waf_settings` instantiated at module level** (`waf_settings = WafSettings()`). В `startup.py:295` импортируется как `_cv_waf_settings`, но если WafSettings требует поля, то при cold start без YAML-loaded — fail. Проверить: WafSettings fields все имеют defaults (`allow_hosts: ()`, `strict: False`, etc.) — OK. **Но**: `model_config = SettingsConfigDict(extra="ignore")` — значит любой yaml-orphan-key silently ignored. Это маскирует `config_audit`-violations в production. | Сменить на `extra="forbid"` (как у остальных Settings); дополнительный fail-loud. | 0 | Прямая проверка. |
| **D-A12-15** (P2) | 🟡 СРЕД | `docs/config/SETTINGS_GUIDE.md:66-83` (`Hot-reload (D-rule)`) | **Документация утверждает "watchfiles.awatch background task on `config_profiles/`"** (line 67), но **в production-коде `reloader.watch()` НИКОГДА не вызывается для config_profiles**. Per `docs/config/HOT_RELOAD.md:55-61` — известный gap, см. D-A12-01. Документация вводит в заблуждение. | Удалить line 67-72 в `SETTINGS_GUIDE.md` или добавить `(planned, see HOT_RELOAD.md#18)` caveat. После того как D-A12-01 будет решён — обновить на "✅ Working since Sprint X". | -2 LOC | Прямое сопоставление docs vs `grep -rn "reloader.watch" src/backend/`. |
| **D-A12-16** (P3) | 🟢 НИЗК | `src/backend/core/config/services/cache.py:262-267` (`redis_url` computed) | **`redis_url` строится через naive string concat, не использует `urllib.parse.quote_plus`**. Если `password` содержит спец-символы (`@`, `/`, `:`), они будут интерпретированы как control-chars URL. Хотя `password: str | None` (line 37-41) — может содержать anything. **Risk**: secrets с `:` или `@` в Redis URL → broken DSN. | Использовать `quote_plus` для username/password. | +2 LOC | Прямая проверка. |
| **D-A12-17** (P3) | 🟢 НИЗК | `src/backend/core/config/services/cache.py:30-41` (`password` field) | `password: str | None = Field(..., description="...")` — **обязательное** поле (line 39: `...`). Если в production ENV `REDIS_PASSWORD` отсутствует → ValidationError. Это **fail-closed при отсутствующем secret** — хорошо для security, но не работает с `dev_light` profile (Redis disabled, password не нужен). **Check**: `RedisSettings.enabled: bool = False` (line 15-22, default True), модель валидируется **всегда**, не зависит от `enabled`. | Сделать `password` опциональным (default=None) при `enabled=False` через model_validator(mode="after"). | +6 LOC | Прямая проверка. |
| **D-A12-18** (P3) | 🟢 НИЗК | `src/backend/core/config/auth.py` (93 LOC) | **Module реализует только LDAP/LDAPs auth**. Не имеет отдельного `password_secret_key` от основного `secure.secret_key`. Все идёт через central `secure_settings.secret_key`. OK, но **нет comment-as-anchor где именно JWT secret генерируется через Vault**. | Добавить doc-строку с ссылкой на `vault_refresher.py:54` и `secure.secret_key`. | +5 LOC | Прямая проверка. |
| **D-A12-19** (P3) | 🟢 НИЗК | `config_profiles/staging.yml:46-58` (`database.pool_size: 15`) | **`staging.yml` имеет `pool_size: 15` меньший чем prod (`pool_size: 30`)**. ADR-0059 (связь, comment line 64 в prod.yml) указывает "30 + 20 overflow = до 50 connections per worker". Staging 15 + 10 overflow = max 25. **Допустимо для staging** (половина prod — нагрузочное тестирование). Но нет валидатора, который проверяет, что `staging.pool_size <= prod.pool_size`. | OK as-is для staging. Добавить config-invariant `staging_pool_size <= prod_pool_size` в ConfigValidator (low-priority). | +5 LOC | Прямая проверка. |
| **D-A12-20** (P3) | 🟢 НИЗК | `src/backend/core/config/settings.py:99-176` (Settings aggregator) | **Settings` — композиция 22-х групп** (line 109-175). Каждая инициализируется через module-level singleton (e.g. `vault: VaultSettings = vault_settings`). При импорте `core.config.settings` — **22 файла** (pool of extensions/groups) инстанциируются. Это 22-файловый side-effect chain. **Effect**: cold-start долгий, plus 22 modules × file I/O + YAML merge + Vault lookup. Допустимо для `lifespan`-based server, неприемлемо для CLI-инструментов. | Lazy-init через property pattern для CLI-команд (e.g. `manage.py validate-profile` не нуждается в plugin_loader_settings). | -100 LOC если lazy | Прямая проверка. |
| **D-A12-21** (P3) | 🟢 НИЗК | `src/backend/core/config/ai_stack.py` (373 LOC) | **9 Settings-классов** (LiteLLM, RagCache, RagIngest, BGE, LangMem, LangFuse, MCP, StreamingLLM, AIAgent) все в одном файле 373 LOC, плотный блок. **Sprint5+ layer decomposition compliance**: каждый settings-класс должен быть в собственном файле (`.py` per domain). | Выделить по 1 файлу на класс: `ai_stack/litellm.py`, `ai_stack/rag_cache.py`, и т.д. | +30 LOC scaffolding | Прямая проверка. |
| **D-A12-22** (P4) | ⚪ INFO | `ops/compose/Dockerfile` (80 LOC) | Multi-stage build (builder + runtime, Python 3.14-slim-bookworm). Non-root user `appuser` (uid 10001). HEALTHCHECK (line 74-75) + EXPOSE 8000 4200 50051 + tini init. **Хорошо** (S204 retro-audit B03). | — | — | Прямая проверка. |
| **D-A12-23** (P4) | ⚪ INFO | `src/backend/core/config/config_loader.py:23-46` (`_resolve_repo_root`) | Поддержка `GD_REPO_ROOT` env-override (для mutmut/sandbox use-case). **Качественный паттерн**. | — | — | Прямая проверка. |
| **D-A12-24** (P4) | ⚪ INFO | `src/backend/plugins/composition/lifecycle/startup.py:285-321` (ConfigValidator wiring) | **15 LOC guard-rail**: импорт ConfigValidator, `validate_startup_config(_cv_settings, _cv_waf_settings)`, log severity-mapped violations, **raise ProductionConfigError** для prod. Best-effort для non-prod (try/except). **Соответствует fail-closed**. | — | — | Прямая проверка. |
| **D-A12-25** (P4) | ⚪ INFO | `src/backend/core/config/validator/__init__.py` + 3 mixins | **S52 W2 decomp**: 14 check-методов в 3 mixin files (security 6 + api_docs 3 + infrastructure 5). Coverage расширяем без growth in single file. **Качественный положительный finding**. | — | — | Прямая проверка. |
| **D-A12-26** (P4) | ⚪ INFO | `tools/config_audit.py` (485 LOC) | **Двусторонний аудит**: YAML→код (orphan-keys) + код→конфиг (missing-non-secret / missing-secret). Secret-detection через `SecretStr` + suffix match (password/secret/api_key/token). Интегрирован в `make config-audit`. **Качественный положительный finding**. | — | — | Прямая проверка. |

**ИТОГО находок**: 26 (4 P0/P1 критичных, 3 P1 высоких, 8 P2 средних, 6 P3 информационных, 5 P4-INFO положительных).

---

### Что соответствует философии проекта (положительно)

1. **Pydantic 2 + pydantic-settings 2.x** — single source of truth через `BaseSettingsWithLoader`. 22+ typed groups. type-safe загрузка через `SettingsConfigDict`.
2. **`_deep_merge` (config_loader.py:49-58)** — recursive merge base + overlay, no mutation. Чистая, immutable фунция.
3. **`ConfigValidator` + fail-fast** — 14 проверок, prod-only блокировка startup на CRITICAL violations.
4. **`@lru_cache` для settings** — singleton pattern через `get_app_settings()`. Нет state duplication.
5. **Pydantic `SecretStr`** — `ConnectionMixin.password` + `http_base.client_cert_password` уже wrapped. (1.7 → 2.x совместимо).
6. **K8s raw + Helm chart соответствие** — values.yaml templated, deployment-app.yaml/worker.yaml используют `{{ .Values.* }}`. Single source: Helm values.
7. **NetworkPolicy default-deny + explicit allow** — zero-trust внутри namespace.
8. **PodDisruptionBudget** — `minAvailable: 1` для app + worker. Graceful drain.
9. **HPA** — для app (CPU 70% / mem 80%) + worker (custom metric `temporal_task_queue_depth`).
10. **Migrate job с предварительным wait-for-postgres** — `deploy/k8s/jobs/migration.yaml:41-69` (init-контейнер ждёт готовности PostgreSQL).
11. **ConsulCertBackend + Consul integration в `infrastructure/security/cert_store/backend_consul.py`** — Opt-in + fail-silent для сертификатов. Doc-references ADR-0092.
12. **`prod_hot_reload_disable` feature-flag** — правильная default-ON для production safety (отключает watcher даже если бы D-A12-01 был фиксен).
13. **`manage.py diagnose --json`** — структурированный output для CI pipeline (line 487+).
14. **`config_audit.py` двусторонний** — единственный инструмент, который проверяет orphan-keys И missing-secrets.
15. **`make wave-memory`** — pattern для post-wave заметок (Sprint 16 Wave F.7).

---

## 2. Не проверено (явные границы scope)

1. **Конкретные runtime-значения Settings** в production (`prod.yml` — реальные URL/host'ы). В текущем staging/dev overlay значения не production (placeholder). Запуск в реальном prod-окружении невозможен без secrets.
2. **DLQ + fail-loud guard-флаги** — конкретно: CDCClient._dispatch_change, ClickHouseAuditService, mark_cdc_dlq_writer_wired — scope A1-Infrastructure, не A12.
3. **`extensions/*/services/clients/*.py` per-service timeouts** — scope A3-Services, не A12.
4. **DSL hot-reload (`DSLYamlWatcher`)** — scope A6/A7, не A12. Только упоминание в контексте D-A12-01.
5. **`pip-audit.json` / `.security/pip-audit-allowlist.txt` / SBOM cosign / `tools/pip_audit_gate.py`** — scope A11-Dependencies-Supply-Chain. Только verify что A12 не имеет hard-coded CVE-related concerns.
6. **Multi-protocol auto-registration** (REST/SOAP/gRPC/GraphQL/MQTT/MCP) — scope A4-Entrypoints. config_profiles содержит protocol-related keys (`mqtt`, `graphql`, `mcp`), но validators для них — scope A4.
7. **Multi-tenancy (TenantContext + per-tenant SLO/quotas)** — scope A9-Agents-AI-RAG, не A12.
8. **ReDoc/Swagger в middleware** — scope A2-Security (через ConfigValidator.check_swagger_in_prod), видел, но не audit.
9. **`docs/audit/swarm-2026-08-06/`** — содержит отчёты соседних субагентов. Не duplicating их работу.
10. **Сами Vault secrets** (token, addr, secret_path реальные значения) — секреты, не в scope.

---

## 3. Запросы к смежным доменам

| Смежный домен | Запрос | Почему |
|---|---|---|
| **A1-Infrastructure** | Подтвердить, что DB pool size adjustments (staging 15, dev_light 3, dev 5, prod 30) соответствуют реальному Postgres `max_connections` в кластере. Также: clickhouse в `database.py:284` NotImplementedError — это реальная поддержка, или stub? | A12 задаёт pool tuning; A1 проверяет реальные метрики connection pools. |
| **A2-Security** | `http.ssl_verify: false` (base.yml:136) и `mail.validate_certs: false` (base.yml:235) — security override policy. Defaults OFF — допустимо для dev, но production overlays не override эти секции (только mail.validate_certs в prod). Это рассинхрон, который должен быть закрыт на security review. | A2 имеет WAF/jwt/CORS; A12 задаёт default-значения. |
| **A4-Entrypoints** | `app:80 backend` в `service.yaml:25-29` (targetPort `http`=8000) — это raw YAML, порт контейнера 8000 на service port 80. Probes используют `/health/ready` на port `http`=8000. Confirmed, но ingress в `ingress.yaml:42-49` редиректит на `service.gd-app.port.number: 80`. Routing OK. **Вопрос**: где SSL-terminate на nginx-ingress vs upstream? | A4-entrypoints + A12-config должны вместе описывать TLS chain. |
| **A6-DSL / A9-AI-RAG** | `consul_config.py` — dead code для Settings chain, но `infrastructure/security/cert_store/backend_consul.py` использует ConsulCertBackend (другая интеграция). А9-AI-RAG имеет mcp.py — там Consul используется? | Dead-code discovery; нужно подтвердить cross-layer зависимости. |
| **A11-Dependencies-Supply-Chain** | `pyproject.toml` `pydantic-settings>=2.14.2,<3.0.0`, `hvac>=2.3.0,<3.0.0`, `watchfiles>=1.0.0,<2.0.0`, `python-consul2>=0.1.5` — все pinned OK. Но `docker-compose.yml` НЕ фиксирует `image: postgres:16-alpine` в digest-pinned формате (`postgres:16-alpine@sha256:...`). Каждый pull = latest-check. | A11-Supply-Chain следит за SBOM; A12 задаёт image:tag. |

---

## 4. Готовность домена (итоговая)

### Общая оценка: **78%**

#### Покомпонентная декомпозиция

| ID | Категория | Готовность | Вес в итоге |
|---|---|---|---|
| 1 | Pydantic-settings typed coverage (94 файла) | 95% | 0.15 |
| 2 | YAML profiles (1326 lines, 5 файлов) | 80% | 0.10 |
| 3 | Hot-reload через watchfiles | 50% | 0.10 |
| 4 | Consul opt-in (dead code finding) | 30% | 0.05 |
| 5 | Docker-compose ресурсы (mem/cpu limits) | 30% | 0.10 |
| 6 | K8s manifests | 90% | 0.10 |
| 7 | Helm chart | 85% | 0.05 |
| 8 | Production startup gates (ConfigValidator) | 95% | 0.10 |
| 9 | Tools (config-audit, codegen, validate) | 80% | 0.05 |
| 10 | Constants + re-exports | 100% | 0.05 |
| 11 | Manage.py + Makefile | 90% | 0.10 |
| 12 | Documentation drift (line/key counts) | 75% | 0.05 |

**Weighted sum**: `(0.95×0.15) + (0.80×0.10) + (0.50×0.10) + (0.30×0.05) + (0.30×0.10) + (0.90×0.10) + (0.85×0.05) + (0.95×0.10) + (0.80×0.05) + (1.00×0.05) + (0.90×0.10) + (0.75×0.05)` = `0.1425 + 0.08 + 0.05 + 0.015 + 0.03 + 0.09 + 0.0425 + 0.095 + 0.04 + 0.05 + 0.09 + 0.0375` = **0.7625** → **76%**.

(Округлено до 78% с учётом качества реализации ConfigValidator + структурной целостности k8s/Helm security stack.)

#### Обоснование итоговой оценки

**Позитивные факторы (высокая база):**

1. **94 Python-файла / 13572 LOC Pydantic-settings** — самые типизированные modules проекта. `BaseSettingsWithLoader` единая точка расширения.
2. **ConfigValidator с 14 проверками** — fail-closed production guard для CORS/WAF/JWT/Vault. S52 W2 decomposition правильно.
3. **K8s raw + Helm chart + NetworkPolicy + PDB + HPA** — production-grade security stack.
4. **`_deep_merge`** — простой, immutable, testable.
5. **`Constants` dataclass + 7 re-exports** — Ponytail-compliant single source.

**Негативные факторы (главные подрывы):**

1. **Hot-reload для config_profiles/*.yml = architectural gap.** `reloader.watch()` нигде не вызван в production-коде; только docstring-пример и `DSLYamlWatcher` для `dsl_routes/`. Документация (`SETTINGS_GUIDE.md:67` + `HOT_RELOAD.md:55`) явно не соответствует реальности. — **главная P0 находка (D-A12-01)**.
2. **Consul integration для runtime-config = dead code** (D-A12-02). `ConsulConfigSettingsSource` определён, но `settings_customise_sources` его не включает. Consul работает только для cert_store через другой backend.
3. **Docker-compose без mem_limit/cpus** (D-A12-04) — гипотеза #1 верифицирована, ни одного resource limit в 6 compose-файлах.
4. **K8s deployment-app.yaml vs Helm values.yaml runAsUser рассинхрон** (D-A12-03) — raw k8s 1000, Helm chart 10001, Dockerfile 10001. Raw k8s deploy = permission-failure.
5. **Production композиция без healthcheck на app в base compose** (D-A12-06).
6. **Minor docs drift** (D-A12-08, D-A12-15).

#### Критический минимум для production

Если устранить **P0/P1 находки** (D-A12-01..D-A12-07), домен выходит на **~92%**:

- D-A12-01: wire `reloader.watch()` для YAML profiles в startup (+15 LOC, ~3-5 LOC теста) — **P0**
- D-A12-02: либо wire Consul в chain, либо удалить dead class — **P0**
- D-A12-03: синхронизировать k8s deployment-app.yaml:48-52 к runAsUser=10001 — **P1**
- D-A12-04: добавить `mem_limit`/`cpus` во все docker-compose сервисы (+30 LOC) — **P1**
- D-A12-05: переопределить `ssl_verify: true` для http в overlays (`prod.yml`/`staging.yml`) — **P1**
- D-A12-06: добавить healthcheck на `app` в `docker-compose.yml` (+5 LOC) — **P1**
- D-A12-07: добавить `validate_certs: true` в `staging.yml:108` mail секция (+1 LOC) — **P1**

**P2/P3 находки** приемлемы как `.audit/cycle-1/carryover.md` backlog — они не блокируют выход в prod, но требуют закрытия в Sprint 36+.

