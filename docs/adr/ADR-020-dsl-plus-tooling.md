# ADR-020: DSL+ tooling — LSP + formatter + type-check

* Статус: accepted
* Дата: 2026-04-21
* Фазы: K1

## Контекст

Расширенный tooling для DSL: language server (LSP) для YAML-DSL, code
formatter, type-check интеграция с mypy (Protocol-based interfaces).

## Решение

1. LSP — публикуется как `gdi-dsl-language-server` через pip,
   интегрируется с VSCode, Neovim, JetBrains.
2. Formatter — `gdi dsl format` (обёртка над `ruamel.yaml`).
3. Type-check — dedicated mypy plugin, который валидирует `RouteBuilder`-
   chains (B1 mixins дают type-safe категории).

## Альтернативы

- **Полный custom DSL compiler**: overkill.

## Последствия

- Публикация LSP в PyPI — в H4 release stage.
