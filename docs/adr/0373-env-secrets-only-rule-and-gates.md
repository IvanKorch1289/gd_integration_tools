# ADR-0373 — Правило «в `.env` только секреты» и гейты конфигурации

* Статус: Accepted (2026-10-28, cycle 172)
* Cycle: 172
* Дата: 2026-10-28
- **Затрагивает**: `.env.example`, `tools/config_secret_rules.py`,
  `tools/check_env_example.py`, `tools/config_audit.py`,
  `tools/config_audit_allowlist.txt`, `src/backend/core/config/database.py`,
  `src/backend/core/config/mongo.py`, `.github/workflows/lint.yml`,
  `make/quality.mk`
- **Связан с**: ADR-0362 (orphan- vs missing-класс аудита), ADR-0335
  (unsafe-defaults), ADR-0336 (env-example matrix), ADR-0370 (RPA-конфиг)

## Контекст

Read-only ревью настроек (4 ревьюера) зафиксировало 6 дефектов правила
«в `.env` только секреты» (решение владельца: «в `.env` — только секреты»).

1. **`.env.example` содержал 19 несекретных ключей** с непустыми значениями:
   `APP_PROFILE=dev`, `APP_ENV=dev`, `ENVIRONMENT=development`,
   `CONSUL_ENABLED=false`, `CONSUL_ADDR=`, `VAULT_MOUNT=secret`,
   `VAULT_NAMESPACE=`, `CDC_ENABLED=false`, `JUPYTER_BACKEND=hub`,
   `DSL_YAML_STORE_DIR=/tmp/dsl_yaml_store`, `SEARXNG_BASE_URL=…`,
   `SEARXNG_ENGINES=…`, `FEATURE_PROD_HOT_RELOAD_DISABLE=true`,
   `SEC_ROUTES_WITHOUT_API_KEY=`, `ALLOW_INSECURE_AUDIT_KEY=`,
   `CONTEXT7_API_KEY=ctx7sk-REPLACE-WITH-YOUR-KEY` (плейсхолдер), а также
   мёртвые ключи `GIGACHAT_API_KEY`, `TAVILY_API_KEY`,
   `LOG_PASSWORD_SECRET`, `LOG_ROOT_PASSWORD_SHA2` (реальные поля —
   `GIGACHAT_CREDENTIALS`; Graylog-ключей в Settings нет).
2. **Ни один гейт не проверял значения.** `check_env_example.py` сверял
   только имена переменных: непустой секрет и несекретный ключ проходили
   молча.
3. **Сбор env-переменных был зашумлён**: AST-скан видел
   `yaml_group: ClassVar[str]` и собирал 69 псевдо-переменных
   `*_YAML_GROUP`.
4. **missing-secret не блокировал гейт**: 17 секретов × 4 профиля = 68
   записей в baseline `tools/config_audit_allowlist.txt`; новый секрет
   проходил молча (ADR-0362 сознательно оставил этот класс неблокирующим).
5. **44 из 48 секретных полей — plain `str`**, а не `SecretStr`: значение
   попадает в `repr()` модели и в логи (ADR-0362 не покрывал типизацию).
6. **Эвристики гейтов расходились**: `config_audit` считал `username`
   секретом, `check_env_example` — нет; списки правил дублировались.

## Решение

### (а) Канонический модуль правил

`tools/config_secret_rules.py` — единственный источник правды:

* `SECRET_NAME_MARKERS` — маркеры credential-имён (`password`, `secret`,
  `token`, `api_key`, `access_key`, `credentials`, `username`, `role_id`,
  `secret_id`, `webhook_url`, …); имя совпадает с маркером или заканчивается
  на `_<маркер>`;
* `is_secret_name(name)` — эвристика по имени;
* `is_secret_field(name, annotation)` — эвристика по имени **и** типу:
  `SecretStr` — всегда секрет, а `int`/`bool`/`list`/`dict`/`Path`/`Literal`
  — никогда (даже при имени `api_key_admin_roles`).

Оба гейта используют этот модуль: `config_audit.FieldSpec.is_secret` и
`check_env_example._is_secret_field_name` — тонкие обёртки над ним.

### (б) `.env.example` — только секреты с пустыми значениями

* удалены 19 несекретных ключей и 4 мёртвых;
* значения всех оставшихся ключей пустые (`CONTEXT7_API_KEY=` вместо
  плейсхолдера);
* документированы 18 недостающих секретов (`AI_*`, `MINIMAX_*`, `MQTT_*`,
  `REDIS_SENTINEL_PASSWORD`, `HTTP_CLIENT_CERT_PASSWORD`,
  `INFLUXDB_TOKEN`, `JUPYTER_HUB_API_TOKEN`, `LANGFUSE_SECRET_KEY`,
  `LDAP_BIND_PASSWORD`, `LINEAGE_AUTH_TOKEN`, `YANDEXGPT_API_KEY`,
  `GIGACHAT_CREDENTIALS`, `SALUTE_SPEECH_CREDENTIALS`);
* шапка-правило сохранена и дополнена ссылкой на гейт.

### (в) Гейт значений и несекретности

`tools/check_env_example.py` получил проверку `check_secrets_only()`:
документированный ключ обязан быть секретом (по модели Settings либо по
каноническим правилам), значение секрета обязано быть пустым. Нарушения
блокируют гейт **во всех режимах**; новый режим `--secrets-only` — быстрый
CI-шаг без «покрытий»-шума. Дополнительно:

* `ClassVar[...]` и computed-поля исключены из сбора env-переменных
  (было 69 псевдо-переменных `*_YAML_GROUP`);
