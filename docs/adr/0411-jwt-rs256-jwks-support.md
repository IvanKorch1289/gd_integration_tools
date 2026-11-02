# ADR-0411 — RS256/JWKS: поддержка асимметричного режима JWT, генерация ключевой пары и контракт ротации (волна 23, кластер C1)

* Статус: Accepted (2026-11-02, волна 23, кластер C1 — RS256 + JWKS)
* Cycle: 182 (волна 23)
* Связан с:
  - ADR-0407 (прод-значения: контракты HS256 — «секрет обязателен»; переход на RS256 объявлен owner-задачей),
  - ADR-0371 (прод-значения, оставленные осознанно — источник owner-задач),
  - ADR-0403 (прод-валидатор: JWT-алгоритм и AI-fallback),
  - ADR-0385 (env-ключи с наследованием — env-имена настроек),
  - ADR-0400/ADR-0408 (образец формата ADR волны 22)
* Затрагивает:
  - `src/backend/core/security/jwt_keys.py` (новый),
  - `src/backend/core/auth/jwt_backend_class.py`, `jwt_backend.py`,
    `jwt_backend_helpers.py`, `jwks_cache.py`, `jwt_signing.py` (новый),
  - `src/backend/core/di/providers/auth.py`,
  - `src/backend/core/config/security.py`,
  - `src/backend/entrypoints/api/v1/endpoints/auth_login.py`,
  - `docs/config/SETTINGS_GUIDE.md`,
  - `tests/unit/core/auth/test_jwt_asymmetric_mode.py`,
    `tests/unit/core/auth/test_jwt_provider_modes.py`,
    `tests/unit/core/security/test_jwt_keys.py`,
    `tests/unit/entrypoints/api/v1/test_auth_login_rs256.py`

---

## Контекст

ADR-0407 закрыл контракт «HS256 в prod допустим только при гарантированном
секрете» и зафиксировал переход prod на RS256 как **owner-задачу**
(OWNER_TASKS § 3.1): «нужна RSA-keypair + JWKS/IdP». Кодовой поддержки
асимметричного режима в проекте фактически не было:

1. **Выпуск токенов всегда HS256.** `POST /auth/login` вызывал
   `jwt_backend.encode(..., secret=...)` без `alg` — то есть даже при
   `security.algorithm=RS256` выпускался HS-токен, который RS-режим
   проверки не принимает. Переключение алгоритма ломало логин.
2. **Нет источника ключа, кроме JWKS.** `SecureSettings` знал только
   `jwks_url`; локальный PEM-публичный ключ не поддерживался, хотя
   выпуск и проверка в одном сервисе (без внешнего IdP) требуют именно
   его. `JwtBackend` требовал `jwks` для любого асимметричного алгоритма.
3. **Algorithm confusion (незакрытый вектор).** DI-провайдер при заданном
   `jwks_url` **молча добавлял** `RS256` в allowlist HS256-режима
   (`algorithms = list({*algorithms, "RS256"})`). В одном backend'е
   оказывались и HS-секрет, и публичный ключ — классическая схема подмены
   алгоритма: злоумышленник берёт публичный ключ из JWKS и подписывает
   HS256-токен этим ключом как HMAC-секретом.
