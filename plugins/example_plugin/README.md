# example_plugin

Минимальный демо-плагин Wave 4 (Roadmap V10) для подтверждения DoD
plugin-системы:

- Регистрирует action `example.echo`.
- Репозиторий `orders` получает audit-hook на `before_create`.
- Метод `orders.get_by_id` подменяется stub-ответом.
- Никаких изменений в `src/` не требуется.

## Загрузка

In-tree (без `pip install`):

```python
from src.services.plugins import get_plugin_loader

loader = get_plugin_loader()
await loader.load_from_path("plugins/example_plugin")
```

Через entry_points (для отдельного дистрибутива) — добавить в свой
`pyproject.toml`:

```toml
[project.entry-points."gd_integration_tools.plugins"]
example_plugin = "plugins.example_plugin.plugin:ExamplePlugin"
```

И вызвать `loader.discover_and_load()`.
