# Core DI: три реестра + `app_state_singleton`

Этот документ фиксирует каноническую модель dependency injection в ядре
(`src.backend.core`). Цель — устранить неоднозначность «куда
регистрировать / откуда доставать сервис» в `extensions/`, `services/`,
`entrypoints/` и `infrastructure/`.

## Три ортогональных реестра (не дублируют друг друга)

| Реестр | Модуль | Lookup | Когда использовать |
|---|---|---|---|
| `svcs_registry` | `core/svcs_registry.py` | type-based или name-based | Type-safe singleton-сервис: `register_factory(OrderService, factory)`, `get_service(OrderService)`. Thread-safe через `threading.Lock`. |
| `providers_registry` | `core/providers_registry.py` | `category + name` | Protocol-реализации с несколькими вариантами: `register_provider("llm", "openai", oai)`, `get_provider("llm", "ollama")`. Подходит для LLM/Notif/CDC/Memory backend'ов. |
| `module_registry` | `core/di/module_registry.py` | dotted-path → `importlib` | Static lookup для обхода AST layer-чекера: `resolve_module("infrastructure.workflow.factory")`. Scope enum: SINGLETON/SCOPED/TRANSIENT. Регистрация extensions через `register_extension_module`. |

Плюс отдельный паттерн:

| Паттерн | Модуль | Когда использовать |
|---|---|---|
| `app_state_singleton` | `core/di/app_state.py` | FastAPI `app.state` доступ из non-request контекстов (background tasks, lifecycle hooks). Decorator + lazy factory. |

## Правило выбора

1. **Один экземпляр сервиса на процесс** (DB session manager, Notifier,
   AIGateway) → `svcs_registry`.
2. **Несколько реализаций одного протокола** (LLM, NotificationChannel,
   MemoryBackend, CDCSource) → `providers_registry`.
3. **Нужен `importlib.import_module` для layer-bypass** (только для
   legacy compatibility) → `module_registry`.
4. **Нужен доступ к FastAPI app.state из background** → `app_state_singleton`.

## Composition root

`src/backend/plugins/composition/lifecycle.py` + `app_factory.py` —
единственное место, где все три реестра заполняются. Контракт:
никакой другой код не должен регистрировать сервисы в процессе
работы приложения (только при startup).

## Public API for extensions

Расширения импортируют только `src.backend.sdk` + `src.backend.core.api`
(см. AGENTS.md, V22 boundary). Прямой импорт из
`core.di.svcs_registry` / `core.di.providers_registry` / `core.di.module_registry`
НЕ предусмотрен и считается layer violation.

## Тест-override паттерн

```python
def test_with_fake_db(monkeypatch):
    from src.backend.core.svcs_registry import register_factory, get_service
    from src.backend.infrastructure.database import DatabaseSessionManager

    fake = FakeDB()
    register_factory(DatabaseSessionManager, lambda: fake, replace=True)
    # ... test logic ...
```

Параметр `replace=True` разрешает перезапись (по умолчанию — нет).
