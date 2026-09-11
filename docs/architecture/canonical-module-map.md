# Canonical Module Map — 2026-09-11

> Сопутствует `repository-navigation-audit.md` (метод и evidence там).
> Это карта «ответственность → канонический каталог → публичный вход».
> Каждый вход проверен на текущем HEAD; не-канонические алиасы помечены.

## Ответственность → куда класть код

| Ответственность | Канонический каталог | Публичный вход | Не-канонические алиасы (не использовать) |
|---|---|---|---|
| Public API facade для extensions | `src/backend/core/api/` | `from src.backend.core.api import ...` | `core/facades.py` (compat-shim, DEPRECATE) |
| Контракты/Protocols/DTO | `src/backend/core/<domain>/` | Protocol + Fake в том же пакете (ADR-045 модель) | — |
| Конкретные клиенты/адаптеры | `src/backend/infrastructure/` | через DI-провайдеры `core/di/providers/` | прямые импорты из core |
| Application/use-case слой | `src/backend/services/<domain>/` | фасады домена | бизнес-логика в core (запрещено) |
| Протоколы (REST/GraphQL/gRPC/SOAP/WS/SSE/Webhook/MQTT/MCP/CDC/…) | `src/backend/entrypoints/<protocol>/` | регистрация в `plugins/composition/app_factory.py` | — |
| ASGI middleware | `src/backend/entrypoints/middlewares/` | `build_default_registry()` в `setup_middlewares.py` | ad-hoc `add_middleware` вне registry |
| DSL-процессоры | `src/backend/dsl/engine/processors/` | `@processor` / `ProcessorRegistry` | `dsl/processors/` (агентные паттерны — отдельная роль, консолидация запланирована) |
| DSL-роуты (декларативные) | `routes/<name>/` | `route.toml` + `*.dsl.yaml` | — |
| Бизнес-плагины | `extensions/<name>/` | `plugin.toml` + `BasePlugin` из `core.api` | корневой `plugins/` (legacy `plugin.yaml`) |
| Composition root | `src/backend/plugins/composition/` | `create_app()` → `src/backend/main.py` | — |
| AI: контракты/Safety | `src/backend/core/ai/` | `AIFsFacade`, workspace-manager, LLM gateway | `src/backend/ai/` (stub-прослойка, CONSOLIDATE) |
| AI: RAG/tools/guardrails | `src/backend/services/ai/` | `tools/registry.py`, `rag_service/` | — |
| MCP-сервер | `src/backend/entrypoints/mcp/` | `/mcp` mount (feature-flag, default OFF) | — |
| Workflow (durable) | контракты `core/workflow/`; runtime `dsl/workflow/`; бэкенды `infrastructure/workflow/` | Protocol+Fake → factory | — |
| CLI (manage/gdi) | `src/backend/dsl/cli/`, `manage.py` | `make`-таргеты, `manage.py <cmd>` | — |
| Тестовые утилиты | `testkit/` + `gd_integration_tools.testkit.*` | pytest11 entry-point | — |
| SDK (stable public API) | `src/backend/sdk/` | `src.backend.sdk` re-exports | корень `sdk/` не существует — не создавать |
| Документация evergreen | `docs/<тип>/` | mkdocs nav | `docs/audit`, `docs/roadmap` — только датированные снапшоты |

## Порядок чтения кода (onboarding path)

```text
src/backend/main.py (1 строка: app = create_app())
  → plugins/composition/app_factory.py (регистрация протоколов/middleware)
    → entrypoints/<protocol>/ (dispatch_action → ActionDispatcher)
      → services/execution/ (invoke modes)
        → dsl/engine/ (pipeline/processors)
          → infrastructure/* (через DI-провайдеры)
```
