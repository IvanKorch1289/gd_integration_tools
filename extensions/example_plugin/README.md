# example_plugin (V11 reference)

Minimal in-tree demo-plugin для формата `extensions/<name>/` (V11).
Используется как:

- reference-имплементация ADR-042 (`plugin.toml` schema);
- smoke-fixture для `PluginLoaderV11`
  (`src/services/plugins/loader_v11.py`);
- иллюстрация декларации capabilities из ADR-044.

## Что внутри

- `plugin.toml` — манифест V11 (name / version / requires_core /
  entry_class / capabilities / provides).
- `plugin.py` — `ExamplePlugin(BasePlugin)`: один action
  `example.echo`, который возвращает payload без изменений.

## Как загружается

`PluginLoaderV11` сканирует `extensions/*/plugin.toml`, вызывает
`load_plugin_manifest(path)` (см. `src/services/plugins/manifest_v11.py`),
проверяет `requires_core` через `is_compatible_with_core(...)`, проводит
capability-allocation и инстанцирует `entry_class`. Далее вызываются
lifecycle-хуки `BasePlugin`: `on_load` → `on_register_actions` →
`on_shutdown`.

## Связанные ADR

- [ADR-042 — `plugin.toml` schema](../../docs/adr/ADR-042-plugin-toml-schema.md)
- [ADR-044 — Capability vocabulary](../../docs/adr/ADR-044-capability-vocabulary.md)

Legacy Wave-4.4 reference (entry_points + `plugin.yaml`) остаётся в
`plugins/example_plugin/` до удаления YAML-shim'а.
