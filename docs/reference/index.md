# Справочник (Reference)

Справочник содержит точное техническое описание системы.
Он предполагает, что читатель уже знает, что ищет.

## Содержание

```{toctree}
:maxdepth: 1
```

## API Reference

> Автоматическая генерация API Reference из docstrings (`sphinx-autoapi`)
> запланирована в отдельной Wave (требует cleanup всех публичных docstrings).
> До этого момента данный раздел является placeholder.

## DSL-спецификации

- `route.toml` — манифест маршрута (R-V15-2)
- `plugin.toml` — манифест плагина (R-V15-1)
- `*.dsl.yaml` — шаги маршрута (R-V15-12)

## JSON-Schema каталог

Схемы экспортируются командами:

```bash
make plugin-schema   # plugin.toml JSON-Schema → docs/reference/schemas/
make route-schema    # route.toml JSON-Schema → docs/reference/schemas/
```

## Capability vocabulary

```bash
make capability-catalog  # → docs/reference/capabilities.md
```
