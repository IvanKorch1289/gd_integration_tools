# ADR-0399 — JSON-Schema процессоров в репозитории, каталог LSP-шагов и метрики workflow

* Статус: Accepted (2026-10-30, волна 20, кластер W2 — DX: схемы, LSP, метрики, запрет downgrade)
* Автор: coder-агент, кластер W2
* Связи: ADR-0058 (JSON-Schema процессоров), ADR-0369 (достижимость шагов из YAML),
  ADR-0395 (переключение движков workflow), ADR-0397 (каталог YAML-шагов)

---

## Контекст

Волна 20 закрыла остаточные дефекты кластера W2:

1. **Схемы процессоров не публиковались.** Цель `make schemas` отсутствовала
   (в `make/` были только `plugin-schema`/`route-schema`), каталог
   `docs/reference/schemas/processors` не создавался, а CLI
   `tools/dsl_export_schemas.py` ссылался на несуществующий путь.
2. **LSP-completion знал 55 шагов из 438.** `STEP_COMPLETIONS` в
   `tools/dsl_lsp/schema_completion.py` был захардкоженным списком и
   разъезжался с `RouteBuilder`.
3. **Каталог шагов не был синхронизирован с реестром `@processor`.** Часть
   процессоров не адресуема из YAML, а переименованные шаги
   (`print_pdf` → `rpa_pdf`, `wait_for_selector` → `rpa_wait_for`) получали
   сигнатурный каркас вместо реестровой JSON-Schema.
4. **Downgrade Temporal → pg_runner не был запрещён.** ADR-0395 обещает
   запрет в staging/prod, но `infrastructure/workflow/factory.py` не смотрел
   профиль; вызовы `kind="auto"` без профиля (`manage.py workflow cancel`)
   деградировали молча.
5. **Метрики workflow были объявлены, но не наполнялись.** В
   `infrastructure/observability/otel/setup.py` создавались инструменты, но
   ни одного `record` не было; в pg-runner не было метрик шага, ретрая и
   компенсации.

---

## Решение

### 1. Публикация схем

* В `make/codegen.mk` добавлена цель `schemas` —
  `python tools/dsl_export_schemas.py --output docs/reference/schemas/processors`.
* CLI сам создаёт каталог публикации (`mkdir(parents=True)`) до экспорта —
  каталог не обязан существовать в репозитории.
* В CI (`lint.yml`) шаг мягкий (`continue-on-error: true`): публикуемые
  файлы — артефакт, а не блокирующий гейт.

### 2. Каталог — источник истины для LSP

* `STEP_COMPLETIONS` строится из каталога
  `src.backend.dsl.builders.step_catalog` (все публичные методы
  `RouteBuilder`); curated-описания и snippet'ы из
  `_STATIC_STEP_COMPLETIONS` сохраняются как fallback и для известных шагов.
* `get_step_snippet()` при отсутствии curated-схемы добирает схему из
  каталога.

### 3. Синхронизация каталога с реестром

* Сопоставление «YAML-шаг ↔ процессор реестра» — **по классу процессора**
  (builder → AST → класс), а не по имени: имя в реестре может отличаться
  (`print_pdf` → `rpa_pdf`). Поэтому переименованные шаги получают
  **реестровую** JSON-Schema, а остальные — каркас по сигнатуре метода.
* Новые функции каталога: `step_registry_spec()`, `registry_only_steps()`,
  `yaml_step_for_registry_name()`; `catalog_coverage()` дополнена счётчиком
  `registry_only`.
* Линтер (`src/backend/dsl/cli/linter.py`) сообщает новым кодом
  `PROCESSOR_NOT_YAML_ADDRESSABLE`, если в YAML использовано имя процессора
  из реестра (`rpa_pdf` вместо `print_pdf`) или имя, не адресуемое из YAML
  вовсе.

### 4. Запрет downgrade вне dev

* Эффективный профиль определяется как аргумент `profile`, иначе —
  `APP_PROFILE` (`core.config.profile.get_active_profile`).
* В профилях `staging`/`prod` падение подключения к Temporal при
  `kind="auto"` больше не деградирует в pg_runner: выбрасывается
  `RuntimeError` с перечнем потерянных гарантий (replay / determinism /
  typed-query) и исходной ошибкой в `__cause__`.
