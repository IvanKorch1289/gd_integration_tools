# gd_integration_tools

Universal domain-agnostic integration platform (Python 3.14+, Apache-Camel/Airflow-style).

**Public API**: at subpackage level (`src.backend.core`, `src.backend.services`, `src.backend.dsl`, `src.backend.entrypoints`).

## Diátaxis toctree

```{toctree}
:maxdepth: 2
:caption: Documentation
:titlesonly:
tutorials/index
how-to/index
reference/index
explanation/index
```

## Quick Links

- [Architecture](ARCHITECTURE.md)
- [Domain DSL](dsl/index.md) — RouteBuilder + WorkflowBuilder
- [AI Platform](ai/index.md) — AIGateway + PydanticAI + MultiAgent
- [Workflows](workflows/index.md) — контракт workflow-подсистемы и схема состояний
- [Owner-задачи и известные ограничения](roadmap/OWNER_TASKS.md) — сводка
  позиций, требующих владельца
- [ADRs](adr/INDEX.md) — 400 Architecture Decision Records

## Layers

```
src/frontend/streamlit_app/  ─►  src/backend/entrypoints/  ─►  src/backend/services/
        │                              (REST/SOAP/gRPC/         (core[5-7],
        │                               GraphQL/WS/SSE/          ai, integrations,
        │                               MQTT/MCP/CDC/...)       ops, execution,
        │                                                        plugins, ...)
        │                                                        │
        ▼                                                        ▼
    public API only                                     src/backend/core/ (Protocols,
                                                         interfaces, di, tenancy,
                                                         plugin_runtime, auth, ai,
                                                         net[WAF], messaging, scaling)
                                                                ▲
                                                                │ контракты
                                                                ▼
                                                 src/backend/infrastructure/ (db, cache,
                                                         storage, messaging, search,
                                                         audit, sources, sinks, repos,
                                                         resilience, observability,
                                                         secrets[Vault],
                                                         workflow[Temporal+Lite])
                                                                ▲
                                                                │ (через registries)
                                                                ▼
                                                 src/backend/dsl/ (route/, workflow/,
                                                         service/, contracts/, engine,
                                                         blueprints/[10 patterns R2])
```

Бизнес-логика — только в `extensions/<name>/` (плагины с `plugin.toml`).

## Status

Источник правды по состоянию проекта — не этот файл, а:

- [`roadmap/PROD_READINESS_GAPS.md`](roadmap/PROD_READINESS_GAPS.md) — открытые
  позиции прод-готовности с владельцами;
- [`roadmap/OWNER_TASKS.md`](roadmap/OWNER_TASKS.md) — реестр owner-задач и
  известных ограничений (сводка по волнам);
- [`STATUS.md`](STATUS.md) — проверенный срез: реальные прогоны, HTTP-контракт,
  найденные дефекты;
- [`CURRENT_STATUS.md`](CURRENT_STATUS.md) — автогенерируемый срез
  (CI-артефакты, hard gates);
- `README.md` (корень репозитория) — блок «Текущие метрики» генерируется
  из кода (`tools/generate_current_metrics.py --check` — CI-гейт).

Числовые метрики (actions, OpenAPI paths, тесты, layer baseline) намеренно
не продублированы здесь: они живут в README и проверяются гейтом, чтобы
индекс не расходился с кодом.