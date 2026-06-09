# ADR-0108 — DI DSL для RouteBuilder / call_function / process_fn

* Статус: Accepted (Sprint 40 W1–W5, 2026-06-09)
* Связано с: PLAN.md V23 §S40; tutorial `docs/tutorials/15_dependency_injection.md`.

## Контекст

В проекте существует **фрагментированная** DI-система:

* `core/di/app_state_singleton` — хранит singleton'ы в `app.state`.
* `core/di/module_registry` — резолвит инфраструктурные модули по ключу.
* FastAPI `Depends()` — работает только внутри HTTP-request контекста.
* DSL-процессоры (`call_function`, `process_fn`) получают только
  `exchange` и `context`; зависимости резолвятся внутри функций через
  прямые импорты.

Это приводит к:
1. **Жёсткой связанности** — бизнес-функции импортируют инфраструктуру
   напрямую.
2. **Сложности тестирования** — нельзя подменить зависимость без
   `unittest.mock.patch` на модуль.
3. **Дублированию** — каждый плагин изобретает свой способ получить
   `DatabaseSessionManager` или `RedisClient`.

Цель Sprint 40 — создать **единый lightweight DI DSL** для всех
DSL-процессоров с минимальным overhead и без нарушения существующих
контрактов безопасности (whitelist, capability-gate, audit-log).

## Решение

### 1. Архитектура DI Core

```
src/backend/dsl/di/
├── types.py       — InjectMarker (frozen dataclass)
├── container.py   — Container (static resolver: factory → registry → app.state)
├── decorators.py  — @inject (авто-резолв параметров с InjectMarker default)
└── __init__.py    — публичный API: Container, inject, DIError, InjectMarker
```

**Container.resolve** — три механизма (по приоритету):
1. `InjectMarker.factory` — явная factory-функция.
2. `InjectMarker.key` → `module_registry.resolve_module(key)`.
3. `InjectMarker.key` → `app.state.<key>`.
4. (fallback) тип параметра → `_type_map` → registry/app.state.

### 2. Интеграция с RouteBuilder

Новый chainable модификатор `RouteBuilder.depends(*deps)`:

```python
builder.call_function("mod:fn").depends("db", ("logger", "logging.default"))
```

* `deps` — строки (имена параметров) или кортежи `(param_name, key)`.
* Применяется к последнему processor'у через `_last_processor_or_raise()`.
* Процессор должен иметь атрибут `_inject`.

### 3. Интеграция с CallFunctionProcessor

* `__init__` получает `inject: list[str] | None = None`.
* `process()` проверяет `fn.__inject_markers__` или `self._inject`.
* Если DI активен — вызывает `Container.resolve_signature(fn, exchange, context)`,
  мержит с `payload`, вызывает `fn(**kwargs)`.
* `to_spec()` сериализует `_inject` в YAML round-trip.
* `spec_schema` обновлён с полем `inject` (array of string | [string, string]).

### 4. Интеграция с call_function() builder-методом

```python
def call_function(self, ref, *, payload_from="body", result_property="function_result", inject=None)
```

Параметр `inject` прокидывается в `CallFunctionProcessor(..., inject=inject)`.

### 5. Безопасность

DI работает **поверх** существующих механизмов:
* Module whitelist (`plugin.toml::call_function_modules`) проверяется
  до импорта функции.
* Capability-gate (`function.call.<module>`) проверяется до вызова.
* Audit-log фиксирует результат вызова (success / error).

DI-резолв происходит **после** всех security-проверок.

## Альтернативы

| Альтернатива | За | Против | Решение |
|---|---|---|---|
| Использовать FastAPI `Depends()` | Знакомо разработчикам | Работает только в HTTP-request; не подходит для Kafka/Timer/CDC | Отклонено |
| Интегрировать `dependency-injector` (IoC-контейнер) | Полноценный IoC | Лишняя зависимость; избыточно для 80% декларативного DSL | Отклонено |
| Оставить ручные импорты | Просто | Жёсткая связанность; плохая тестируемость | Отклонено |
| **Собственный lightweight DI** | Контроль; ноль новых зависимостей; работает во всех DSL-контекстах | Нужно писать и поддерживать | **Принято** |

## Последствия

* **Позитивные:**
  * Единый механизм DI для всех DSL-процессоров.
  * Упрощение тестирования — `Container.register_type()` + mock.
  * Уменьшение coupling между business-logic (extensions/) и infrastructure.
  * Tutorial `15_dependency_injection.md` закрывает gap для неопытных
    разработчиков.

* **Риски:**
  * `Container` — глобальный singleton; возможны конфликты имён ключей.
    Митигация: namespace-конвенция (`clients.storage.redis`, `logging.default`).
  * DI-резолв в runtime добавляет небольшой overhead (~1–2 ms на вызов).
    Митигация: кэширование в `module_registry` + `app_state` уже Singleton.

## Ссылки

* Код: `src/backend/dsl/di/`, `src/backend/dsl/builders/base.py::depends()`,
  `src/backend/dsl/builders/integration_core.py::call_function()`,
  `src/backend/dsl/engine/processors/function_call.py`.
* Тесты: `tests/unit/dsl/di/`, `tests/unit/dsl/test_builder_chainable_modifiers.py`.
* Tutorial: `docs/tutorials/15_dependency_injection.md`.
