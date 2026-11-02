# ADR-0407 — Прод-значения: контракты HS256, WAF allow_hosts, AI-fallback и replica_dsn (волна 22, кластер B3)

* Статус: Accepted (2026-11-02, волна 22, кластер B3 — прод-значения: контракты)
* Cycle: 181 (волна 22)
* Связан с:
  - ADR-0371 (прод-значения, оставленные осознанно: HS256, WAF allowlist, `open_webui`, `replica_dsn`),
  - ADR-0377 (WAF-allowlist внешних интеграций, запрет env-плейсхолдеров в YAML),
  - ADR-0381 (`replica_dsn` как `SecretStr`, маскирование DSN),
  - ADR-0403 (прод-валидатор: JWT-алгоритм и AI-fallback — образец проверок в `profile_merge.py`),
  - ADR-0378 (маскирование секретов в дампах)
* Затрагивает:
  - `src/backend/core/config/validator/profile_merge.py`,
  - `config_profiles/prod.yml`, `config_profiles/staging.yml`,
  - `docs/config/SETTINGS_GUIDE.md`, `docs/roadmap/OWNER_TASKS.md`,
  - `tests/unit/core/config/test_prod_values_contracts.py`

---

## Контекст

`docs/roadmap/OWNER_TASKS.md` § 3 перечисляет четыре «прод-значения,
оставленные осознанно»: HS256 в проде, loopback-хосты в `waf.allow_hosts`,
`open_webui` вне AI-fallback-цепочки и `database.replica_dsn: null`. Все четыре
требовали внешней инфраструктуры и потому висели как «задокументированные
ограничения» — без исполняемого контракта: правило «HS256 допустим, если
есть секрет» и «allow_hosts покрывает интеграции» нигде не проверялось
машинно, а `replica_dsn: null` формально выглядел как незаполненное
прод-значение.

Фактическое состояние на момент wave-22 (проверено кодом и запуском
`manage.py validate-profile prod/staging`):

1. **HS256.** Проверка уже существовала (ADR-0403,
   `_check_jwt_algorithm_secret_policy`): симметричный алгоритм в prod без
   гарантированного источника секрета → CRITICAL. Но контракт не был
   зафиксирован для владельца: не было ответа «что считается источником
   секрета» и «как выглядит переход на RS256».
2. **WAF `allow_hosts`.** В `prod.yml`/`staging.yml` уже были хосты
   интеграций (`api.skb-techno.ru`, `suggestions.dadata.ru`) и loopback
   (`localhost`, `127.0.0.1`) — но «loopback оставлен осознанно» оставалось
   комментарием. Строгой проверки не было: удаление хоста интеграции из
   allowlist'а проходило с exit 0, и интеграция в проде падала с
   `WafBypassError`.
3. **AI-fallback.** `open_webui` действительно исключён из prod-цепочки
   (`base.yml` → `http://localhost:3000`), и ADR-0403 добавил проверку на
   loopback-провайдера — но проверка жила только в коде, без контракта в
   документации и без теста на репозиторном prod-профиле.
4. **`database.replica_dsn: null`.** Валидатор молчал: `null` не считался
   ни нарушением, ни осознанным решением. Непустое значение не проверялось
   вовсе (реплика на loopback означала бы «свой экземпляр на каждый pod»).

---

## Решение

Контракты перенесены из комментариев в **исполняемые проверки**
`src/backend/core/config/validator/profile_merge.py` (merged-конфиг
`base.yml` + overlay, как в рантайме) и закреплены тестами
`tests/unit/core/config/test_prod_values_contracts.py`.

### 1. HS256 в prod — контракт «секрет обязателен»

* **Контракт.** В prod симметричный алгоритм (`HS*`) допустим **только** при
  гарантированном источнике JWT-секрета:
  * `security.secret_key` в YAML профиля;
  * env `SEC_SECRET_KEY` (env-префикс `SEC_` модели `SecureSettings`);
  * Vault: `vault.enabled` + `addr` + `secret_path` — прод-источник по
    умолчанию.
* **Проверка.** Нет ни одного источника → CRITICAL
  `security.jwt_symmetric_algorithm_without_secret` (ADR-0403; контракт
  уточнён, алгоритм не менялся).