* Явный выбор оператора (`kind="pg_runner"`, `kind="temporal"`) не
  меняется: это не downgrade.

### 5. Метрики pg-runner'а

* В `infrastructure/observability/otel/setup.py` добавлены инструменты и
  recorders: `workflow.step_duration` (ms), `workflow.step_retries`,
  `workflow.compensation_total`, `workflow.status` — через meter `gd.workflow`.
* `DurableWorkflowRunner` эмитит их на каждом шаге: длительность — по
  таймеру вокруг `execute_next`, ретраи — из номера попытки, компенсации —
  из события `compensated`, статус — при переходах
  succeeded/failed/paused/cancelled.
* Recorders best-effort: отсутствие OTel SDK не ломает исполнение.

---

## Альтернативы

* **Генерировать LSP-список из реестра `@processor`.** Отклонено: в YAML
  адресуемы публичные методы `RouteBuilder`, а не имена реестра; часть
  процессоров реестра (`memory_recall`, `redelivery_policy`) методами
  builder'а не представлена.
* **Оставить `make schemas` в `make/v11.mk`.** Отклонено: цель относится к
  публикации JSON-Schema процессоров (ADR-0058), а не к манифестам V11.
* **Запретить `pg_runner` в prod полностью.** Отклонено: ADR-0395 запрещает
  именно автоматическую деградацию; явный выбор оператора — осознанное
  решение и должно оставаться возможным.
* **Считать метрики в Prometheus-регистре.** Отклонено: дефект касался
  объявленных OTel-инструментов; эмиссия идёт через существующий OTel-слой,
  чтобы данные попадали в тот же OTLP-конвейер.

---

## Последствия

* **Позитивные**: схемы процессоров публикуются воспроизводимо; LSP
  предлагает все YAML-шаги; переименованные шаги валидируются по
  реестровой схеме; staging/prod не деградирует молча; метрики pg-runner'а
  видны в OTLP-конвейере.
* **Издержки**: импорт `tools.dsl_lsp.schema_completion` теперь поднимает
  каталог шагов (AST-разбор builder'а кэшируется); в CI добавлен мягкий
  шаг экспорта схем.
* **Совместимость**: curated-список LSP и схем сохранён как fallback;
  поведение `kind="auto"` в dev-профилях не изменилось; явный
  `kind="pg_runner"` работает во всех профилях.
* **Ограничение**: `kind="auto"` без профиля теперь следует `APP_PROFILE` —
  в окружении с `APP_PROFILE=dev_light` такой вызов выберет lite-temporal
  вместо temporal.

---

## Проверка

* `tests/unit/tools/test_dsl_export_schemas.py` — цель `make schemas`
  объявлена; экспорт создаёт каталог и валидные JSON-схемы (+ `index.json`).
* `tests/unit/tools/test_lsp_schema_completion.py` — completion покрывает
  весь каталог; snippet'ы валидны; статический список остался fallback'ом.
* `tests/unit/dsl/cli/test_step_catalog.py` — реестровая схема для
  `print_pdf`/`wait_for_selector`; `registry_only_steps()`;
  `yaml_step_for_registry_name()`.
* `tests/unit/dsl/cli/test_linter.py` — `PROCESSOR_NOT_YAML_ADDRESSABLE`.
* `tests/unit/infrastructure/workflow/test_workflow_backend_factory.py` —
  запрет downgrade в staging/prod и при `kind="auto"` без профиля.
* `tests/unit/infrastructure/observability/otel/test_workflow_metrics.py` —
  recorders пишут в OTel-инструменты; pg-runner эмитит все четыре метрики.
* `pytest tests/unit/dsl/cli tests/unit/tools/test_lsp_schema_completion.py
  tests/unit/tools/test_dsl_export_schemas.py tests/unit/core/workflow
  tests/unit/infrastructure/workflow tests/unit/infrastructure/observability` —
  зелёные (кроме pre-existing падений в кластере workflow, см. отчёт).
* `ruff check` по файлам кластера — чисто; `tools/config_audit.py --scope
  orphans` → 0; `tools/check_layers.py --strict` → 41 (baseline, новых нет);
  `tools/check_docstrings.py src --max-allowed 0` → 0.

---

## Связи

ADR-0058, ADR-0369, ADR-0395, ADR-0397.
