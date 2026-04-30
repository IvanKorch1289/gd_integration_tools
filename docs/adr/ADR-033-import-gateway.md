# ADR-033: ImportGateway (W24)

- **Статус:** accepted
- **Дата:** 2026-04-30
- **Фаза:** Wave-E-W24
- **Автор:** crazyivan1289

## Контекст

В проекте было два дублирующих стэка importer'ов:

1. `src/tools/schema_importer/` (sync, файловый) — `SchemaImporter.from_openapi(path)`
   генерирует Pydantic модели + YAML routes на диск (~620 LOC).
2. `src/dsl/importers/` (async, in-memory) — `OpenAPIImporter.import_spec(spec)`
   возвращает `ImportedRoute[]`, экспортирует actions `openapi.import` /
   `openapi.preview` / `openapi.list_imported` (~455 LOC).

Оба покрывали OpenAPI и Postman — без WSDL. Дублирование нарушало
Правило 13.2 (Gateway-консолидация). План W24 требовал создание
`ImportGateway` как единой точки.

Дополнительно ритуал Правила 8 (4 субагента) выявил:
- секреты Postman environments попадали в `connector_configs.config`
  открытым текстом;
- при reimport orphan operation_id оставались в Mongo;
- идемпотентность импорта в плане заявлена, но не реализована.

## Рассмотренные варианты

- **Вариант 1 — три standalone функции (без ABC).** Простое решение,
  меньше кода. ❌ Нарушает Правило 13.2 (Gateway требуется для 2+
  backends), не унифицирует контракт.
- **Вариант 2 — ABC + Registry (по аналогии с SourceRegistry).**
  Полный паттерн W23. ❌ Лишний слой: ImportGateway — stateless
  операция parse-and-convert, нет долгоживущих instances для lookup
  по id.
- **Вариант 3 — ABC + factory с single dispatch.** ✅ Минимальный
  необходимый набор: Protocol + 3 backends + factory + ImportService
  поверх. Принят.

## Решение

Принят **Вариант 3**:

- `core/interfaces/import_gateway.py` — Protocol `ImportGateway`,
  `ImportSourceKind` enum (postman/openapi/wsdl), dataclass
  `ImportSource`.
- `core/models/connector_spec.py` — `ConnectorSpec`, `EndpointSpec`,
  `AuthSpec`, `SecretRef`.
- `infrastructure/import_gateway/{postman,openapi,wsdl}.py` —
  3 backend; lazy import `zeep`/`openapi-pydantic`.
- `infrastructure/import_gateway/factory.py` —
  `build_import_gateway(kind)` (match/case).
- `services/integrations/import_service.py` — `ImportService`
  (idempotency через SHA256 hash в `connector_configs`,
  orphan-cleanup, register_actions через `ActionHandlerRegistry`,
  secret_refs_required возвращается без записи значений в `config`).

Auth-extraction приводит security-схемы (Bearer/Basic/ApiKey/OAuth2) к
`AuthSpec` с `SecretRef`-ами — ссылками `${VAR_NAME}`. Реальное
наполнение SecretsBackend (Vault) — отдельный шаг, чтобы избежать
утечек plaintext-секретов в `connector_configs`.

Legacy-стэки удалены полностью: `src/tools/schema_importer/`,
`src/dsl/importers/`. Миграция call-sites выполнена за один шаг
(REST endpoints, DSL actions, Streamlit page, manage.py CLI).

## Последствия

- ✅ **Положительные**:
  - Удалено ~1100 LOC дубликата.
  - WSDL-импорт теперь поддерживается (через `zeep`, уже подключён).
  - Идемпотентность импорта (SHA256-hash check).
  - Auth-секреты не пишутся открытым текстом.
  - Orphan-cleanup при reimport.
  - DSL actions унифицированы (`connector.import` /
    `connector.list_imported`).

- ⚠️ **Отрицательные**:
  - +1 dependency: `openapi-pydantic>=0.5.0,<1.0.0` (~50KB).
  - Smoke-тестирование импортированного endpoint'а пока не
    автоматизировано (отложено в W24.x).
  - Mapping JSON Schema → Pydantic-моделей в новом ImportGateway
    отсутствует (legacy `pydantic_gen.py` удалён); восстановить можно
    через `datamodel-code-generator`, если потребуется.
  - Streamlit Wizard (план 24.4) реализован минимально (одна страница
    `26_Import_Schema.py`); полноценный wizard — отдельный шаг.

- 〰 **Нейтральные**:
  - DSL actions переименованы: `openapi.import` → `connector.import`,
    `openapi.list_imported` → `connector.list_imported`. Старый
    `openapi.preview` удалён (заменён на `dry_run=True` в `import`).

## Связанные ADR

- ADR-013 (FastStream / messaging consolidation) — образец
  Gateway-pattern.
- ADR-031 (DSL durable workflows) — общий принцип «один Gateway
  для функционально близких задач».
- W23 SourceRegistry — соседний Gateway (sources side).
