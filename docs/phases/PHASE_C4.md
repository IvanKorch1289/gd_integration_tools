# Фаза C4 — CloudEvents 1.0 + Schema Registry + AsyncAPI

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** ADR-010
* **Зависимости:** C3

## Выполнено

- `src/infrastructure/eventing/cloudevents.py` — `CloudEvent` dataclass
  + `envelope()` / `parse_envelope()` helpers с полным набором CE 1.0
  полей + extensions (`tenantid`, `traceparent`).
- `src/infrastructure/eventing/schema_registry.py` — `SchemaRegistry`
  с JSON Schema и Avro, graceful degrade при недоступности
  remote-registry.
- `src/infrastructure/eventing/__init__.py` — public API.

AsyncAPI автоген — делегирован FastStream (C5).

## Definition of Done

- [x] CloudEvent 1.0 envelope (required + extension-поля).
- [x] SchemaRegistry для JSON и Avro.
- [x] Local cache при недоступности remote-registry.
- [x] `docs/adr/ADR-010-cloudevents-schema-registry.md`.
- [x] `docs/phases/PHASE_C4.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C4 → done).
