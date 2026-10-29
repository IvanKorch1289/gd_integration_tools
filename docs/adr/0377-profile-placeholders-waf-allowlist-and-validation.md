# ADR-0377 — Профили без env-плейсхолдеров, WAF-allowlist интеграций и валидация секции constants

* Статус: Accepted (2026-10-29, wave 15, кластер W2 — «Профили: плейсхолдеры, WAF, валидация»)
* Cycle: 175
* Дата: 2026-10-29
- **Затрагивает**: `config_profiles/{base,staging,prod}.yml`,
  `src/backend/core/config/validator/profile_merge.py`, `manage.py`,
  `tests/unit/core/config/{test_profile_invariants,test_validate_profile_merged}.py`,
  `docs/config/SETTINGS_GUIDE.md`
- **Связан с**: ADR-0371 (инварианты prod/staging-профилей),
  ADR-0372 (приоритет источников и hot-reload), ADR-0375 (merged-валидация
  профиля и yaml-группы), ADR-0059 (Granian RSGI production tuning),
  ADR-0362 (config-audit: orphan vs missing)

## Контекст

Независимый свип функционала настроек (волна 15) нашёл в профилях
кластер остаточных дефектов:

1. **[critical] Env-плейсхолдеры `${VAR:-default}` в YAML-профилях.**
   `prod.yml` и `staging.yml` содержали `policy.opa_url`,
   `policy.casbin_model_path`, `policy.casbin_policy_path` в виде
   `${OPA_URL:-http://opa:8181}` и т.п. YAML-загрузчик
   (`core/config/config_loader.py`) подстановку **не выполняет**, а Helm
   эти файлы не шаблонизирует — плейсхолдер попадал в рантайм как есть:
   OPA-клиент получал невалидный URL (все решения — `deny`,
   `opa_unavailable`), Casbin — `FileNotFoundError` с плейсхолдером в пути.
2. **[high] WAF-allowlist рвал внешние интеграции.** `waf.strict=true` +
   allowlist `["esbgreendata", "localhost", "127.0.0.1"]` → любой исходящий
   запрос к хосту вне списка блокировался (`core/net/waf.py` →
   `WafBypassError`). В prod запросы к СКБ-Техно (`api.skb-techno.ru`) и
   DaData (`suggestions.dadata.ru`) идут **напрямую** (минуя WAF-шлюз
   `http.waf_url`) → интеграции были сломаны полностью.
3. **[medium] `validate-profile` не валидировал секцию `constants`.**
   Секция собиралась через `model_construct` (без валидации), поэтому
   `initial_delay: -5` проходил CLI насквозь — и ронял старт процесса
   (`ValidationError` при создании `ConstantsSettings`).
4. **[medium] staging наследовал dev-значения** из `base.yml`:
   `vault.addr=http://127.0.0.1:8200` (loopback-plaintext),
   `http.limit_per_host=20`, `security.rate_limit=1000`,
   `security.request_timeout=20.0`, `snapshot.enabled=true`.
5. **[low] Устаревшие комментарии** в `base.yml` (self-signed TLS override,
   которого нет) и `prod.yml` (`workers=1` «в base.yml» — на самом деле
   это дефолт модели, ключа в `base.yml` нет).
6. **[low] Granian-настройки вне зоны гейта покрытия.** Класс
   `GranianTuning` (`yaml_group="granian"`) живёт в
   `src/backend/core/scaling/`, а не в `core/config/` → его 10 полей
   настраивались только через env (`GRANIAN_*`).

## Решение

### (а) В YAML — только литералы, override — через env

`prod.yml` / `staging.yml` получили литералы: `http://opa:8181` /
`http://opa-staging:8181`, `/etc/casbin/model.conf`,
`/etc/casbin/policies.csv`. Комментарии в профилях и в
`docs/config/SETTINGS_GUIDE.md` фиксируют env-override (приоритет env выше
YAML, ADR-0372): `POLICY_OPA_URL`, `POLICY_CASBIN_MODEL_PATH`,
`POLICY_CASBIN_POLICY_PATH` (префикс `POLICY_` — из
`core/config/services/policy.py::PolicySettings`).

Гейт: `test_profile_invariants.py::TestNoEnvPlaceholders` — в строковых
значениях **всех** YAML-профилей (`base`/`dev`/`dev_light`/`staging`/`prod`)
нет `${...}`; плюс проверка, что `policy.opa_url` — URL, а
`casbin_*_path` — абсолютные пути.

### (б) WAF-allowlist покрывает внешние интеграции

В `prod.yml` и `staging.yml` в allowlist добавлены хосты интеграций из
`src/backend/services/integrations/**`: `api.skb-techno.ru` (`skb.prod_url`)
и `suggestions.dadata.ru` (`dadata.base_url`). Webhook-relay не добавлен:
его цели задаются динамически, per-webhook.

Гейт: `TestWafAllowlistCoversIntegrations` — (1) allowlist покрывает хосты
интеграций из merged-конфига, (2) известные внешние хосты присутствуют,
(3) проба `WafPolicy.evaluate(url)` даёт `allowed` (тот же сценарий, что
в свипе).

### (в) Валидация секции `constants`

`profile_merge.py` получил `_validate_constants_section()`: значения
секции проверяются моделью-зондом, собранной из полей
`ConstantsSettings` (те же ограничения `ge=0` / `gt=0`). Нарушение →
`ConfigViolation(code="constants.invalid", severity=CRITICAL)` → CLI
завершается с кодом 1.

