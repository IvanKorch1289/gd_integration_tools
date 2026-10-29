# ADR-0378 — Маскирование секретов в дампах/логах и необъявленные env-секреты

* Статус: Accepted (2026-10-29, wave 15, кластер W3)
* Cycle: 175
* Дата: 2026-10-29
- **Затрагивает**: `src/backend/core/config/base/__init__.py`,
  `src/backend/core/config/services/cache.py`,
  `src/backend/core/config/database.py`,
  `src/backend/core/config/mongo.py`,
  `src/backend/core/config/security.py`,
  `src/backend/plugins/composition/lifecycle/startup.py`,
  `.env.example`, `tests/unit/core/config/test_secret_typing*.py`
- **Связан с**: ADR-0373 (`.env` только секреты), ADR-0375 (типизация
  секретов, wave 14), ADR-0362 (orphan- vs missing-класс аудита)

## Контекст

Независимый свип функционала настроек (волна 15, кластер W3 «Секреты: утечки
и покрытие») зафиксировал пять дефектов:

1. **Пароль Redis утекал в лог.** `RedisSettings.redis_url` содержал
   `:{password}@`, а `startup.py` писал этот URL в лог на INFO (и в warning
   при таймауте). Проба свипа:
   `EventBus started on redis://:REDISPASS-SECRET-1@redis.local:6379`.
2. **`model_dump()`/`model_dump_json()` отдавали секреты открытым текстом.**
   `computed_field(repr=False)` влияет только на `__repr__`: DSN БД
   (`async_connection_url`/`sync_connection_url`), строка подключения Mongo
   (`connection_string`) и `redis_url` попадали в дампы в открытом виде.
3. **Пять живых секретов не были документированы:** `ANTHROPIC_API_KEY`,
   `GEMINI_API_KEY`, `LAKERA_API_KEY`, `NEO4J_PASSWORD`, `TELEGRAM_BOT_TOKEN`
   читаются напрямую из `os.environ` (без Settings-модели) и отсутствовали
   в `.env.example` — гейты их не видели.
4. **`SecureSettings.webhook_signature_secrets: dict[str, str]`** — HMAC-ключи
   в контейнере: `tools/config_secret_rules.py::NON_SECRET_TYPE_HINTS`
   считает `dict`/`list` принципиально несекретными, поэтому поле не
   типизировано, не требуется в `.env.example` и может утечь в `repr`/дамп.
5. **`check_env_example --strict` не разрешает наследование** — секреты из
   `os.environ` (и переменные, не выведенные из Settings) помечаются
   «не используются», часть живых секретов гейту не видна.

## Решение

### (а) Маскирование в дампах, рабочее значение — в атрибуте

`core/config/base/__init__.py` — общий хелпер `mask_url_password(url)`:
пароль в userinfo-части URL/DSN заменяется на `***`
(`redis://:pass@host:6379` → `redis://:***@host:6379`). Хелпер **не**
добавлен в `__all__` facade'а — ratchet-тест экспортов
`tests/unit/core/config/base/test_init.py` фиксирует ровно 2 символа
(явный импорт по имени при этом работает).

В моделях `RedisSettings.redis_url`, `DatabaseConnectionSettings.async_connection_url` /
`sync_connection_url`, `MongoConnectionSettings.connection_string` добавлены
`@field_serializer`: **атрибут модели остаётся рабочим** (клиент подключается
с настоящим паролем), а `model_dump()`/`model_dump_json()` отдают замаскированное
значение. Для логов добавлено свойство `RedisSettings.redis_url_masked`.

### (б) Лог старта

`plugins/composition/lifecycle/startup.py` пишет в лог
`settings.redis.redis_url_masked` (INFO и warning), а в EventBus передаёт
`settings.redis.redis_url` — подключение не изменено.

### (в) Необъявленные env-секреты

