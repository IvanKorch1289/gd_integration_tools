# Архитектура системы

## Слоистая архитектура

`gd_integration_tools` построен на строгой слоистой архитектуре Clean Architecture.
Каждый слой имеет чётко ограниченные зависимости:

```text
entrypoints  →  services  →  core  (Protocols)
                                ↑
                        infrastructure
```

**Правило**: слои могут импортировать только нижележащие; `core` не импортирует
ничего из `src/` (только stdlib + Protocols). Нарушения проверяются через
`make check-layers` (`tools/checks/check_layers.py`).

## DSL Dual-Mode Principle

DSL поддерживает два равноправных способа описания маршрутов.

### Python — Camel-style fluent API

```python
RouteBuilder("my_route") \
    .from_("http:POST /api/v1/data") \
    .call_function("extensions.myapp.normalizer:apply") \
    .validate_response(schema="MySchema", on_error="dlq") \
    .to("response", code=202)
```

### YAML — декларативные шаги

```yaml
from:
  http:
    method: POST
    path: /api/v1/data

steps:
  - call_function:
      ref: extensions.myapp.normalizer:apply
  - validate_response:
      schema: MySchema
      on_error: dlq

to:
  response:
    code: 202
```

Оба подхода дают идентичный результат и поддерживаются одновременно.
Один JSON-Schema каталог экспортирует обе спецификации (R1).

## Plugin-система (V11.1)

Плагины живут в `extensions/<name>/` и декларируют capability через `plugin.toml`.
Доступ к ресурсам (БД, HTTP, FS) осуществляется исключительно через
capability-checked фасады. Нарушение → `CapabilityDeniedError` + audit-event.

## Принцип 80/20

80% конфигурации — декларативно через YAML/TOML.
20% кастомной логики — обычные Python-функции в `extensions/<name>/functions/`,
подключаемые через `call_function('module:fn')`.