* **Алгоритм не меняется.** Переход на RS256 — отдельная owner-задача
  (`OWNER_TASKS.md` § 3.1): нужна RSA-keypair + JWKS/IdP. Условия приёмки
  перечислены в реестре owner-задач.
* **Fail-closed в рантайме.** Если Vault недоступен или не задан
  `VAULT_TOKEN`, секрет не приедет, и `SecureSettings.secret_key` (обязательное
  поле) роняет старт процесса `ValidationError` — приложение не стартует
  без ключа подписи.

### 2. WAF `allow_hosts` — покрытие интеграций + обоснованный loopback

* **Контракт (a).** В prod/staging при `waf.strict=true` allowlist обязан
  содержать хост **каждой** внешней интеграции, чей endpoint задан в
  профиле (`skb.prod_url` — `services/integrations/skb.py`,
  `dadata.base_url` — `services/integrations/dadata.py`). Нет хоста → CRITICAL
  `waf.allow_hosts_missing_integration_hosts` (иначе исходящий запрос
  блокируется `WafBypassError`, и интеграция в проде не работает).
* **Контракт (b).** Loopback-хост (`localhost` / `127.0.0.1` / `::1` / …) в
  allowlist допустим **только** если в профиле есть включённая локальная
  зависимость — sidecar `clamd` (`waf.clamav_enabled=true` +
  `waf.clamav_host` на loopback) или otel-collector
  (`app.opentelemetry_endpoint` на loopback). Иначе → CRITICAL
  `waf.allow_hosts_loopback_without_local_dependency`: запись либо мёртвая,
  либо (хуже) внешняя интеграция молча указывает на localhost.
* **Значения профилей не менялись:** `esbgreendata`, `localhost`,
  `127.0.0.1`, `api.skb-techno.ru`, `suggestions.dadata.ru` — loopback
  оправдан локальным sidecar'ом clamd.

### 3. AI-fallback-цепочка — только доступные в проде провайдеры

* **Контракт.** В prod `ai_providers.fallback_chain` не содержит провайдера
  с loopback-`base_url` (`open_webui` → `http://localhost:3000`): откат на
  несуществующий в проде сервис выглядит как «LLM отвечает».
  Нарушение → CRITICAL `ai_providers.fallback_chain_localhost` (ADR-0403).
* **Факт подтверждён:** `open_webui` в prod-цепочке отсутствует; цепочка
  состоит из реально доступных провайдеров (`perplexity`, `huggingface`,
  `openrouter`, `nim`, `openai`, `minimax`).

### 4. `database.replica_dsn` — `null` допустим, непустое — реальный хост

* **Контракт.** `replica_dsn: null` = «реплика не развёрнута»: весь трафик
  идёт на primary. Это **не** CRITICAL (валидатор так и трактует).
* **Непустое значение** — только реальный хост реплики: DSN без хоста или с
  loopback-хостом → CRITICAL `database.replica_dsn_invalid` (реплика на
  loopback = «свой экземпляр на каждый pod»).
* **Маскирование.** `replica_dsn` — `SecretStr` с `@field_serializer`
  (ADR-0381): пароль в userinfo заменяется на `***` в `model_dump()` /
  `model_dump_json()`; рабочее значение доступно через `get_secret_value()`
  (ADR-0378).

---

## Альтернативы

* **Переключить prod на RS256 «по умолчанию».** Отклонено: без RSA-keypair и
  JWKS/IdP выпуск и проверка JWT перестают работать (ADR-0371). Зафиксировано
  как owner-задача с критериями приёмки.
* **Убрать loopback из `waf.allow_hosts` prod/staging.** Отклонено: clamd
  обслуживается через loopback (`waf.clamav_host=127.0.0.1`), и удаление
  записи сломает AV-сканирование. Вместо «жёсткого» запрета введён
  обоснованный инвариант: loopback допустим ровно при наличии локальной
  зависимости — иначе запись мертва или маскирует неверную интеграцию.
* **Считать `replica_dsn: null` CRITICAL.** Отклонено: это штатное
  состояние «реплики нет», а не дефект конфигурации; запрет мешал бы
  деплою без реплики.
