# ADR-0371 — Харденинг prod/staging-профилей и инварианты профилей

* Статус: Accepted (2026-10-28, cycle 172)
* **Cycle**: 172 (кластер CF1 — «Профили и prod-защита»)
* **Связан с**:
  - ADR-0362 (config-audit: orphan vs missing)
  - ADR-0364 (удаление мёртвого кода — волна 13)
  - ADR-0370 (консолидация RPA-конфига, соседний кластер cycle 172)
  - ADR-0059 (Granian RSGI production tuning)
  - ADR-0063 (Presidio + ru NER PII layer в prod)
  - ADR-036 (resilience-fallback db_main → sqlite_ro)
* **Затрагивает**:
  - `config_profiles/base.yml`
  - `config_profiles/prod.yml`
  - `config_profiles/staging.yml`
  - `tests/unit/core/config/test_profile_invariants.py`

## Контекст

Read-only ревью конфигурации (4 агента-ревьюера, cycle 172) зафиксировало
дефекты, из-за которых prod-профиль по факту наследовал dev-значения, а
staging почти не отличался от dev. Решения владельца: «в `.env` — только
секреты», «hot-reload должен реально работать», «prod-профили не должны быть
как dev», «приоритет источников должен быть задокументирован и корректен».

1. **[critical] TLS-сертификаты не проверялись.** `base.yml:153` содержал
   `http.ssl_verify: false`, и ни `prod.yml`, ни `staging.yml` это значение
   не переопределяли → все исходящие HTTPS-запросы в проде принимали любой
   сертификат (риск MITM). Потребители: `infrastructure/clients/transport/
   http_httpx.py:180` (`httpx verify=`) и
   `infrastructure/clients/transport/http/session_mixin.py:51`.

2. **[high] Vault в проде — loopback plaintext.** `base.yml:23` содержал
   `vault.addr: "http://127.0.0.1:8200"` (dev-дефолт), prod его не
   переопределял → в проде секреты читались с loopback по HTTP.

3. **[high] `graphql.enable_introspection` не был объявлен.** Секции
   `graphql:` не было ни в одном профиле, дефолт модели
   (`GraphQLSettings.enable_introspection`) — `True`, при этом docstring
   модели прямо обещал «отключить в prod».

4. **[high] staging давал 2 CRITICAL от `ConfigValidator`.** В staging не было
   секции `features:` → работали модельные дефолты
   `lsp_server_strict=True` и `ai_prompt_sweep_strict=True`, а оба strict-флага
   требуют несуществующих базовых флагов `lsp_server` / `ai_prompt_sweep`
   (S46: documented no-ops) → `feature_flag.dependency_unmet` (CRITICAL) × 2.

5. **[medium] staging не был prod-уровня.** Без секции `waf:`
   (`strict=false`, пустой allowlist → outbound allow-all), без секции
   `watermark:` (`backend=memory` вместо `postgres`),
   `log.log_requests: true` (буферизация body каждого response) и
   `app.enable_swagger: true` — всё inherited из base.

6. **[medium] prod без тюнинга.** `app.workers=1`,
   `app.granian_runtime_threads=1`, `http.limit_per_host=20`,
   `security.rate_limit=1000`, `security.request_timeout=20.0` — dev-значения
   из `base.yml`.

7. **[low] localhost-хосты в prod.** `waf.allow_hosts` содержал
   `localhost`/`127.0.0.1`; `base.yml` задавал `open_webui.base_url:
   http://localhost:3000`, а `ai_providers.fallback_chain` включал
   `open_webui` → откат с perplexity в проде молча уходил на localhost;
   `snapshot.enabled=true` (локальный SQLite-файл) в prod.

8. **Валидация проверяла только overlay.** `manage.py validate-profile`
   смотрит на `config_profiles/<env>.yml` и для prod делает лишь
   поверхностную проверку флагов (`app.debug`, `app.enable_swagger`,
   `app.enable_redoc`, `secure.cors_origins`). Merged-конфиг
   (`base.yml` + overlay) через `ConfigValidator` не проверялся нигде —
   именно поэтому дефекты 1, 3, 4, 5 остались незамеченными.

## Решение

### 1. TLS-проверка включена по умолчанию

`base.yml`: `http.ssl_verify: true` (вместо `false`) + комментарий со
списком потребителей. `prod.yml` и `staging.yml` объявляют
`http.ssl_verify: true` явно (не наследуют).

### 2. Vault в prod — не loopback-plaintext

`prod.yml`: новая секция `vault: addr: "https://vault:8200"`. Фактический
адрес Vault в деплое задаётся env `VAULT_ADDR` (приоритет выше YAML), YAML —
безопасный fallback профиля. `staging.yml` наследует base-дефолт
(`http://127.0.0.1:8200`) — это зафиксированный долг (см. «Последствия»),
реальный адрес задаётся env.

### 3. GraphQL-интроспекция объявлена выключенной

