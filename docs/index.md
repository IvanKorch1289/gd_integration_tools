# gd_integration_tools

Apache Camel-inspired интеграционная шина для банковского приложения.
Реализует DSL-builder маршрутов, 150+ готовых процессоров и единый
`ActionHandlerRegistry`, через который сервисы доступны из REST, очередей,
MCP и Prefect-тасков без модификаций.

## Разделы

```{toctree}
:maxdepth: 2
:caption: Руководства

QUICKSTART
ARCHITECTURE
DEVELOPER_GUIDE
DSL_COOKBOOK
PROCESSORS
AI_INTEGRATION
RPA_GUIDE
CDC_GUIDE
DEPLOYMENT
EXTENSIONS
```

```{toctree}
:maxdepth: 1
:caption: API reference

api/index
```

## Сборка

```bash
cd docs && make html
# результат: docs/_build/html/index.html
```

## Основные концепции

* **Exchange** — контейнер сообщения (in/out + properties + headers).
* **Processor** — единица работы, реализует `async process(exchange, ctx)`.
* **Pipeline** — упорядоченный список процессоров с метаданными.
* **RouteBuilder** — fluent-API для описания pipeline.
* **Action** — именованная бизнес-операция в `ActionHandlerRegistry`.
