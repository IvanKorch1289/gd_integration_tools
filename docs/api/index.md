# API Reference

Канонические публичные входные точки (mkdocstrings-handler настроен в
`mkdocs.yml`, `paths: [src]`; разделы ниже можно развернуть директивами
`::: <module>` при необходимости).

| Входная точка | Модуль | Назначение |
|---|---|---|
| Public API facade | `src/backend/core/api/` | Единственный supported импорт для extensions |
| SDK | `src/backend/sdk/` | Stable public API (re-exports) |
| Task registry | `src/backend/core/utils/task_registry.py` | Фоновые задачи + graceful shutdown |
| Protocols/contracts | `src/backend/core/<domain>/` | Protocol + Fake (ADR-045 модель) |

Карту «ответственность → каталог → вход» см.
[canonical-module-map.md](../architecture/canonical-module-map.md).
