# How-To Guides

Решают **конкретную проблему**: «как сделать X» без обучения матчасти.

## Содержание

```{toctree}
:maxdepth: 1

01_add_processor
run_perf_locally
run_chaos_locally
sign_release
```

## Часто решаемые задачи

- [Написать кастомный процессор](01_add_processor.md) — регистрация через `@processor`
- [Запуск perf-тестов локально](run_perf_locally.md) — k6 + locust
- [Запуск chaos-тестов локально](run_chaos_locally.md) — fallback chains V15
- [Подписать релиз](sign_release.md) — cosign supply-chain V4
- Настроить capability-gate для плагина — см. `extensions/<name>/plugin.toml`
- Добавить Workflow через DSL — см. `dsl/workflow/`
