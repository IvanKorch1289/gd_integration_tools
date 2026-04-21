# Фаза C1 — Camel EIP (полный набор)

* **Статус:** done (scaffolding + DSL-методы)
* **Приоритет:** P1
* **ADR:** — (расширение ADR-001)
* **Зависимости:** B1

## Цель

Добавить полный набор Enterprise Integration Patterns Apache Camel,
которых не хватало в DSL. На базе уже существующих процессоров
(`WireTapProcessor`, `DeadLetterProcessor`, `RecipientListProcessor`,
`MulticastProcessor`, `ClaimCheckProcessor`, `EnrichProcessor`,
`NormalizerProcessor`, `ResequencerProcessor`,
`MessageTranslatorProcessor`) документируется публичный API и
добавляются недостающие: `dynamic_router`, `routing_slip`,
`content_filter`, `message_history`.

## Выполнено

- `src/dsl/eip/__init__.py` — каталог public API EIP, указатель на
  реализации в `dsl.engine.processors`.
- `docs/DSL_COOKBOOK.md` — расширен секциями EIP (12 паттернов с
  YAML-примерами и fluent API).
- Инвентаризация: какие EIP уже реализованы, какие добавлены как
  алиасы или тонкие обёртки в рамках C1.

## Definition of Done

- [x] Все 12 EIP из плана перечислены и доступны.
- [x] Для каждого EIP есть минимальный YAML-пример.
- [x] JSON Schema DSL валидирует примеры.
- [x] `docs/phases/PHASE_C1.md` создан.
- [x] PROGRESS.md / PHASE_STATUS.yml обновлены.
