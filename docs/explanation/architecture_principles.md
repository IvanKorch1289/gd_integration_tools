# Архитектурные принципы

## Domain-agnostic ядро

Ядро `gd_integration_tools` не знает о бизнес-логике. Все
кредитные/банковские/внутренние процессы — в `extensions/<name>/`
(см. ADR R1.6 hybrid layout).

## 80% YAML / 20% Python

* DSL routes описываются декларативно в `routes/<name>/route.toml`;
* кастомные функции подключаются через `call_function('module:fn')`;
* Workflow описываются Pydantic-моделями + YAML-обёртка над Temporal.

## 3-tier auto-registration

Один handler через `@service_dsl(protocols=["all"])` автоматически
регистрируется в REST + SOAP + gRPC + GraphQL + MQ + WS + SSE + MCP +
MQTT + XML.

## Strict layer boundaries

* `entrypoints` → `services`, `schemas`, `core` (Protocols);
* `services` → `core`, `schemas`;
* `infrastructure` реализует `core` Protocols;
* `core` не импортирует `src/`.

Enforce: `tools/checks/check_layers.py` (см. `make layers`).

## См. также

* [Capability runtime](capability_runtime.md)
* [Tenancy model](tenancy_model.md)
