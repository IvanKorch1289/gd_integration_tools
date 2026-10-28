# ADR-0364 — Удаление мёртвого кода, найденного в Wave 13

* Статус: Accepted (2026-10-28, cycle 172, владелец Mavis)
* **Cycle**: 172 (Wave 13, гриллинг раунд 2, решение Q5)
* **Связан с**:
  - ADR-0100 (удаление мёртвого `dsl/builders/eip.py` — тот же прецедент)
  - ADR-0359 (канонический SQL-guard)
  - ADR-0358 (path-allowlist)
  - `artifacts/current_audit/FRONTIER_ROUNDS_2026-10-27.md` (раунд 2, Q5)
* **Затрагивает**:
  - `src/backend/infrastructure/database/database/initializer.py`
  - `src/backend/dsl/registry/lazy_processor.py`
  - `src/backend/dsl/engine/processors/rpa/file_search.py` (удалён)
  - `tests/unit/dsl/registry/test_lazy_processor.py`
  - `tests/unit/dsl/engine/processors/rpa/test_file_search.py` (удалён)
  - `tests/unit/dsl/engine/processors/test_path_allowlist_wave13_followup.py`

## Контекст

Аудит Wave 13 (S-18, S-26) указал несколько сущностей, которые не имеют
использования. Прецедент ADR-0100 и правило ADR-0099/ADR-0100 важны: заявления
аудита о «мёртвом коде» систематически требуют перепроверки — часть таких
заявлений в прошлых циклах была ложной (в текущем цикле так оказалось
утверждение про `InboxDLQWriter`: он подключён в
`src/backend/plugins/composition/di.py:260` и
`src/backend/infrastructure/messaging/outbox/lifecycle.py:147`).

Поэтому перед удалением каждая кандидатура проверялась grep-ом по `src/`,
`tests/`, `extensions/`, `tools/`.

### Проверенные кандидатуры

| Сущность | Проверка | Вердикт |
|---|---|---|
| `execute_with_resilience()` (`infrastructure/database/database/initializer.py`) | 0 вызовов в `src/`, 0 в `tests/`; docstring обещал «CB + Retry», тела не было | мёртвая → удалить |
| `FileSearchProcessor` (`dsl/engine/processors/rpa/file_search.py`) | standalone-класс (не `BaseProcessor`), не зарегистрирован в реестре DSL, 0 вызовов в `src/`, не реэкспортирован в `rpa/__init__.py` | мёртвый → удалить модуль |
| `capabilities_for()` (`dsl/registry/lazy_processor.py`) | 0 вызовов в `src/`; комментарий «policy-gate» без реализации | мёртвый → удалить метод |
| `SqliteDocStore` | 0 инстанцирований в `src/`, но задокументирован в `core/interfaces/doc_store.py:5` как dev/test-бэкенд | **оставить** — контракт ссылается на него |
| `InboxDLQWriter` | подключён в `plugins/composition/di.py:260` | **оставить** — заявление аудита неверно |

## Решение

1. Удалены три мёртвые сущности (см. таблицу). Вместе с ними удалены
   ставшие неиспользуемыми импорты (`connector_resilience.resilient` в
   `initializer.py`) и тесты, проверявшие удалённое поведение
   (`test_capabilities_for_*` в `tests/unit/dsl/registry/test_lazy_processor.py`;
   файл `tests/unit/dsl/engine/processors/rpa/test_file_search.py`).
2. `FileSearchProcessor` получил `validate_path` в ходе Wave 13 (ADR-0358) —
   перед удалением guard был актуальным, чтобы при возможном возврате
   модуля защита уже была на месте.
3. `LazyProcessorRegistry` и `register_lazy` сохранены: реестр — точка
   расширения для lazy-процессоров, удаление целого подсистемы выходит за
   рамки решения (отдельный ADR не принимался).

## Последствия

- Минус 3 мёртвые сущности; `docs/runbooks/lazy-processor-warmup.md:62`
  обновлён (Option C больше не ссылается на удалённый метод;
  актуальный путь — `lazy.list_lazy_refs()` → `LazyProcessorRef.capabilities`).
- Исторические документы (`docs/adr/0358-…`, `docs/rpa/DSL_AUDIT.md`,
  `docs/SPRINT_171_M24_CLOSE.md`, `docs/PROJECT_RECOMMENDATIONS.md`) продолжают
  упоминать `FileSearchProcessor`: ADR и отчёты аудита иммутабельны, правка
  не вносилась.
- Проверка: `pytest tests/unit/dsl tests/unit/core/config
  tests/unit/infrastructure/database` — 5966 passed, 30 skipped, 32 xfailed,
  25 xpassed; `tools/check_layers.py --strict` — 41 (baseline, новых нет);
  `tools/check_docstrings.py` — 1 missing (pre-existing,
  `dsl/builders/infra_logging_mixin.py:28`).

## Альтернативы (отклонённые)

- **(а) Оставить мёртвый код «на будущее»** — отклонено: неисполняемая
  декларация (обещание CB+Retry в docstring) вводит в заблуждение ровно так же,
  как мёртвые ключи конфига (ADR-0362).
- **(б) Удалить и `SqliteDocStore`** — отклонено: на него ссылается публичный
  контракт `core/interfaces/doc_store.py:5`; удаление сломало бы контракт.
- **(в) Удалить `LazyProcessorRegistry` целиком** — отклонено: точка
  расширения; `register_lazy` не имеет вызовов, но удаление подсистемы —
  отдельное решение с отдельным ADR.

## Связи с другими ADR

- ADR-0100 — прецедент удаления мёртвого кода с проверкой вызовов.
- ADR-0099 — «аудит систематически фабрикует заявления»: каждая кандидатура
  перепроверена grep-ом перед удалением.
- ADR-0358 — path-allowlist (модуль `file_search.py` получил guard перед
  удалением).
