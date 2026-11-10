# ADR-0434 — Единый линтер DSL-YAML, error-лог загрузки workflow, экспорт примитивов устойчивости

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0398 (activity-имена), ADR-0424 (каталог шаблонов), ADR-0433 (линтер workflow-спецификаций)
* Затрагивает: `src/backend/dsl/cli/lint.py`, `tools/dsl_lint.py`, `src/backend/plugins/composition/workflow_setup.py`, `src/backend/core/api/__init__.py`, `docs/cookbooks/07-write-workflow-yaml.md`

## Контекст

1. В проекте было **три** линтера DSL-YAML: `tools/dsl_lint.py` (capability-aware, 302 LOC),
   `src/backend/dsl/cli/lint.py` (устаревший, 71 LOC) и `src/backend/dsl/cli/linter.DSLLinter`
   (другой уровень — `route.toml` + `*.dsl.yaml`, используется LSP и `dsl debug`).
2. `workflow_setup.py` логировал ошибку загрузки workflow как WARNING с обрезкой текста
   до 200 символов → битый workflow просто исчезал из приложения.
3. `core.api` не экспортировал примитивы устойчивости (`CircuitBreaker`, `Bulkhead`,
   `RateLimiter`, `with_retry`), хотя AGENTS.md заявлял «17 primitives».

## Решение

* Канон линтера — `src.backend.dsl.cli.lint` (бывший `tools/dsl_lint.py`);
  `tools/dsl_lint.py` — тонкая CLI-обёртка (tools → src). Дубли удалены.
* Ошибка загрузки workflow → `logger.error` с путём файла и полным текстом +
  сводка «N из M не загружено»; список доступен через
  `get_workflow_load_failures()`.
* `core.api` экспортирует примитивы устойчивости (lazy `__getattr__`).
* Cookbook 07 «Как написать workflow на YAML» (шаблон → правка → линт →
  dry-run → запуск → gotchas).

## Последствия

* Один линтер вместо трёх; `dsl lint`/`tools/dsl_lint.py` дают одинаковый результат.
* Битый workflow виден в логах (ERROR) и в диагностике.
* Расширения могут импортировать `CircuitBreaker`/`Bulkhead`/`with_retry` из `core.api`.
