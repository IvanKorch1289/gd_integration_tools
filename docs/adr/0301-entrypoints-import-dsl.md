# ADR-0301: entrypoints → dsl (санкционированное направление импортов)

- Статус: accepted
- Дата: 2026-09-08
- Контекст: Prod-Readiness метрика №5 (layer allowlist 37 → ≤15, ADR по
  каждому матричному изменению — правило governance в `tools/check_layers.py`)

## Контекст

Матрица слоёв (`ALLOWED` в `tools/check_layers.py`) не разрешала
`entrypoints → dsl`. Фактически entrypoints УЖЕ используют dsl как
исполнимое ядро (7 записей allowlist, все существующие файлы):

| Файл | Что импортирует | Зачем |
|------|-----------------|-------|
| `entrypoints/api/v1/endpoints/processors_catalog.py` | `dsl.builder`, `dsl.engine.processors` | каталог процессоров = интроспекция DSL-реестра |
| `entrypoints/mcp/mcp_server/tools_convert.py` | `dsl.engine.processors.converters` | MCP-инструменты = exposure DSL-процессоров |
| `entrypoints/mcp/mcp_server/tools_template.py` | `dsl`, `dsl.templates_library` | MCP-шаблоны = библиотека DSL-шаблонов |
| `entrypoints/webhook/handler.py` | `dsl.codec.json`, `dsl.engine.processors.scraping` | webhook-обработка через DSL-процессоры |

## Решение

1. `ALLOWED["entrypoints"] += {"dsl"}` — Camel/Airflow-семантика: adapters
   (entrypoints) управляют исполнением DSL-маршрутов. DSL — мета-слой,
   оркестрирующий backend (см. комментарий S65 W4 в матрице); направление
   `entrypoints → dsl` — потребление движка, а не нарушение слоёв.
2. Встречное направление `dsl → entrypoints` уже разрешено матрицей
   (`"dsl": {..., "entrypoints", ...}`); циклическая связка признаётся
   осознанной (DSL регистрирует обработчики, entrypoints их вызывают).
3. Governance: новые импорты `entrypoints → dsl.*` НЕ требуют записей в
   allowlist; нарушение остаётся для `entrypoints → dsl`-обходов слоёв
   (например, импорт infrastructure-модулей через dsl).

## Последствия

- Allowlist сокращается на 7 записей (21 → 14, цель ≤15 достигнута).
- `check_layers.py` остаётся fail-CLOSED для всех прочих направлений.
- Риск роста связности entrypoints↔dsl ограничен тем, что dsl публичная
  поверхность стабилизирована (RouteBuilder/ProcessorRegistry/templates).

## Связанные

- ADR-0284 (services/entrypoints → infrastructure), ADR-0286
  (infrastructure → services), AGENTS.md «Архитектура — слои» (V22).
