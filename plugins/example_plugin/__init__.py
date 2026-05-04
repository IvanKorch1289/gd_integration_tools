"""Example plugin (Wave 4 / DoD).

Демонстрирует:

* регистрацию action `example.echo` через `on_register_actions`;
* repository hook `before_create` для `orders` через `@repository_hook`;
* override `get_by_id` для `orders` через `@override_method`;
* в perspective DSL — нет (этот пример минимален).

Манифест — `plugin.yaml`. В реальном дистрибутиве модуль регистрируется
через entry_point ``gd_integration_tools.plugins`` в `pyproject.toml`.
"""

from __future__ import annotations

from plugins.example_plugin.plugin import ExamplePlugin

__all__ = ("ExamplePlugin",)
