# Dependency Injection (DI) для DSL-роутов

> Sprint 40 W3 — DI DSL Core.

Dependency Injection (DI) — это способ **автоматически подставлять зависимости**
(базу данных, кэш, логгер, внешний клиент) в функции-обработчики без
ручного импорта и создания объектов внутри кода.

Вместо того чтобы в каждой функции писать::

```python
from src.backend.infrastructure.db import get_db

def handler(payload):
    db = get_db()          # ручное создание
    db.execute(...)
```

DI позволяет объявить: *«мне нужна база данных»* — и система сама её подставит::

```python
from src.backend.dsl.di import Container, inject

@inject
async def handler(
    exchange: Exchange[Any],
    context: ExecutionContext,
    db: DatabaseSessionManager = Container.depends(),
) -> None:
    db.execute(...)        # db уже создан и передан автоматически
```

---

## Зачем DI в gd_integration_tools

1. **Разделение ответственности** — бизнес-логика не знает, как создавать
   инфраструктурные объекты.
2. **Тестируемость** — в тестах можно подменить зависимость на mock
   через `Container.register_type()` или `factory=`.
3. **Единообразие** — один механизм для `call_function`, `process_fn`,
   workflow-шагов и AI-агентов.
4. **Безопасность** — whitelist + capability-gate для `call_function`
   остаются неизменными; DI работает *поверх* них.

---

## Быстрый старт

### 1. Декорируй функцию `@inject`

```python
from src.backend.dsl.di import Container, inject

@inject
async def process_order(
    exchange: Exchange[Any],
    context: ExecutionContext,
    redis: RedisClient = Container.depends("clients.storage.redis"),
) -> dict[str, Any]:
    redis.set(f"order:{exchange.in_message.body['id']}", "pending")
    return {"status": "ok"}
```

### 2. Используй в RouteBuilder

```python
from src.backend.dsl.builder import RouteBuilder

route = (
    RouteBuilder("order.handler")
    .from_("http:POST /api/v1/orders")
    .call_function("extensions.orders.handlers:process_order")
    .depends("redis")                     # ← DI-модификатор (Sprint 40)
    .to("response", code=202)
    .build()
)
```

Или передай список зависимостей сразу в `call_function`::

```python
.call_function(
    "extensions.orders.handlers:process_order",
    inject=["redis", ("logger", "logging.default")],
)
```

### 3. YAML-эквивалент

```yaml
from:
  http:
    method: POST
    path: /api/v1/orders

steps:
  - call_function:
      ref: extensions.orders.handlers:process_order
      inject:
        - redis
        - - logger
          - logging.default

to:
  response:
    code: 202
```

---

## Три механизма резолва

Когда DI видит `Container.depends(...)`, он ищет реальное значение
в порядке приоритета:

| Приоритет | Механизм | Пример |
|-----------|----------|--------|
| 1 | **Factory** | `Container.depends(factory=lambda: MyStore())` |
| 2 | **Module registry** | `Container.depends("clients.storage.redis")` → `module_registry.resolve_module(...)` |
| 3 | **App state** | `Container.depends("reply_registry")` → `app.state.reply_registry` |
| 4 | **Convention (type_map)** | `Container.depends()` + `Container.register_type(RedisClient, "clients.storage.redis")` |

### Factory — полный контроль

```python
@inject
async def handler(
    exchange: Exchange[Any],
    store: OrderStore = Container.depends(factory=lambda: OrderStore(tenant_id="t1")),
) -> None:
    ...
```

### Module registry — стандартный способ

```python
# где-то в startup / plugin_loader
from src.backend.core.di.module_registry import register_module
register_module("clients.storage.redis", redis_client)

# в обработчике
@inject
async def handler(
    exchange: Exchange[Any],
    redis: RedisClient = Container.depends("clients.storage.redis"),
) -> None:
    ...
```

### App state — singleton'ы

```python
# в startup
app.state.reply_registry = ReplyRegistry()

# в обработчике
@inject
async def handler(
    exchange: Exchange[Any],
    registry: ReplyRegistry = Container.depends("reply_registry"),
) -> None:
    ...
```