* **Проверять `replica_dsn` только на «не пустое».** Отклонено: DSN без
  хоста (`not-a-dsn`) или на loopback — тихая поломка read-роутинга; нужен
  разбор URL и проверка хоста.
* **Оставить проверки в тестах профилей, без валидатора.** Отклонено:
  `manage.py validate-profile` — единственная точка, которую смотрят перед
  деплоем; контракт должен быть там (ADR-0375).

---

## Последствия

* `manage.py validate-profile prod` → 0 CRITICAL, 1 WARNING
  (`waf.clamav_fail_open_in_prod`, pre-existing); `... staging` → 0 CRITICAL,
  0 WARNING. Exit code 0 в обоих случаях.
* Новые CRITICAL-коды не меняют текущие профили: хосты интеграций в
  allowlist есть, loopback оправдан sidecar'ом clamd, `replica_dsn: null`.
* `config_profiles/staging.yml` теперь явно объявляет `replica_dsn: null`
  (раньше значение наследовалось из `base.yml`, где ключа нет).
* Владелец получает исполняемый контракт вместо комментария: четыре
  позиции `OWNER_TASKS.md` § 3 переведены в «закрыто кодом + остаток у
  владельца».

---

## Проверка

* `tests/unit/core/config/test_prod_values_contracts.py` — контракты всех
  четырёх позиций: JWT (prod без секрета → CRITICAL; с секретом → OK),
  WAF (покрытие интеграций + обоснованный loopback), AI-fallback
  (prod-цепочка без недоступных провайдеров), `replica_dsn` (`null` — не
  CRITICAL; loopback/без хоста — CRITICAL; маскирование в дампах).
  Проверки идут по merged-конфигу и по результату валидатора, а не по
  наличию строк в YAML (падало → зелёное).
* `python manage.py validate-profile prod` → exit 0, 0 CRITICAL;
  `python manage.py validate-profile staging` → exit 0, 0 CRITICAL.
* Гейты: `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` (baseline 41); `tools/checks/mypy_budget.py`
  (бюджет 30); `ruff`; `tools/generate_adr_index.py --check`.

---

## Открытое (owner-задачи)

1. **Переход на RS256** (prod). Владелец: безопасность/платформа. Критерии
   приёмки: выпущены RSA-keypair и JWKS-endpoint (или подключён IdP);
   `security.algorithm=RS256` + `security.jwks_url` в профиле; `SEC_SECRET_KEY`
   для подписи больше не требуется; тест контракта обновлён вместе с
   ADR-0407.
2. **Service-DNS вместо loopback для sidecar'ов** (prod/staging).
   Владелец: эксплуатация. Критерии: `waf.clamav_host` и
   `app.opentelemetry_endpoint` указывают на DNS-имена sidecar'ов; loopback
   удаляется из `waf.allow_hosts`; `validate-profile` — 0 CRITICAL.
3. **Прод-endpoint OpenWebUI.** Владелец: эксплуатация/AI-платформа.
   Критерии: задан реальный `base_url` (не loopback), провайдер возвращён в
   `ai_providers.fallback_chain` prod-профиля, `validate-profile` — 0 CRITICAL.
4. **DSN read-реплики.** Владелец: DBA/эксплуатация. Критерии: выдан
   async-DSN реплики, `database.replica_dsn` (или `DB_REPLICA_DSN`) задан
   реальным host'ом, `snapshot` в prod включён по runbook'у.

---

## Связи

* ADR-0371 — прод-значения, оставленные осознанно (источник owner-задач).
* ADR-0377 — WAF-allowlist внешних интеграций и запрет env-плейсхолдеров.
* ADR-0378 — маскирование секретов в дампах.
* ADR-0381 — `replica_dsn` как секрет (`SecretStr`).
* ADR-0403 — прод-валидатор: JWT-алгоритм и AI-fallback.
* `docs/config/SETTINGS_GUIDE.md` — «Прод-значения: контракты (ADR-0407)».
* `docs/roadmap/OWNER_TASKS.md` § 3 — реестр owner-задач по прод-значениям.
