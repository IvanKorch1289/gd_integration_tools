# Architecture

Схема слоёв, канонические карты модулей и аудиты репозитория.

```{toctree}
:maxdepth: 1

canonical-module-map
workflow_architecture
logging
memory_structure
repository-navigation-audit
STREAMLIT_AUDIT_2026-06-06
```

## Страницы

- [Canonical Module Map](canonical-module-map.md) — «ответственность →
  канонический каталог → публичный вход» (актуально на 2026-09-11).
- [Workflow-архитектура](workflow_architecture.md) — слои workflow-подсистемы:
  `core/workflow` → `dsl/workflow` → `infrastructure/workflow` +
  `services/workflows`.
- [Logging](logging.md) — логирование: провайдеры, форматирование, PII.
- [Memory structure](memory_structure.md) — память агентов и её слои.
- [Repository navigation audit](repository-navigation-audit.md) — аудит
  навигации по репозиторию (метод и evidence).
- [Streamlit audit 2026-06-06](STREAMLIT_AUDIT_2026-06-06.md) — аудит
  Streamlit-портала.
