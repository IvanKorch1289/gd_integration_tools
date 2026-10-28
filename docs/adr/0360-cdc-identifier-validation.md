# ADR-0360 — Allowlist-валидация идентификаторов в CDC (cycle 172)

* Статус: Accepted (2026-10-27, cycle 172)
* Cycle: 172
* Связан с:
  - [ADR-0112](0112-security-audit-status.md) — allowlist/escape-паттерн для SQL
  - [ADR-0284](0284-architectural-debt-resolution.md) — ограничения межслойных зависимостей
* Затрагивает:
  - `src/backend/infrastructure/clients/external/cdc/_identifiers.py`
  - `src/backend/infrastructure/clients/external/cdc/client.py`
  - `src/backend/infrastructure/clients/external/cdc/strategies.py`
  - `src/backend/infrastructure/clients/external/cdc/events.py`
  - `src/backend/infrastructure/cdc/poll_backend.py`
  - `src/backend/entrypoints/cdc/cdc_routes.py`

## Контекст

Имена таблиц и timestamp-колонок CDC-подписки нельзя передать через
bind-параметры: bind-параметры применяются к значениям, а не к SQL-
идентификаторам. Поэтому в polling- и LogMiner-стратегиях имена
подставлялись в SQL через f-string.

До Wave 13:

- `_PollingStrategy` использовал `sub.tables` и `sub.timestamp_column`
  непосредственно в SQL;
- `_LogMinerStrategy` собирал `TABLE_NAME IN (...)` из
  `sub.tables` без allowlist-проверки и без escape строковых литералов;
- `PollCDCBackend` аналогично использовал `target_table` и
  `timestamp_column` в f-string;
- `CDCSubscription` оставался plain dataclass без валидации полей
  (`src/backend/infrastructure/clients/external/cdc/events.py:39-53`);
- REST-эндпоинт создания подписки принимал `tables` из тела запроса
  (`src/backend/entrypoints/cdc/cdc_routes.py:31-38`) и передавал их в
  client (`src/backend/entrypoints/cdc/cdc_routes.py:50-62`).

Таким образом, недоверенное имя из REST-запроса могло дойти до SQL.

## Решение

### 1. Allowlist-регекс в слое infrastructure

Создан модуль
`src/backend/infrastructure/clients/external/cdc/_identifiers.py` с тремя
функциями:

- `validate_identifier(value, *, context)`;
- `validate_subscription_identifiers(sub)`;
- `escape_sql_literal(value)`.

Регекс допускает только `name`, `schema.name` и `db.schema.name`
(`src/backend/infrastructure/clients/external/cdc/_identifiers.py:31-36`).
Проверка и текст ошибки находятся в
`src/backend/infrastructure/clients/external/cdc/_identifiers.py:39-68`,
проверка идентификаторов подписки (`tables` и `timestamp_column`) — в
`src/backend/infrastructure/clients/external/cdc/_identifiers.py:71-87`.

Это тот же allowlist-подход, что зафиксирован в ADR-0112, но helper
размещён в `infrastructure`: импорт из `services` нарушил бы правило
слоёв, закреплённое ADR-0284.

### 2. Fail-fast в `CDCClient.subscribe()`

`CDCClient` валидирует подписку **до** регистрации в
`self._subscriptions` и до запуска фоновой задачи
(`src/backend/infrastructure/clients/external/cdc/client.py:146-167`).
Недоверенное имя отклоняется сразу, а не в середине polling-цикла.

`CDCSubscription` остаётся простой dataclass-моделью; решение не
добавляет инфраструктурную зависимость в DTO и валидирует на
эксплуатационных границах.

### 3. Defence in depth в стратегиях

Валидация повторяется непосредственно перед построением SQL:

- polling: `src/backend/infrastructure/clients/external/cdc/strategies.py:91-112`;
- LogMiner: `src/backend/infrastructure/clients/external/cdc/strategies.py:303-327`.

Это защищает не только REST-путь, но и прямые callers, создающие
`CDCSubscription` внутри кода.

