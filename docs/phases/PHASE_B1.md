# Фаза B1 — Refactor builder.py → 11 mixin-категорий

* **Статус:** done (phase-1)
* **Приоритет:** P1
* **ADR:** ADR-001
* **Зависимости:** A5

## Цель

Снять cognitive load god-object `RouteBuilder` (1313 LOC, 170 методов)
через категорийную декомпозицию публичного API.

## Выполнено (phase-1)

- Создан пакет `src/dsl/builders/` с `__init__.py`.
- 11 mixin-маркеров (`CoreMixin`, `EIPMixin`, `TransportMixin`,
  `StreamingMixin`, `AIMixin`, `RPAMixin`, `BankingMixin`,
  `BankingAIMixin`, `StorageMixin`, `SecurityMixin`, `ObservabilityMixin`).
- `RouteBuilder` re-export — публичный API не изменён.
- ADR-001 зафиксировано решение и план phase-2.

## Phase-2 (follow-up — открыт, не блокирует мердж)

Физическое разнесение реализации на 11 файлов ≤300 LOC. Выполняется
после B2 (split files > 500 LOC), чтобы сначала нормализовать соседние
крупные файлы, потом — разложить RouteBuilder без конфликтов. Открыт
как отдельный подпункт в backlog «B1 phase-2».

## Definition of Done (phase-1)

- [x] Пакет `app.dsl.builders` создан.
- [x] 11 mixin-классов объявлены.
- [x] Публичный API не сломан (`from src.dsl.builder import RouteBuilder`
      + `from src.dsl.builders import RouteBuilder` — оба работают).
- [x] ADR-001 создан.
- [x] `docs/phases/PHASE_B1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (B1 → done).

## Как проверить вручную

```bash
python3 -c "
from src.dsl.builders import RouteBuilder as RB1
from src.dsl.builder import RouteBuilder as RB2
assert RB1 is RB2 or issubclass(RB1, RB2) or issubclass(RB2, RB1)
print('OK: API identity preserved')
"
```
