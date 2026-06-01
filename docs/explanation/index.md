# Explanation

Объясняет **почему**: контекст, trade-offs, мотивация архитектурных решений.

```{toctree}
:maxdepth: 1

architecture
architecture_principles
capability_runtime
tenancy_model
```

## Ключевые концепции

- [Архитектура системы](architecture.md) — слоистая архитектура и DSL dual-mode
- [Принципы архитектуры](architecture_principles.md) — V15 architectural decisions
- [Capability-runtime gate](capability_runtime.md) — V11.1 plugin contract
- [Модель multi-tenancy](tenancy_model.md) — TenantContext + per-tenant SLO/quotas
- Plugin-система и capability-gate — V11.1, R-V15-1
- Workflow-оркестрация через Temporal — ADR-045, R-V15-7
- AI Safety и workspace isolation — V22, R-V15-4
