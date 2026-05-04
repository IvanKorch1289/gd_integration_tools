# Runbook — Plugin Install

Установка плагина (Wave 4 plugin system).

## Symptom
- Нужно подключить новый плагин (third-party или внутренний).
- Включить расширение DSL/processors/repository hooks.

## Cause
Расширение функциональности без изменения core.

## Resolution
1. Положить plugin-код в `plugins/<plugin_name>/` со структурой:
   - `plugin.yaml` (metadata: name, version, entry_points);
   - `__init__.py`;
   - `plugin.py` с `class Plugin(BasePlugin)`.
2. Smoke-проверка:
   ```bash
   uv run python tools/check_plugin_system.py
   ```
3. Регистрация в lifespan: см. `src/plugins/composition/lifecycle.py`.
4. Перезапуск приложения.

## Verification
- `/api/v1/actions/inventory` показывает actions плагина.
- `tools/check_plugin_system.py` exit 0.
- Метрика `plugin_loaded_total{name=...}` увеличилась.

## Rollback
1. Удалить директорию `plugins/<plugin_name>/`.
2. Убрать регистрацию из `lifecycle.py`.
3. Restart приложения.
4. Smoke-проверка `/actions/inventory`.