Модель-зонд — отдельная (а не сам `ConstantsSettings`), потому что у
`ConstantsSettings` есть `model_post_init`, применяющий значения к
глобальному синглтону `consts`. Валидация профиля не имеет права менять
рантайм-состояние — это зафиксировано тестом
`test_validation_does_not_mutate_global_constants`.

### (г) Staging выровнен до prod-уровня

`staging.yml`: `vault.addr=https://vault-staging:8200` (вместо
loopback-plaintext из `base.yml`), `http.limit_per_host=50`,
`security.rate_limit=3000`, `security.request_timeout=30.0`,
`snapshot.enabled=false` — каждое значение с комментарием.

### (д) Комментарии приведены в соответствие с кодом

`base.yml`: self-signed TLS override есть только через env
`HTTP_SSL_VERIFY` (dev/dev_light значение наследуют). `prod.yml`:
`workers=1` / `granian_runtime_threads=1` — это дефолты модели
`AppBaseSettings`, в `base.yml` таких ключей нет.

### (е) Секция `granian` в `base.yml`

Добавлена секция `granian:` с 10 полями, равными дефолтам `GranianTuning`
(`workers: auto`, `max_workers: 16`, `blocking_threads: auto`,
`loop: uvloop`, `interface: rsgi`, `http: auto`, `log_level: info`,
`access_log: true`, `backlog: 2048`, `granian_kill_timeout: 30`).
Поведение при загрузке не меняется — параметр становится конфигурируемым
через YAML-профиль.

## Альтернативы

* **Поддержать `${VAR:-default}` в YAML-загрузчике.** Отклонено: это
  меняет формат конфигурации для всех 70 yaml-групп, требует собственного
  парсера подстановок (и precedence env/YAML) и вводит в конфиг третий
  синтаксис значений. Env-override уже покрывает потребность
  (ADR-0372) и не трогает рантайм-семантику YAML.
* **Разрешить интеграции через WAF-шлюз (`http.waf_url`) везде.** Отклонено:
  маршрутизация зависит от окружения и `use_waf` конкретного клиента —
  универсальный rewrite URL изменил бы контракт клиентов.
* **Отключить `waf.strict` в prod.** Отклонено: permissive-WAF в prod
  запрещён валидатором (`waf.strict_required_in_prod`).
* **Валидировать `constants` через сам `ConstantsSettings`.** Отклонено:
  `model_post_init` применил бы YAML-значения к глобальному `consts` —
  CLI-отчёт не должен менять состояние процесса.
* **Перенести `GranianTuning` в `core/config/`.** Отклонено: класс вне
  зоны кластера (перенос затрагивает импорты `core/scaling` → `core/config`
  и нарушит границы слоёв).

## Последствия

* Поведение рантайма в prod/staging меняется только там, где конфиг был
  сломан: policy-движки получают валидные литералы (env-override
  сохраняется), интеграции СКБ-Техно/DaData больше не блокируются WAF,
  staging изолирован от dev-значений Vault/лимитов/snapshot.
* `manage.py validate-profile` стал строже: секция `constants` с
  нарушением ограничения → CRITICAL → exit 1 (раньше — «зелёный» отчёт и
  падение на старте).
* Валидация профиля не имеет побочных эффектов (глобальный `consts` не
  мутируется).
* Гейт `tools/config_audit.py --scope orphans` по умолчанию видит
  `granian` как `orphan-group`: инструмент сканирует только
  `src/backend/core/config`, а `GranianTuning` живёт в
  `src/backend/core/scaling/`. Это ограничение области сканирования
  гейта (не дефект ключей: все 10 ключей — поля модели, значения равны
  дефолтам). Расширение гейта — вне этого кластера
  (`tools/`, `test_yaml_group_coverage.py` не трогались); при
  `--config-dir src/backend/core` аудит даёт 0 расхождений.
* Webhook-relay (`services/integrations/webhook_relay.py`) ходит через
  `OutboundHttpClient` с динамическими целями — статический allowlist его
  не покрывает (вне зоны: список целей per-webhook).

## Проверка

* `python -m pytest tests/unit/core/config/test_profile_invariants.py
  tests/unit/core/config/test_validate_profile_merged.py -q -p no:randomly`
  → 68 passed.
* `python manage.py validate-profile prod` → 0 CRITICAL, 1 WARNING
  (`waf.clamav_fail_open_in_prod` — значение из дефолта модели);
  `validate-profile staging` → 0 CRITICAL, 0 WARNING.
* `python tools/config_audit.py --scope orphans` → 4 × `orphan-group:
  granian` (область сканирования гейта, см. «Последствия»);
  с `--config-dir src/backend/core` → 0 расхождений.
* `python tools/check_layers.py --strict` → без новых нарушений (41
  pre-existing).

## Связи

* ADR-0371 — харденинг prod/staging-профилей и инварианты профилей.
* ADR-0372 — приоритет источников конфигурации (env выше YAML).
* ADR-0375 — merged-валидация профиля, yaml-группы, константы из YAML.
* ADR-0059 — Granian RSGI production tuning.
* ADR-0362 — двусторонний аудит конфигурации (orphan vs missing).
* `docs/config/SETTINGS_GUIDE.md` — разделы «Профили без env-плейсхолдеров»,
  «WAF allowlist и внешние интеграции», «Секция constants».
