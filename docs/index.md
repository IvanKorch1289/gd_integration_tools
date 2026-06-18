# gd_integration_tools

Universal domain-agnostic integration platform (Python 3.14+, Apache-Camel/Airflow-style).

**Public API**: at subpackage level (`src.backend.core`, `src.backend.services`, `src.backend.dsl`, `src.backend.entrypoints`).

## Quick Links

- [Architecture](ARCHITECTURE.md)
- [Domain DSL](dsl/index.md) — RouteBuilder + WorkflowBuilder
- [AI Platform](ai/index.md) — AIGateway + PydanticAI + MultiAgent
- [ADRs](adr/index.md) — 190+ Architecture Decision Records

## Layers

```
src/frontend/  →  src/backend/entrypoints/  →  src/backend/services/  →  src/backend/infrastructure/
                                                       ↓
                                                  src/backend/core/  (interfaces, DI)
```

## Status (S164)

| Domain | Status | Notes |
|---|---|---|
| DSL builders | ✅ | 18 processors, 13 mixins, fluent API |
| AI Gateway | ✅ | 9-step pipeline, SkillRegistry |
| Workflows | ✅ | LiteTemporal + Temporal |
| Auth facade | ✅ | S164 W35 (JWT/API-key/OAuth2) |
| Storage facade | ✅ | S164 W37 (Rule 1) |
| Cache facade | 🟡 | S164 W38 pending |
| External HTTP | ✅ | httpx + purgatory CB + tenacity |
| CDC | 🟡 | Polling + Listen/Notify OK, Debezium scaffold |
| Agent isolation | 🟡 | E2B sandbox scaffold |
| Notifications | 🟡 | Email only, Telegram/Push scaffold |

See [ADRs](adr/index.md) for detailed decisions.