В `.env.example` добавлены пустыми `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`LAKERA_API_KEY`, `NEO4J_PASSWORD`, `TELEGRAM_BOT_TOKEN` (+ тест, что они
перечислены и реально используются в `src/backend`).

### (г) HMAC-ключи вебхуков

`webhook_signature_secrets` оставлен `dict[str, str]` (контракт
`WebhookSignatureMiddleware` — `Mapping[str, str]`, файл вне зоны кластера),
но: поле скрыто из `repr` (`repr=False`) и значения маскируются в дампах
(`@field_serializer` → `{prefix: "***"}`). В рантайме маппинг не изменён.

### (д) Owner-задачи (вне зоны — `tools/`)

* `tools/config_secret_rules.py::NON_SECRET_TYPE_HINTS`: `dict`/`list`/`set`
  исключены как «несекретные» без разбора generic-аргумента → контейнеры
  секретов (`dict[str, SecretStr]`, `list[SecretStr]`) не признаются
  секретами. Нужно смотреть на generic-параметры, а не только на имя типа.
* `tools/check_env_example.py`: `--strict` считает «лишними» переменные,
  которых нет в Settings (секреты из `os.environ` — ровно наш случай), и не
  разрешает наследование → переиспользовать `_resolve_fields` из
  `tools/config_audit.py`, чтобы «используется» считалось по коду, а не
  только по моделям.
* Типизация `webhook_signature_secrets` в `dict[str, SecretStr]` — вместе с
  адаптацией `entrypoints/middlewares/webhook_signature.py` (HMAC считается
  по байтам секрета).

## Альтернативы

* **Маскировать само `redis_url`** — отклонено: `redis_url` используется
  клиентом для подключения (`infrastructure/clients/messaging/stream.py`,
  вне зоны) — подключение сломается.
* **Вернуть в `repr=False`/`SecretStr` только пароли** — отклонено: `repr=False`
  не влияет на `model_dump()` — именно это и было дефектом.
* **`dict[str, SecretStr]` для HMAC-ключей** — отклонено в этой волне:
  middleware вне зоны принимает `Mapping[str, str]` и получил бы `SecretStr`
  (HMAC-считание сломалось бы). Выбран эквивалентный по эффекту вариант —
  маскирование в `repr`/дамп.
* **Отдельный модуль `core/config/secret_mask.py`** — отклонено: хелпер
  положен в `core/config/base/__init__.py` (в зоне кластера), чтобы не
  плодить модули без нужды.

## Последствия

* Поведение рантайма не изменилось: подключения к Redis/БД/Mongo используют
  настоящие пароли, middleware получает настоящие HMAC-ключи.
* Дампы настроек (`model_dump`/`model_dump_json`, в т.ч. вложенные модели в
  агрегате `Settings`) больше не содержат паролей открытым текстом.
* В `.env.example` появились 5 новых ключей — `check_env_example --strict`
  покажет их как «не используются в Settings» до решения owner-задачи (п. д);
  режим `--secrets-only` и `config_audit --scope missing` проходят.
* `RedisSettings.redis_url_masked` — новое публичное свойство (логи/диагностика).

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/config/test_secret_typing.py \
    tests/unit/core/config/test_secret_typing_extended.py \
    tests/unit/core/config/test_secret_typing_env_example.py -q -p no:randomly
.venv/bin/python tools/check_env_example.py --secrets-only   # rc=0
.venv/bin/python tools/config_audit.py --scope orphans       # rc=0
.venv/bin/python tools/check_layers.py --strict              # без новых нарушений
```

## Связи

* ADR-0373 — правило «в `.env` только секреты» и гейты (`check_env_example`,
  `config_secret_rules`).
* ADR-0375 — типизация секретов как `SecretStr` (wave 14): `repr=False` у
  computed-полей закрыл только `__repr__` — этот ADR закрывает дампы.
* ADR-0362 — разделение orphan- и missing-класса аудита конфигурации.
