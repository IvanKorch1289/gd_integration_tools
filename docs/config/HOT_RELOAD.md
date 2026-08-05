# Hot-Reload Configuration

> **Состояние на 2026-08-05: механизм существует, но для YAML profiles не подключён.**
> Документ описывает что есть, что работает, и какой gap остался.

## Архитектура

```
  ┌─────────────────────�         ┌──────────────────────┐
  │  .env / configs/*   │  watch  │ ConfigHotReloader    │
  │  (файлы)            │────────►│ (watchfiles.awatch)  │
  └─────────────────────┘         └─────────┬────────────�
                                             │ debounce 500 ms
                                             ▼
                              ┌──────────────────────────�
                              │ ReloadCallback registry │
                              └─────────┬────────────────┘
                                        │ вызывает по порядку
                                        ▼
                          pydantic-settings @lru_cache → reload()
                          LLM/cache/feature-flags → re-init
```

**Ключевые компоненты:**

| Компонент | Путь | Роль |
|-----------|------|------|
| `ConfigHotReloader` | `src/backend/core/config/hot_reload.py` | Singleton watcher + callback registry |
| `get_hot_reloader()` | то же | Возвращает singleton |
| `trigger_reload(reason)` | то же | Ручной триггер (admin endpoint + read-only FS) |
| Admin endpoint | `src/backend/entrypoints/api/v1/endpoints/admin.py:189` | `POST /admin/config/reload` |

## Что работает

- **API горячей перезагрузки** — `ConfigHotReloader` корректно дебаунсит, вызывает
  callback'и последовательно (без гонок), логирует ошибки и не падает на них.
- **Ручной триггер** — `POST /admin/config/reload` всегда работает; используется
  для read-only FS (контейнеры без inotify).
- **Disable в prod** — `feature_flags.prod_hot_reload_disable` (env: `FEATURE_PROD_HOT_RELOAD_DISABLE`,
  default `True`) при `APP_PROFILE=prod` отключает watcher, оставляя только ручной
  триггер (см. `src/backend/core/config/features/sprint19_ai.py:109`).
- **Тесты** — `tests/unit/core/config/test_hot_reload.py` покрывает singleton + callbacks.

## Что НЕ подключено (известный gap)

`grep -rn "reloader.watch" src/ tests/` показывает **только docstring-примеры**
в `src/backend/core/config/hot_reload.py:39-41`:

```python
reloader = get_hot_reloader()
reloader.watch(Path(".env"))
reloader.watch(Path("configs/routes.yaml"))
```

В production-коде **ни один файл из `config_profiles/*.yml` НЕ зарегистрирован
через `reloader.watch(...)`**. Это означает:

- Изменение `config_profiles/base.yml`, `dev.yml`, `dev_light.yml`, `staging.yml`,
  `prod.yml` **не приводит** к автоматическому reload'у.
- Для применения изменений в YAML-профилях требуется **рестарт процесса** или
  ручной `POST /admin/config/reload`.
- Документация `docs/config/SETTINGS_GUIDE.md:64-72` описывает hot-reload для
  YAML как работающий, что **противоречит реальности** — нужно исправить в
  следующем спринте.

## TODO (Sprint 37+)

```bash
# 1. Verify gap
grep -rn "reloader.watch" src/ tests/

# 2. Wire YAML profiles в startup hook
#    src/backend/plugins/composition/lifecycle/startup.py
#    → добавить вызовы:
reloader.watch(Path("config_profiles/base.yml"))
reloader.watch(Path("config_profiles/dev.yml"))   # or active profile

# 3. Перевести feature-flag `feature_flags.route_loader_hot_reload`
#    в default=True после shadow-mode в staging.

# 4. Update docs/config/SETTINGS_GUIDE.md §"Hot-reload (D-rule)"
#    чтобы описание соответствовало коду.
```

## Безопасность

- В production (`APP_PROFILE=prod`) watcher **выключен по умолчанию** —
  изменения конфигов требуют деплоя (явная операционная процедура).
- При `APP_PROFILE=dev/dev_light/staging` watcher включён; dev-сервер
  перезагружает settings без рестарта процесса.
- Ошибка callback'а логируется, но **не останавливает** watcher — другие
  подписчики продолжат получать reload-события.

## See also

- `src/backend/core/config/hot_reload.py` — реализация
- `src/backend/core/config/features/sprint19_ai.py:109` — `prod_hot_reload_disable` flag
- `src/backend/entrypoints/api/v1/endpoints/admin.py:189` — admin endpoint
- `tests/unit/core/config/test_hot_reload.py` — unit-тесты
- `docs/config/SETTINGS_GUIDE.md` — общий guide по настройкам (требует sync после Sprint 37)