`base.yml`: новая секция `graphql: enable_introspection: false`;
`prod.yml` и `staging.yml` объявляют значение явно. Runtime-запрет
интроспекции вне development обеспечивает
`entrypoints/graphql/graphql_guards.py` (`NoIntrospectionRule`) — ключ
фиксирует декларативное намерение профиля.

### 4. staging: секция `features:`

`staging.yml` объявляет `features:` с `lsp_server_strict: false`,
`ai_prompt_sweep_strict: false` (как dev/dev_light/prod) и
`presidio_pii_enabled: true` (ADR-0063 — PII-слой обязателен в prod,
staging повторяет prod-конфигурацию).

### 5. staging: prod-уровень по WAF / watermark / логированию / docs

`staging.yml` дополнен:

* `waf: strict: true` + непустой `allow_hosts` (тот же whitelist, что в prod);
* `watermark: backend: "postgres"` (durable, как в prod);
* `log.log_requests: false` (в base было `true`);
* `app.enable_swagger: false` / `app.enable_redoc: false`;
* `app.workers: 2`, `app.granian_runtime_threads: 2` (стенд воспроизводит
  многопроцессный режим, но дешевле prod'а).

### 6. prod-тюнинг

`prod.yml`:

* `app.workers: 4` — совпадает с дефолтом
  `ops/compose/docker-compose.prod.yml` (`APP_WORKERS:-4`);
* `app.granian_runtime_threads: 4`;
* `http.limit_per_host: 50` (в base было 20);
* `security.rate_limit: 3000` (в base было 1000) — лимит запросов в минуту
  на route+dependency, Redis-лимитер
  (`entrypoints/dependencies/rate_limit.py`);
* `security.request_timeout: 30.0` (в base было 20.0) — глобальный
  fallback `TimeoutMiddleware`
  (`entrypoints/middlewares/timeout.py`).

`security.algorithm` намеренно оставлен `HS256`: переход на `RS256` требует
RSA-keypair + JWKS/IdP, без этой инфраструктуры он ломает выпуск и проверку
JWT (`get_jwt_backend_provider` передаёт `secret=None` для не-HS алгоритмов).
Секрет остаётся в Vault (решение владельца «в `.env` — только секреты»).

### 7. prod: localhost-хосты

* `ai_providers.fallback_chain` в prod больше не содержит `open_webui`
  (его `base_url` — `http://localhost:3000`; реальный host без
  инфраструктуры вывести нельзя → owner-задача);
* `snapshot.enabled: false` в prod — локальный SQLite-файл
  `var/db/snapshot.sqlite` является per-pod (shared state между подами).
  Корректный prod-fallback — read-replica PostgreSQL
  (`database.replica_dsn`, сейчас `null` → owner-задача);
* `waf.allow_hosts` в prod/staging оставлен с loopback (реальные хосты
  локальных sidecar'ов — clamd/otel — без инфраструктуры не выводятся) →
  owner-задача.

### 8. Инвариантный тест `tests/unit/core/config/test_profile_invariants.py`

Новый гейт (30 тестов) проверяет merged-конфиг `base.yml` + overlay:

* `http.ssl_verify is True` и `graphql.enable_introspection is False` — для
  prod и staging, плюс явное объявление в overlay-файле и в `base.yml`;
* `vault.addr` в prod — `https` и не loopback; staging — зафиксированное
  отклонение (тест явно фиксирует, что значение взято из base);
* секция `features:` в staging + `waf.strict` + `watermark.backend=postgres` +
  `log.log_requests=false` + Swagger/ReDoc выключены;
* prod-тюнинг (workers/threads/лимиты), `snapshot.enabled=false` в prod,
  `open_webui` вне fallback-цепочки;
* **loopback-хосты**: скан всех строковых значений merged-конфига на
  `localhost` / `127.0.0.1` / `::1`; допускаются только пути из явного
  allowlist'а (`_LOOPBACK_ALLOWLIST` в тесте, продублирован в ADR);
* **`ConfigValidator` на merged base+profile → 0 CRITICAL** — в отличие от
  `manage.py validate-profile`, который проверяет только overlay.

Тест работает по YAML-файлам (merge — как в
`core.config.config_loader._deep_merge`) и не зависит от env/Vault: результат
определяется только содержимым `config_profiles/*.yml`.

## Альтернативы (отклонённые)

1. **Оставить `ssl_verify: false` в base, переопределять только в prod/staging.**
   Отклонено: base — единственный источник дефолтов, и любой будущий профиль
   (или профиль, забытый в реестре) унаследовал бы небезопасное значение.
   Безопасным должен быть дефолт.
2. **Переключить `security.algorithm` на `RS256` в prod.** Отклонено: без
   RSA-keypair и JWKS/IdP `get_jwt_backend_provider` передаёт `secret=None`,
   и JWT-проверка перестаёт работать — это ломающий change без инфраструктуры.
   Зафиксировано как owner-задача.
3. **Убрать loopback из `waf.allow_hosts` в prod.** Отклонено: реальные
   хосты локальных sidecar'ов (clamd/otel) без инфраструктуры не выводятся,
   а удаление loopback из allowlist может отрезать легитимные исходящие
   вызовы. Зафиксировано как owner-задача + allowlist в тесте.
4. **Выключить `snapshot.enabled` и в staging.** Отклонено: staging — стенд
   для репетиции prod-контура; выключение snapshot там оставило бы fallback
   `db_main → sqlite_ro` без источника данных. Требование владельца
   относилось к prod (multi-pod).
5. **Выдумать реальные хосты для `open_webui` / `vault-staging` / sidecar'ов.**
   Отклонено: без реальной инфраструктуры это фиктивная конфигурация,
   которая выглядит hardened, но не является таковой. Вместо этого —
   fail-closed поведение (open_webui исключён из fallback-цепочки) и явный
   allowlist в тесте + owner-задачи в ADR.
6. **Расширить `manage.py validate-profile` до merged-проверки.** Отклонено:
   `manage.py` — не мой файл (зона оркестратора/соседнего кластера);
   эквивалентная гарантия дана pytest-гейтом, который исполняется в том же
   CI-прогоне.
7. **Добавить `graphql.enable_introspection` в `entrypoints/graphql/
   graphql_guards.py` (потребление ключа).** Отклонено: файл вне зоны
   кластера CF1; зафиксировано как owner-задача (см. «Последствия»).

## Последствия

* **Позитивные:** prod/staging больше не наследуют небезопасные значения из
  `base.yml` (TLS, интроспекция, Vault, WAF, watermark, логирование body,
  Swagger); staging даёт 0 CRITICAL от `ConfigValidator` на merged-конфиге;
  регрессии по инвариантам закрыты pytest-гейтом; `open_webui` в prod больше
  не является молчаливым localhost-откатом.
* **Негативные / breaking:** `http.ssl_verify: true` в base затрагивает
  `dev`/`dev_light` — если там нужен self-signed TLS, значение должно быть
  переопределено в их overlay-файлах (зона соседнего кластера); выключение
  `snapshot.enabled` в prod делает ветку fallback `db_main → sqlite_ro`
  инертной (в prod fallback должен опираться на `database.replica_dsn`,
  сейчас `null`); исключение `open_webui` из fallback-цепочки означает, что
  при отказе всех внешних AI-провайдеров запрос завершится ошибкой, а не
  уйдёт на localhost.
* **Долги, зафиксированные за владельцем:**
  1. `waf.allow_hosts` в prod/staging — заменить loopback на явные
     service-DNS имена sidecar'ов (clamd/otel);
  2. `open_webui.base_url` — реальный host внутреннего LLM-сервера (или
     явное решение «OpenWebUI в prod не используется»);
  3. `vault.addr` в staging — https-адрес вместо base-дефолта;
  4. `security.algorithm` — переход на `RS256` вместе с RSA-keypair и
     JWKS/IdP;
  5. `database.replica_dsn` в prod — read-replica PostgreSQL (замена
     отключённого SQLite-snapshot как источника fallback'а);
  6. `graphql.enable_introspection` — wiring в
     `entrypoints/graphql/graphql_guards.py` (сейчас ключ декларативный, а
     runtime-политика опирается на `app.environment`);
  7. `dev.yml` / `dev_light.yml` — решение по `http.ssl_verify` (своя зона).
* **Вне зоны кластера CF1:** `manage.py` (merged-валидация в CLI),
  `entrypoints/graphql/graphql_guards.py` (wiring `enable_introspection`),
  `dev.yml` / `dev_light.yml` (override `ssl_verify` при self-signed TLS).

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/config/test_profile_invariants.py \
    -q -p no:randomly                                            # 30 passed
.venv/bin/python -m ruff check tests/unit/core/config/test_profile_invariants.py
.venv/bin/python tools/config_audit.py --scope orphans          # 0
.venv/bin/python tools/check_layers.py --strict                 # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
.venv/bin/python tools/check_declared_dependencies.py           # 0 новых
.venv/bin/python manage.py validate-profile prod
.venv/bin/python manage.py validate-profile staging
```

## Связи с другими ADR

* **ADR-0362** — `orphan` vs `missing` в config-audit: все новые ключи
  профилей соответствуют живым полям моделей (`config_audit --scope orphans`
  = 0).
* **ADR-0364** — общий принцип «мёртвая конфигурация = ложь в конфиге»:
  `graphql.enable_introspection` объявлен явно, как и требует его docstring.
* **ADR-0059** — Granian RSGI production tuning: `app.workers` /
  `app.granian_runtime_threads` в prod приведены к prod-уровню.
* **ADR-0063** — Presidio PII-слой: `features.presidio_pii_enabled: true`
  в prod и staging.
* **ADR-036** — resilience-fallback db_main → sqlite_ro: выключение
  `snapshot.enabled` в prod и переход на read-replica.
* **ADR-0370** — соседний кластер cycle 172: консолидация RPA-конфига
  (тема секций `features:` и конфиг-аудита общая).
