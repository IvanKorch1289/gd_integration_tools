# ADR-0385 — Открытые задачи A1–A11: env-гейт, Vault-refresher, WAF, внешние БД и валидация профиля

* Статус: Accepted (2026-10-29, wave 16, кластер X6 — «ОТКРЫТЫЕ ЗАДАЧИ A1–A6 + НАСТРОЙКИ БД»)
* Дата: 2026-10-29
- **Затрагивает**:
  - `tools/check_env_example.py`
  - `tools/uv_audit_gate.py` (новый), `.security/uv-audit-allowlist.txt` (новый)
  - `.github/workflows/security.yml`
  - `src/backend/plugins/composition/setup_infra/lifecycle.py`
  - `src/backend/core/net/outbound_http.py`
  - `src/backend/core/config/external_databases/{connection,item,registry}.py`
  - `src/backend/core/config/validator/profile_merge.py`
  - `docs/config/SETTINGS_GUIDE.md`
- **Связан с**:
  - ADR-0373 (правило «в `.env` только секреты» + гейты)
  - ADR-0375 (merged-валидация профиля, yaml-группы)
  - ADR-0377 (placeholder'ы, WAF-allowlist, валидация секций)
  - ADR-0378 (маскирование секретов в дампах)
  - ADR-0379 (честный hot-reload и валидация профиля)
  - ADR-0381 (fail-fast для несовместимых пар СУБД/драйвер, DB2)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/core/config/database.py` — A4 (fail-fast DB2), сделано
    параллельной правкой кластера X2;
  - `src/backend/core/config/hot_reload.py` — предупреждение «нужен рестарт»
    для пулов БД в сам отчёт reload не добавлено (вне зоны), задокументировано
    в ADR и `docs/config/SETTINGS_GUIDE.md`.

## Контекст

Свип настроек БД (волна 16) нашёл кластер из одиннадцати открытых задач
A1–A11: мёртвые гейты конфигурации, неработающий фоновый рефрешер
секретов, обход WAF-политики, пароль внешней БД в admin-ответе, 500 на
`settings.model_dump()`, «дырявую» валидацию профиля и неполный
CI-аудит зависимостей.

1. **[medium] A1.** `tools/check_env_example.py` смотрел только `node.body`
   самого класса Settings. Поля, унаследованные от mixin'ов/баз
   (`ConnectionMixin`, `BaseBotChannelSettings`), терялись → девять живых
   секретов помечались как «не используются в Settings» и не видились гейту
   ADR-0373 (`AI_USERNAME/AI_PASSWORD/AI_API_KEY`,
   `MINIMAX_USERNAME/MINIMAX_PASSWORD`,
   `EXPRESS_SECRET_KEY/EXPRESS_SIGNATURE_SECRET`,
   `TELEGRAM_SECRET_KEY/TELEGRAM_SIGNATURE_SECRET`).
2. **[high] A2.** `VaultSecretRefresher` создавался в composition root
   (`plugins/composition/di.py`), но `start()` не вызывался — фоновая
   ротация секретов не работала.
3. **[high] A3.** `OutboundHttpClient.__init__` подставлял `policy or
   WafPolicy()` — пустую permissive-policy. Вызывающие без явной policy
   (`make_http_client`, прямые `OutboundHttpClient(...)`) обходили
   `waf_settings` (в prod — `strict=true` + allowlist).
4. **[high] A4.** `ibm_db_sa` (DB2 sync) недоступен для установки, а
   диалект `sqlalchemy.dialects.db2` удалён в SQLAlchemy 2.0.
5. **[high] A5.** Pillow 12.3.0 закрывает 59 уязвимостей (5 CRIT), все
   исправлены в 13.0.0, но пин `pillow>=12.3.0,<13.0.0` не даёт обновиться.
6. **[high] A6.** Job `pip-audit` сканировал только default-venv
   (`uv sync`) — 41 из 117 уязвимостей (в extras) не проверялись.
7. **[high] A7.** Computed-поля `async_connection_url` / `sync_connection_url`
   внешней БД содержали пароль открытым текстом → `GET /api/v1/admin/config`
   отдавал пароль.
8. **[high] A8.** `settings.model_dump()` падал без кредов
   (`ValueError: Не найден username для внешней БД 'oracle_1'`,
   `DatabaseDriverError: 'psycopg' не установлен`) → admin 500.
9. **[medium] A9.** `validate-profile` не валидировал `database` и не знал
   `external_databases` → `pool_size: 0`, `port: 99999` проходили с exit 0.
10. **[medium] A10.** Item-модель `external_databases.connections[]` имела
    `extra=ignore` → опечатки (`sslmode`, `pool_sze`) терялись молча.
11. **[medium] A11.** Hot-reload не применяется к пулам БД: engine печётся
    при создании, правка YAML не влияет на живой пуль.

## Решение

### A1. env-гейт разрешает наследование полей

`tools/check_env_example.py` переведён на резолвер
`tools/config_audit.py` (`_parse_config_classes` + `_resolve_fields` +
`_resolve_env_prefix`): собираются поля класса **вместе с полями базовых
классов и mixin'ов**. Required-ness уточняется отдельным проходом по AST
(`Field(default_factory=...)` не считается обязательным). Девять ключей
уже были описаны в `.env.example` пустыми значениями — теперь гейт их
видит («не используются в Settings» → 20 → 11 записей; оставшиеся 11 —
секреты, читаемые напрямую из `os.environ`).

### A2. `VaultSecretRefresher` подключён к lifespan

`plugins/composition/setup_infra/lifecycle.py`: добавлены
`_start_vault_secret_refresher` / `_stop_vault_secret_refresher` и пара
операций `start_vault_secret_refresher` (start + stop) в типизированном
`_build_infrastructure_operations()` и в legacy-списки
`starting_operations` / `ending_operations`. Ошибка старта/остановки
логируется и деградирует (Vault — опциональный источник), criticality
операции — `OPTIONAL`.

### A3. WAF-policy по умолчанию — из настроек

`core/net/outbound_http.py`: добавлен `_policy_from_settings()` —
`WafPolicy` из `waf_settings` (`allow_hosts`, `deny_hosts`, `strict`,
`max_payload_bytes`). `OutboundHttpClient` использует её, когда policy не
передана явно; недоступность конфигурации → прежняя permissive-policy.
Явная policy всегда в приоритете.

### A4. DB2 — fail-fast (выполнено кластером X2)

`core/config/db_drivers.py::UNSUPPORTED_SQLALCHEMY_DB_TYPES` содержит
fail-fast «DB2 не поддерживается», `core/config/database.py` вызывает
`ensure_driver_pair_supported`, запись `ibm_db_sa` снята из
`tools/check_dsn_drivers_allowlist.txt`; гейт
`tools/check_dsn_drivers.py --ci --scope declarations` — exit 0.

### A5. Пин Pillow — конфликт резолвера, пин возвращён с обоснованием

Пин снят во всех трёх местах (`pyproject.toml:266` — extra `rpa`, `:301` —
extra `rpa-windows`, `:644` — extra `multimodal-rag`: `>=13.0.0,<14.0.0`),
после чего выполнен `uv lock`. Резолвер вернул **конкретный блокер**:

```
streamlit>=1.59.0,<=1.59.2 depend on pillow>=7.1.0,<13
streamlit>=1.64.0,<=1.66.0 depend on pillow>=7.1.0,<13
→ your project's requirements are unsatisfiable
```

`streamlit` — core-зависимость (`streamlit>=1.58.0,<2.0.0`, locked 1.63.0,
`Requires-Dist: pillow<13,>=7.1.0`), поэтому единая версия Pillow в
lock-файле не может быть `>=13`. Пин возвращён (`>=12.3.0,<13.0.0` для
`rpa`/`rpa-windows`, `>=10.0.0,<13.0.0` для `multimodal-rag`) с
комментарием в `pyproject.toml` о блокере; `uv lock --check` проходит
(712 пакетов), `uv.lock` не изменён.

**Риск принят осознанно:** 59 уязвимостей Pillow 12.3.0 (5 CRIT) не
закрыты — обновление требует сначала обновить `streamlit` до версии с
`pillow<14` (или снять его верхнюю границу), что затрагивает 95
frontend-импортов и вне зоны кластера. Advisory-ID Pillow 12.x
зафиксированы в `.security/uv-audit-allowlist.txt` (тот же baseline, что
и для остальных пакетов).

### A6. Аудит всего lock-файла — блокирующий гейт

В job `pip-audit` (`.github/workflows/security.yml`) добавлены ДВА шага
ПЕРЕД существующим pip-audit-сканом:

1. `uv audit --frozen > uv-audit.txt` — аудит **всего** `uv.lock`
   (все extras) без установки пакетов; сам вызов не роняет шаг (uv
   возвращает exit 1 при найденных уязвимостях);
2. `python tools/uv_audit_gate.py --report uv-audit.txt` — гейт.

`uv audit` **не умеет** читать allowlist-файл (только `--ignore` в CLI —
проверено `uv audit --help`), поэтому allowlist разбирает гейт:
`tools/uv_audit_gate.py` парсит текстовый отчёт (JSON-вывода у uv нет),
сверяет advisory-ID с canonical allowlist
`.security/uv-audit-allowlist.txt` и **падает** на любой новой ID;
пустой/битый отчёт или отсутствие allowlist → fail-closed. Текущий долг —
98 advisory-ID / 99 уязвимостей в 711 пакетах (chromadb/diskcache без
фикса, pillow/virtualenv/filelock отложены) — зафиксирован в allowlist.
Job `pip-audit` остаётся вторым сканом (blocking).

### A7/A8. Внешняя БД: маскирование DSN и безопасный дамп

`external_databases/connection.py`:
* `@field_serializer("async_connection_url", "sync_connection_url")` →
  `mask_url_password()` (канон `core/config/base/__init__.py`) — в дампе
  пароля нет, атрибут DSN остаётся рабочим;
* `username`/`password` стали опциональными, `_build_dsn` собирает DSN без
  userinfo-части, если кредов нет, и логирует warning при недоступном
  драйвере — computed-поля не роняют `model_dump()`.

`external_databases/registry.py`: отсутствие кредов больше не поднимает
`ValueError` на этапе дампа (профиль деградирует с warning'ом), а
`get_profile()` по-прежнему падает с понятной ошибкой в точке
использования.

### A9. `validate-profile` валидирует секции БД

`core/config/validator/profile_merge.py`: добавлена
`_validate_model_section()` — `model_validate` секции по её pydantic-модели
с превращением ошибок в CRITICAL-нарушения. Проверяются `database`
(`DatabaseConnectionSettings`) и `external_databases`
(`ExternalDatabasesSettings`); `ProfileSettings` теперь знает секцию
`external_databases`.

### A10. `connections[]` — `extra="forbid"`

`external_databases/item.py`: `model_config = ConfigDict(populate_by_name=True,
extra="forbid")` — опечатка в ключе подключения отвергается валидацией.
`registry._resolve_connection` при этом исключает computed-поля item'а
(`username_env_key`, `password_env_key`) из payload.

### A11. Hot-reload и пулы БД — нужен рестарт

Задокументировано (ADR + `docs/config/SETTINGS_GUIDE.md`): SQLAlchemy
`engine`/`pool` печётся при создании, поэтому правка `database.*` /
`external_databases.*` в YAML не влияет на живой пуль — требуется
**рестарт процесса**. Предупреждение в самом отчёте reload не добавлено:
`core/config/hot_reload.py` вне зоны кластера.

## Альтернативы (отклонённые)

1. **Оставить `check_env_example` на собственном AST-сканере и просто
   расширить список полей вручную.** Отклонено: список mixin'ов будет
   разъезжаться с кодом; канонический резолвер уже есть в `config_audit`.
2. **Вызывать `VaultSecretRefresher.start()` в `di.py` при регистрации
   состояния.** Отклонено: `di.py` — синхронный composition root без
   event loop; lifecycle-операция даёт парный start/stop и отчёт.
3. **Сделать `OutboundHttpClient` обязательным потребителем `waf_settings`
   (без fallback).** Отклонено: конфигурация может быть недоступна в
   unit-тестах/CLI — клиент не должен падать из-за этого.
4. **Маскировать пароль в самом `_build_dsn`.** Отклонено: тогда
   SQLAlchemy получит нерабочий DSN. Маскирование — только в сериализации.
5. **Оставить `ValueError` при отсутствии кредов и чинить только дамп
   через `field_serializer`.** Отклонено: исключение arises раньше
   сериализации — `model_dump()` падает на самом computed-поле `profiles`.
6. **Валидировать секции БД через `model_construct` + ручные проверки.**
   Отклонено: дублирование ограничений модели; `model_validate` — тот же
   контракт, что в рантайме.
7. **Сделать `uv audit --frozen` шагом без allowlist (99 уязвимостей →
   красный CI).** Отклонено: гейт должен блокировать **новые** advisory,
   а не быть всегда-красным; принят канонический allowlist (паттерн
   `pip-audit`).
8. **Пересоздавать пулы БД по hot-reload.** Отклонено: вне зоны и по
   объёму (engine/сессии/транзакции); зафиксировано «нужен рестарт».
9. **Оставить `uv audit --frozen` отдельным job'ом.** Отклонено: тот же
   скан выполняется в одном месте с `pip-audit` (общий allowlist-контур,
   один артефакт-отчёт), отдельный job дублировал бы установку uv.

## Последствия

* **Позитивные:** гейт env-видит наследованные секреты; фоновый рефрешер
  секретов реально работает; WAF-настройки действуют для всех вызывающих;
  admin-конфиг не отдаёт пароль и не падает без кредов; битые значения БД
  ловятся до деплоя; опечатки в подключениях больше не теряются; CI
  проверяет уязвимости во всех extras.
* **Негативные / breaking:** в prod/staging запросы к хостам вне
  `waf.allow_hosts` теперь блокируются и для вызывающих, которые раньше
  шли с permissive-policy (ожидаемое поведение, но требует проверки
  allowlist); `external_databases.connections[]` с опечаткой в YAML теперь
  не стартует (fail-fast вместо тихой потери настройки); `validate-profile`
  возвращает CRITICAL на невалидных секциях БД; в CI появился новый tool-гейт
  (`tools/uv_audit_gate.py`) и новый allowlist; 59 CVE Pillow 12.x
  остаются (осознанно принятый риск, см. A5).
* **Не выполнено (вне зоны):** A11 — без предупреждения в отчёте reload
  (задокументировано); A5 — пин Pillow снять нельзя до обновления
  `streamlit` (блокер зафиксирован в самом ADR).

## Проверка

```bash
.venv/bin/python -m pytest \
    tests/unit/tools/test_check_env_example_inheritance.py \
    tests/unit/tools/test_uv_audit_gate.py \
    tests/unit/plugins/composition/test_vault_refresher_wired.py \
    tests/unit/core/net/test_outbound_http_waf_settings.py \
    tests/unit/core/config/external_databases/test_connection_safety.py \
    tests/unit/core/config/test_validate_profile_db_sections.py -q
.venv/bin/python tools/check_env_example.py --secrets-only   # exit 0
.venv/bin/python tools/check_env_example.py --matrix         # exit 0
.venv/bin/python tools/config_audit.py --scope orphans      # 0
.venv/bin/python tools/check_layers.py --strict             # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0373** — «в `.env` только секреты»: A1 возвращает гейту девять
  живых секретов, которые он не видел из-за наследования.
* **ADR-0377** — WAF-allowlist: A3 делает allowlist действующим для всех
  вызывающих, а не только для зарегистрированного в svcs клиента.
* **ADR-0378** — маскирование секретов в дампах: A7 расширяет канон на
  внешний контур БД.
* **ADR-0379** — честный hot-reload: A11 фиксирует честный **предел**
  hot-reload (пулы БД требуют рестарта).
* **ADR-0381** — fail-fast для несовместимых пар СУБД/драйвер: A4 и A8
  используют тот же механизм (`ensure_driver_pair_supported`), но в
  computed-полях он деградирует, а не роняет дамп.