4. **Нет инструмента выпуска ключей.** Нечем было выпустить RSA-пару
   (PKCS#8/SPKI PEM) без сети и без новых зависимостей; `kid` не был
   определён, то есть ротация ключей не была описана.
5. **Нет контракта для владельца.** В SETTINGS_GUIDE был только абзац
   «переход на RS256 — owner-задача»: что задать в prod, что означает
   смена `security.algorithm`, как ротировать и как отозвать старый `kid` —
   не зафиксировано.

Зависимости, доступные без изменений: `cryptography` (генерация ключей,
PEM-форматы), `joserfc` (подпись/проверка, JWK-импорт) — обе уже в
`pyproject.toml`.

---

## Решение

### 1. Режим определяется алгоритмом; режимы взаимноисключающие

`JwtBackend` получил инвариант: **нельзя смешивать** симметричные (`HS*`) и
асимметричные (`RS*`/`ES*`/`PS*`) алгоритмы в одном backend'е
(`jwt_backend_class.py`, `__post_init__`). Смешение — ровно тот вектор
algorithm confusion, который требовалось закрыть.

* `HS*` → используется только `secret`; `jwks`/`public_key` не подключаются
  (раньше `jwks_url` молча расширял allowlist — теперь нет).
* `RS*`/`ES*` → используется `public_key` (локальный PEM) и/или `jwks`;
  shared secret **не используется** — «тихого» downgrade нет.
* Асимметричный режим без источника ключа (`jwks_url` **или**
  `jwt_public_key_path`) → backend не собирается (fail-closed, `ValueError`).
* Явный отказ при несоответствии алгоритма и ключа: RSA-ключ под `ES256`
  (и наоборот) отвергается **до** проверки подписи
  (`_assert_key_matches_alg`); HS-токен в RS-режиме отвергается с
  сообщением «алгоритм не разрешён».

### 2. Источники ключа: JWKS **или** локальный PEM

`JwtBackend` получил поле `public_key` (статический JWK из PEM) и `kid`
(ожидаемый `kid`; `None` — не проверяется, single-key-развёртывание).
Приоритет: `public_key` → JWKS-резолв по `kid` из заголовка. В JWKS-режиме
`kid` обязателен, неизвестный `kid` отвергается («Ключ `<kid>` не найден в
JWKS»). `JwksCache` получил параметр `timeout` — значение
`security.jwks_fetch_timeout` теперь действительно применяется (раньше
было зашито `5.0`).

### 3. Выпуск токенов по конфигурации (`core/auth/jwt_signing.py`)

Новая точка подписи: `resolve_signing_params()` + `encode_token()`.
Алгоритм, ключ и `kid` берутся из `SecureSettings`; `POST /auth/login`
вызывает её вместо ручной передачи `secret`. Явный `alg`, несовместимый по
семейству с настроенным, приводит к ошибке («тихой» downgrade запрещён).
В асимметричном режиме `kid` выводится детерминированно из публичного ключа,
если `security.jwt_kid` не задан.

### 4. Генерация ключевой пары (`core/security/jwt_keys.py`)

```bash
python -m src.backend.core.security.jwt_keys generate --out <dir>
```

* приватный ключ — PKCS#8 PEM, публичный — SPKI PEM (RFC 7468);
* `kid` — `sha256` от DER SPKI (16 hex-символов), детерминированный;
* **идемпотентность по пути**: повторный запуск с тем же `--out` не
  перетирает ключ (перевыпуск — только `--force`), иначе ранее выпущенные
  токены мгновенно перестали бы проверяться;
* права: приватный ключ `0600`, публичный и `jwks.json` — `0644`;
* рядом пишется `jwks.json` — готовый JWKS-документ для публикации;
* без сети и без новых зависимостей (`cryptography` + `joserfc`).

### 5. Конфигурация

`SecureSettings` получила `jwt_private_key_path`, `jwt_public_key_path`,
`jwt_kid`; `algorithm` —Literal расширен значением `ES256`. Env-имена:
`SEC_JWT_PRIVATE_KEY_PATH`, `SEC_JWT_PUBLIC_KEY_PATH`, `SEC_JWT_KID`.

### 6. Контракт для владельца (документация)

`docs/config/SETTINGS_GUIDE.md` → «JWT: алгоритм, ключи и режим
(ADR-0411)»: что задать в prod (вариант A — внешний IdP с `jwks_url`;
вариант B — собственный JWKS с PEM + `kid`), что означает смена
`security.algorithm` (смена режима: выпуск и проверка; окно пересечения по
TTL), процедура ротации (новый каталог → деплой новой пары → JWKS с обоими
ключами → ожидание TTL → удаление старого `kid`) и отзыв старого `kid`.

---

## Альтернативы

* **Оставить смешение HS+RS в одном backend'е.** Отклонено: это и есть
  vector algorithm confusion (публичный ключ как HMAC-секрет). Владелец,
  которому нужно принимать и свои HS-токены, и токены IdP, поднимает
  **два** backend'а явно, а не получает неявный allowlist.
* **`jwt.PyJWKClient` (PyJWT).** Отклонено: в проекте канонический JWT-слой
  — `joserfc`; `PyJWKClient` тянет httpx-клиент с собственной политикой
  таймаутов/ретраев, дублируя `JwksCache` (TTL + stale-fallback), который в
  проекте уже есть и покрыт тестами.
* **Свой JWKS-клиент на `urllib` (fallback из ТЗ).** Отклонено как
  ненужное: `JwksCache` уже реализован и покрыт тестами (TTL, lock,
  stale-fallback, `get_key` по `kid`).
* **Хранить приватный ключ в `SecureSettings` (inline PEM).** Отклонено:
  приватный ключ в YAML/env-конфиге — это секрет в конфиге; файл с правами
  `0600` + путь в конфиге — стандартная схема для keypair-сервиса.
* **Генерировать ключи в рантайме при старте.** Отклонено: приватный ключ
  должен быть долгоживущим и общим между репликами; генерация на старте
  ломает проверку токенов после рестарта/деплоя.
* **Менять `security.algorithm` только в валидаторе (кластер C2).**
  Отклонено: валидатор не может изменить поведение рантайма — режим
  определяется кодом (`core/di/providers/auth.py` + `JwtBackend`).

---

## Последствия

* `security.algorithm=RS256` в prod/staging перестаёт быть «ломающей
  настройкой»: выпуск и проверка работают, ключи генерируются утилитой,
  контракт описан в SETTINGS_GUIDE.
* Algorithm confusion закрыт: смешение режимов запрещено конструктором,
  несоответствие типа ключа и алгоритма отвергается явно.
* `jwks_url` в HS-режиме больше не расширяет allowlist — это изменение
  поведения для конфигураций, которые полагались на «широкий» allowlist.
  В репозитории таких конфигураций нет (`config_profiles/*.yml` не задают
  `jwks_url`); для внешних развёртываний изменение описано в ADR и
  SETTINGS_GUIDE.
* Новых зависимостей нет: `cryptography` и `joserfc` уже были в
  `pyproject.toml`.
* Линтер слоёв: новые модули — `core/security` → `core/security` и
  `core/auth` → `core/security`/`core/config` (core → core), нарушений не
  добавлено (baseline 41).

---

## Проверка

* `tests/unit/core/security/test_jwt_keys.py` — формат PEM (PKCS#8/SPKI),
  детерминированный `kid`, round-trip подпись/проверка, идемпотентность
  `write_keypair` по пути, права `0600`, JWKS-документ, CLI
  (`generate --out`, повторный вызов, код возврата).
* `tests/unit/core/auth/test_jwt_asymmetric_mode.py` — проверка RS256 по
  локальному публичному ключу; JWKS-резолв по `kid` (заглушка) и отказ по
  неизвестному `kid`; отказ по `kid`-mismatch; **HS256-токен в RS256-режиме
  отвергается**; **algorithm confusion (HS256-подпись публичным ключом)
  отвергается**; EC-ключ под RS256 отвергается; конструктор запрещает
  смешение HS*/RS* и требует `jwks`/`public_key`; low-level `decode`
  отвергает алгоритм вне allowlist.
* `tests/unit/core/auth/test_jwt_provider_modes.py` — DI-провайдер строит
  режим по алгоритму (secret ↔ PEM/JWKS), `jwks_url` не расширяет HS-режим,
  симметричный секрет не попадает в асимметричный режим, отсутствие
  источника ключа → fail-closed; выпуск RS256-токена (подпись приватным,
  проверка публичным, `kid` в заголовке); запрет downgrade по явному `alg`;
  контракт конфигурации (`SecureSettings.model_fields`).
* `tests/unit/entrypoints/api/v1/test_auth_login_rs256.py` — `POST
  /auth/login` в RS256-режиме выпускает RS256-токен с `kid` (проверяется
  публичным ключом), в HS-режиме — HS256-токен, без приватного ключа —
  fail-closed.
* Гейты: `ruff check` (по изменённым файлам) — чисто; `ruff format` — чисто
  по моим файлам; `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` → 41 (baseline не изменился);
  `tools/checks/mypy_budget.py` → OK; `tools/check_docstrings.py` → 0
  missing по новым модулям.

---

## Открытое (owner-задачи и инфраструктура)

1. **Прод-конфигурация.** Владелец: безопасность/платформа. Критерии
   приёмки: выпущена RSA-паре (`python -m src.backend.core.security.jwt_keys
   generate --out /etc/gd/keys`), в профиле prod заданы
   `security.algorithm=RS256`, `security.jwt_private_key_path` и
   (`security.jwt_public_key_path` **или** `security.jwks_url`),
   `security.jwt_kid`; `POST /auth/login` возвращает RS256-токен;
   `manage.py validate-profile prod` → 0 CRITICAL.
2. **Правило валидатораprod (кластер C2, `profile_merge.py` — не в зоне
   этого ADR).** Требуемое правило: в prod при асимметричном
   `security.algorithm` (`RS*`/`ES*`) должен быть задан источник ключа для
   проверки — `security.jwks_url` **или** `security.jwt_public_key_path` —
   иначе CRITICAL (например, `security.jwt_asymmetric_algorithm_without_key_source`).
   Симметричный `HS*` в prod остаётся под контрактом ADR-0407
   (`security.jwt_symmetric_algorithm_without_secret`). Дополнительно
   рекомендуется WARNING, если при `HS*` заданы `jwks_url` или
   `security.jwt_*_key_path` (ключи игнорируются — «тихий» downgrade не
   допускается), и CRITICAL, если `security.jwt_private_key_path` и
   `security.jwt_public_key_path` указывают на один файл.
3. **JWKS-endpoint.** Владелец: эксплуатация/платформа. Критерии: JWKS
   (собственный или IdP) доступен из контура приложения, отдаёт `kid`
   выпущенного ключа, обновляется при ротации; stale-fallback проверен.
4. **Индекс ADR.** `docs/adr/INDEX.md` не редактировался в рамках этого ADR
   (правило кластера) — индекс перегенерируется отдельной операцией
   (`tools/generate_adr_index.py`).

---

## Связи

* ADR-0407 — прод-значения: контракты HS256 (секрет обязателен) и
  owner-задача перехода на RS256.
* ADR-0371 — прод-значения, оставленные осознанно (источник owner-задач).
* ADR-0403 — прод-валидатор: JWT-алгоритм и AI-fallback (образец проверок
  для кластера C2).
* ADR-0385 — env-ключи с наследованием (env-имена `SEC_*`).
* `docs/config/SETTINGS_GUIDE.md` — «JWT: алгоритм, ключи и режим
  (ADR-0411)» и «Прод-значения: контракты (ADR-0407)».
* `docs/roadmap/OWNER_TASKS.md` § 3.1 — «Переход prod на RS256».
* `src/backend/core/security/jwt_keys.py` — утилита генерации ключевой пары.
* `src/backend/core/auth/jwt_backend_class.py` — инварианты режима и
  явный отказ при несоответствии алгоритма и ключа.