### 4. LogMiner: escape строковых литералов

Имена таблиц в LogMiner дополнительно экранируются через
`escape_sql_literal()` при построении `TABLE_NAME IN (...)`
(`src/backend/infrastructure/clients/external/cdc/strategies.py:343-363`).
Escape реализован в
`src/backend/infrastructure/clients/external/cdc/_identifiers.py:90-104`;
allowlist остаётся основным барьером, escape — вторым.

### 5. `PollCDCBackend`

`PollCDCBackend.subscribe()` валидирует default table, timestamp-колонку
и все переданные таблицы до запуска polling SQL
(`src/backend/infrastructure/cdc/poll_backend.py:88-110`). После этого
f-string использует только уже проверенные идентификаторы
(`src/backend/infrastructure/cdc/poll_backend.py:147-158`).

## Ограничения решения

- Имена с кавычками, пробелами, `$`, дефисом и другими спецсимволами
  отклоняются. Например, Oracle-имя `SYS.X$Y` не соответствует
  allowlist-регексу.
- Точная форма имени не проверяется по каталогу объектов БД: решение
  защищает от SQL-инъекции, но не от опечатки или отсутствующей таблицы.
- REST-слой пока не преобразует `ValueError` из `client.subscribe()` в
  4xx. В `create_subscription()` нет обработчика этого исключения
  (`src/backend/entrypoints/cdc/cdc_routes.py:50-68`), поэтому невалидное
  имя сейчас приводит к HTTP 500. Pydantic-валидатор на границе
  entrypoints — отдельная задача.
- `CDCSubscription` сама по себе не валидирует идентификаторы; безопасность
  обеспечивается вызывающими границами `CDCClient`, стратегий и
  `PollCDCBackend`.

## Альтернативы

### Вариант A: только экранировать имена кавычками (отклонён)

**Почему отклонён:** quoting меняется между диалектами и не даёт
простого доказательства, что произвольное имя безопасно. Строгий
allowlist проще проверять и аудировать.

### Вариант B: валидировать только в REST/Pydantic-модели (отклонён)

**Почему отклонён:** CDC-клиент вызывается не только из REST. Без
проверки в `CDCClient` и стратегиях недоверенное имя могло попасть в SQL
через другой путь.

### Вариант C: передать имена как bind-параметры (отклонён)

**Почему отклонён:** SQL bind-параметры не позволяют параметризовать
имя таблицы или колонки. Идентификатор остаётся частью SQL и требует
allowlist-проверки.

### Вариант D: оставить проверку только в одной стратегии (отклонён)

**Почему отклонён:** LogMiner, polling и `PollCDCBackend` строят разные
SQL. Единая проверка на входе подписки плюс повторная проверка у
исполнителей обеспечивает defence in depth.

## Последствия

### Позитивные

- SQL-инъекция через имена таблиц/колонок блокируется до выполнения
  запроса.
- `CDCClient.subscribe()` fail-fast: невалидная подписка не
  регистрируется.
- Политика одинакова для внешнего CDC-клиента, polling- и LogMiner-
  стратегий и `PollCDCBackend`.
- LogMiner получает дополнительный escape-слой для строковых литералов.

### Негативные

- Некоторые допустимые для СУБД идентификаторы с необычными
  спецсимволами придётся дополнить в allowlist.
- REST-ответ для невалидного имени сейчас не является семантическим 4xx.
- Валидация логически повторяется на нескольких границах; это намеренная
  защита от обхода одного из путей.

## Проверка после реализации

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/clients/external/cdc/test_strategies_identifier_validation.py \
  tests/unit/infrastructure/cdc/test_poll_backend_identifier_validation.py -q
```

## Связи с другими ADR

- [ADR-0112](0112-security-audit-status.md) — allowlist + escape как
  канонический defence-in-depth паттерн.
- [ADR-0284](0284-architectural-debt-resolution.md) — helper размещён в
  infrastructure без обратной зависимости от services.
