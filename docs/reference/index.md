# Справочник (Reference)

Справочник содержит точное техническое описание системы.
Он предполагает, что читатель уже знает, что ищет.

## Содержание

```{toctree}
:maxdepth: 1

schemas/index
capabilities
```

## API Reference

Автоматическая генерация API Reference из docstrings (`sphinx-autoapi`)
настроена в `docs/conf.py` (S34 W1). Сгенерированная документация доступна
через `make docs` → `docs/_build/html/`.

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
