# ADR-021: DSL interop — import/export из Camel/Spring Integration

* Статус: accepted
* Дата: 2026-04-21
* Фазы: K1

## Контекст

Клиенты из мира Apache Camel / Spring Integration хотят переносить
декларативные route в наш DSL. И наоборот — экспортировать наши
route в стандарт interop-формат (например, AsyncAPI + OpenAPI) для
интеграции с их pipeline-орchest.

## Решение

1. Import: parser Camel XML DSL → наш YAML DSL (lossy, но покрывает
   80 % базовых EIP).
2. Import: Spring Integration `<int:...>` → YAML DSL — аналогично.
3. Export: YAML DSL → AsyncAPI 2.6 (уже через FastStream) + OpenAPI
   3.1 (уже через FastAPI).
4. CLI: `gdi dsl import --from camel <file.xml>`,
   `gdi dsl import --from spring <file.xml>`.

## Альтернативы

- **Поддержка Camel runtime напрямую** (via Py4J): отвергнуто,
  heavyweight.

## Последствия

- Onboarding команд с Camel background → смоделировать + вручную
  доправить нестандартные куски.
