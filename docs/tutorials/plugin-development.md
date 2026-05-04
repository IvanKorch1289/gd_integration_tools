# Tutorial — Plugin Development

Цель: написать собственный плагин по стандарту Wave 4.

## Что вы узнаете
- Структуру `plugins/<name>/`.
- Как определить ActionHandler через декоратор.
- Как добавить repository hook + override.

## Шаги

1. `plugins/my_plugin/plugin.yaml`:
   ```yaml
   name: my_plugin
   version: 0.1.0
   entry_points:
     plugin: my_plugin.plugin:Plugin
   ```
2. `plugins/my_plugin/plugin.py`:
   ```python
   from src.core.interfaces.plugin import BasePlugin

   class Plugin(BasePlugin):
       name = "my_plugin"
       version = "0.1.0"

       async def setup(self, ctx):
           ctx.action_registry.register("my.echo", self._echo)

       async def _echo(self, payload):
           return {"echo": payload}
   ```
3. Запустите `tools/check_plugin_system.py` — должен зарегистрировать action.

## Проверка
- `make actions | grep my.echo`.
- `curl /api/v1/invocations/invoke -d '{"action":"my.echo","payload":{"a":1}}'`.

## Next steps
- [Plugin install runbook](../runbooks/plugin-install.md)
- [DSL extension](write-dsl-route.md)