### Convention-over-configuration (type_map)

Если не указывать ключ явно, DI попробует найти зависимость по **типу аннотации**::

```python
# регистрация (один раз при старте)
from src.backend.dsl.di import Container
Container.register_type(RedisClient, "clients.storage.redis")

# использование — ключ не нужен!
@inject
async def handler(
    exchange: Exchange[Any],
    redis: RedisClient = Container.depends(),   # ← ключ выведен из типа
) -> None:
    ...
```

---

## Chainable `.depends()` в RouteBuilder

Метод `.depends()` — модификатор последнего step, аналогичный
`.with_timeout()` / `.with_headers()`.

```python
route = (
    RouteBuilder("complex.handler")
    .from_("http:POST /api/v1/complex")
    .call_function("ext.handlers:step1")
    .depends("db")                         # ← db для step1
    .call_function("ext.handlers:step2")
    .depends("cache", ("audit", "audit.writer"))   # ← две зависимости для step2
    .to("response", code=200)
    .build()
)
```

Правила:
* `.depends()` можно вызывать только **после** процессора, поддерживающего
  инъекцию (`call_function`, `process_fn`).
* Можно передавать строки (имена параметров) или кортежи
  `(param_name, container_key)`.
* Если процессор уже имеет `inject=[...]`, `.depends()` **дополняет**
  список, а не перезаписывает.

---

## DI без `@inject` (explicit inject)

Не всегда удобно менять код функции. Можно указать зависимости
в `call_function` / `process_fn` декларативно::

```python
.call_function(
    "ext.handlers:legacy_fn",
    inject=["db", ("logger", "logging.default")],
)
```

В этом случае `CallFunctionProcessor` сам вызовет
`Container.resolve_signature(fn, exchange=..., context=...)` и подставит
значения в `kwargs`.

**Важно:** функция `legacy_fn` должна принимать параметры с именами,
совпадающими с именами в `inject` (или кортежами).

---

## Безопасность

DI **не отменяет** существующие механизмы безопасности `call_function`:

1. **Module whitelist** — модуль `ext.handlers` должен быть в
   `plugin.toml::call_function_modules` или `settings.call_function_modules`.
2. **Capability gate** — проверяется `function.call.<module>`.
3. **Audit log** — каждый вызов логируется.

DI работает *после* проверок: сначала whitelist/capability, потом
разрешение зависимостей, потом вызов функции.

---

## Сравнение с FastAPI Depends

| | FastAPI `Depends()` | gd_integration_tools `Container.depends()` |
|---|---|---|
| Контекст | HTTP-request | DSL-exchange (не только HTTP) |
| Registry | Встроенный router | `module_registry` + `app.state` |
| Декоратор | Не требуется (router сам инжектит) | `@inject` или explicit `inject=[...]` |
| Async | Полная поддержка | Полная поддержка |
| Типизация | `Depends(Callable)` | `Container.depends(key=...)` или type_map |

---

## Частые ошибки

### `DIError: Cannot resolve dependency`

Причина: ключ не найден ни в `module_registry`, ни в `app.state`.

Решение:
* Проверьте правильность ключа.
* Убедитесь, что модуль зарегистрирован через `register_module()`
  или singleton добавлен в `app.state`.
* Используйте `factory=` для быстрого fallback.

### `ValueError: depends() может использоваться только с ...`

Причина: `.depends()` вызван после процессора, который не поддерживает DI
(например, `.set_header()`).

Решение: вызывайте `.depends()` только после `.call_function()` или
`.process_fn()`.

### Функция получает `InjectMarker` вместо реального объекта

Причина: функция вызвана без `@inject` и без `inject=[...]` в DSL.

Решение: добавьте `@inject` или укажите `inject` в `call_function`.

---

## Следующие шаги

* Попробуйте `Container.register_type()` для часто используемых сервисов.
* Изучите `docs/adr/0107-di-dsl-for-routes.md` (Sprint 40 W5) для
  архитектурных деталей.
* Для сложных сценариев (scoped lifetime, фабрики с аргументами)
  используйте `factory=` или создайте кастомный processor.