* `--env-example PATH` — проверка произвольного шаблона.

### (г) missing-secret стал блокирующим

`tools/config_audit.py` получил scope `missing` (блокирует `missing-secret`;
`missing-non-secret` — про YAML, остаётся неблокирующим). Baseline
(`tools/config_audit_allowlist.txt`) пересобран через `--update-allowlist` и
**пуст**: ни orphan-, ни missing-расхождений не осталось, поэтому гейт
ловит любое новое расхождение сразу.

### (д) Типизация секретов (`SecretStr`)

В зоне `core/config` типизированы поля, которые читаются **только** внутри
`core/config`:

* `DatabaseConnectionSettings.password` (`database.py`) — `SecretStr | None`
  (default `None`, а не `SecretStr("")`: пустой `SecretStr`-default —
  MEDIUM в гейте `tools/checks/check_unsafe_defaults.py`). DSN собирается
  через `.get_secret_value()`, computed-поля DSN помечены `repr=False`,
  чтобы пароль не утекал в `repr()` модели;
* `MongoConnectionSettings.password` (`mongo.py`) — `SecretStr` (поле
  обязательное, default отсутствует → MEDIUM-нарушения нет), строка
  подключения собирается через `.get_secret_value()`.

### (е) CI и make

* `.github/workflows/lint.yml`: шаги «Config audit gate — missing secrets»
  (`--scope missing`) и «Env example secrets-only gate» (`--secrets-only`);
* `make/quality.mk`: `check-config-audit-missing`, `check-env-example`.

## Альтернативы (отклонённые)

* **Оставить несекретные ключи в `.env.example`** — отклонено: решение
  владельца «в `.env` — только секреты»; несекреты живут в
  `config_profiles/{profile}.yml`.
* **Проверять только имена, значения не трогать** — отклонено: именно
  плейсхолдер `ctx7sk-REPLACE-WITH-YOUR-KEY` и `APP_PROFILE=dev` проходили
  молча.
* **Оставить missing-secret неблокирующим** (ADR-0362) — отменено решением
  владельца: недокументированный секрет = риск bootstrap-fallback; baseline
  очищен, гейт стал блокирующим.
* **Типизировать все 44 поля `SecretStr` сразу** — отклонено: читатели
  лежат за пределами зоны кластера (`services/ai`, `infrastructure/*`,
  `entrypoints/*`); типизация без их адаптации ломает рантайм. Часть
  зафиксирована как owner-задача (см. «Последствия»).
* **Отдельный модуль правил в `src/`** — отклонено: гейты живут в
  `tools/` и не должны тянуть `src.*` ( слой-гейт, скорость CLI).

## Последствия

* Блокирующий scope `missing` и режим `--secrets-only` — новые нарушения
  видны в CI сразу; baseline пуст, поэтому «долг» больше не маскируется.
* Правило «только секреты» теперь проверяется автоматически: регрессия
  (несекретный ключ или непустой секрет) падает в CI.
* Эвристики унифицированы: `username` и `credentials` считаются
  credential-ами обоими гейтами; `secret_path`/`api_key_admin_roles` — нет.
* Часть секретных полей осталась plain `str` — **owner-задача** (вне зоны
  кластера, требует адаптации читателей на `.get_secret_value()`):
  `core/config/security.py` (`secret_key` — `core/di/providers/auth.py:65`,
  `entrypoints/middlewares/login_step_up.py:72`,
  `entrypoints/api/v1/endpoints/auth_login.py:192`; `api_key` —
  `entrypoints/middlewares/api_key.py:110`), `core/config/ai.py` (8× `api_key`
  — `services/ai/ai_providers/*`), `core/config/services/mail.py`
  (`password` — `infrastructure/clients/transport/smtp.py:151`),
  `core/config/services/storage.py` (`access_key`/`secret_key` —
  `infrastructure/storage/s3.py:231`, `infrastructure/clients/storage/s3_pool/client.py:141`),
  а также `elasticsearch.py`, `clickhouse.py`, `services/cache.py`,
  `services/queue.py`, `services/mqtt.py`, `services/ldap.py`, `rag.py`,
  `influxdb.py`, `lineage.py`, `services/jupyter_hub.py`, `vault.py`.
* Перенос несекретных настроек из `.env.example` в YAML — **вне зоны**
  (кластер профилей): `CONSUL_*` (секции `consul` в YAML нет),
  `app.environment`, `vault.mount`/`vault.namespace`,
  `jupyter_hub.backend`, `dsl.yaml_store_dir`, `searxng.*`,
  `features.prod_hot_reload_disable`, `security.routes_without_api_key`
  (дубль `base.yml::security.routes_without_api_key`).

## Проверка

```bash
.venv/bin/python tools/check_env_example.py --secrets-only   # rc=0
.venv/bin/python tools/config_audit.py --scope missing       # rc=0
.venv/bin/python tools/config_audit.py --scope orphans       # rc=0
make check-env-example check-config-audit-missing            # rc=0
.venv/bin/python -m pytest tests/unit/tools/test_env_secrets_only_gate.py \
    tests/unit/core/config/test_secret_typing.py -q -p no:randomly
```

## Связи

* ADR-0362 — разделение orphan- и missing-класса (настоящий ADR отменяет
  решение «missing не блокирует»).
* ADR-0335 / ADR-0336 — unsafe-defaults и env-example matrix.
* ADR-0370 — консолидация RPA-конфига (изменения соседнего кластера учтены:
  `RPA_DESKTOP_API_KEY` больше не существует).
