# ADR-0058 — JSON-Schema Export для DSL Processors

* Статус: Accepted (Sprint 3, К3 W3, 2026-05-13)
* Связано с: V15 R-V15-2 (Routes), R-V15-12 (универсальная формула роута);
  PLAN.md V18.1 §S3 К3 W3 шаг 5; LSP integration roadmap (Sprint 6).

## Контекст

DSL поддерживает ~30 processor-типов (proxy, redirect, call_function,
dispatch_action, transform, choice, parallel, try_catch, saga, invoke_workflow,
policy, db_query_external, db_call_procedure, get_setting, validate_response,
crud_*, publish_event, notify_cascade, audit, sink_*, …) — каждый с
собственным набором параметров. Без JSON-Schema каталога:

* нет LSP-completion в YAML-редакторах;
* нет автогенерации docs (Sphinx ``dsl-reference`` page);
* нет валидации pipeline.dsl.yaml до runtime (errors at first dispatch);
* нет AsyncAPI/OpenAPI экспорта для downstream-консьюмеров.

## Решение

1. **JSON-Schema draft-07** — выбран draft-07 как baseline (vs draft-2020-12):
   максимальная совместимость с tooling (VS Code YAML extension, IntelliJ,
   AsyncAPI 2.x). Upgrade на draft-2020-12 — Sprint 7 (после VS Code 1.85+
   commit).

2. **Closed-set с extension hooks** — все ядерные processors экспортируют
   schema в ``schemas/processors/<name>.json`` (closed-set). Plugin-processors
   через ``@processor`` декоратор тоже экспортируются в
   ``schemas/processors/extensions/<plugin>/<name>.json``, но из отдельного
   manifest. Compose-schema (``schemas/route.toml.schema.json``) ссылается
   через ``$ref`` на оба.

3. **Semver per-processor** — каждая schema содержит ``"$id"`` с semver:
   ```json
   {
     "$schema": "http://json-schema.org/draft-07/schema#",
     "$id": "https://gd-integration-tools/schemas/processors/proxy/1.2.0",
     "title": "ProxyProcessor",
     "type": "object",
     ...
   }
   ```
   Breaking changes → major bump; новые optional fields → minor; doc/example
   правки → patch.

4. **Snapshot-кэш для LSP** — ``schemas/dsl_snapshot.json`` (aggregate)
   обновляется через ``tools/dsl/export_jsonschema.py`` (CI-gate). LSP
   читает один файл, не sweep'ит directory. Snapshot версионируется
   semver на ``aggregate``-уровне; breaking-changes к single processor
   bump'ит aggregate как major.

5. **Экспортер** — ``services/schema_registry/exporter_jsonschema.py``
   реализует:
   ```python
   def export_jsonschema(out_dir: Path) -> ExportReport:
       """Экспорт всех @processor + plugin processors в JSON-Schema files.

       Returns:
           ExportReport(total=N, new=M, changed=K, breaking=[...])
       """
   ```
   Запускается из ``make schemas`` + предкоммитный hook (Sprint 5).

6. **AsyncAPI / OpenAPI bridging** — schemas через
   ``services/schema_registry/asyncapi_bridge.py`` маппятся в
   AsyncAPI 2.6 channels (для event-driven routes) и OpenAPI 3.1 paths
   (для REST routes). Sprint 4 deliverable.

## Последствия

* `+` LSP-completion в YAML-редакторах без custom plugin (стандартное
  ``yaml-language-server`` + ``yaml.schemas``).
* `+` Pre-runtime валидация: ``pipeline.dsl.yaml`` ошибки ловятся до boot.
* `+` Sphinx auto-generates ``dsl-reference`` page из schemas (Sprint 7).
* `+` Semver per-processor — explicit breaking-change tracking.
* `−` Closed-set + extension model требует двух manifest-форматов; усложняет
  plugin authoring (mitigation: codegen-template).
* `−` Snapshot-кэш требует ручного pre-commit hook; не атомарно с code
  changes (Sprint 5 — pre-commit auto-regenerate).
* `−` AsyncAPI 2.6 limitations: нет первоклассного support для saga (Sprint 4
  custom extension).

## Альтернативы рассмотрены и отклонены

* **TypeScript / Zod schemas** — отклонено: Python-нативность ProcessorRegistry
  + Pydantic делает Python-вариант на порядок дешевле.
* **OpenAPI 3.1 как primary** — отклонено: schema reuse между protocols
  затруднителен; AsyncAPI bridging требует двойного maintenance.
* **GraphQL SDL** — отклонено: out-of-scope для DSL (GraphQL — Wave 1.4
  separate adapter).

## CI gates

* ``make schemas`` — экспорт + validate.
* ``tools/dsl/export_jsonschema.py --check`` — fails если snapshot устарел.
* ``tests/services/schema_registry/test_export*.py`` — round-trip:
  processor → schema → validate против sample YAML.

## Roadmap

* **Sprint 3 W3 (текущий)** — экспортер + snapshot-кэш для closed-set
  (≥ 16 processors).
* **Sprint 4** — AsyncAPI 2.6 / OpenAPI 3.1 bridging; semver enforcement.
* **Sprint 6** — LSP plugin для VSCode (yaml-language-server config preset).
* **Sprint 7** — Sphinx ``dsl-reference`` auto-page; draft-2020-12 upgrade.
