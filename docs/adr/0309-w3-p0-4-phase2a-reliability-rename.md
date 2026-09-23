# ADR-0309 — W3 P0-4 Phase 2A: rename `_legacy.py` → `common.py` (reliability)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W3 P0-4 Phase 2A; ADR-0307 (shim inventory + classification).
* Заменяет: misleading имя `_legacy.py` для shared reliability module.

## Контекст

Cycle 152 W3 P0-4 Phase 1 (ADR-0307) идентифицировал
`src/backend/dsl/engine/processors/eip/reliability/_legacy.py` как
misleading-name кандидат для rename. Дальнейший recon (Phase 2A)
выявил реальное содержимое:

**`_legacy.py` НЕ содержит legacy код.** Содержит:

1. **Header constants** (JMS-style / Camel conventions):
   * `HEADER_CORRELATION_ID`
   * `HEADER_MESSAGE_ID`
   * `HEADER_EXPIRATION`
   * `HEADER_REDELIVERED`
   * `HEADER_REDELIVERY_COUNT`
   * `HEADER_RETURN_ADDRESS`

2. **Type aliases** для reliability-процессоров:
   * `IdFactory`
   * `ExpirationResolver`
   * `RedeliveryAttempt`

3. **`__getattr__`** для backward-compat lazy resolution Processor-классов
   (но классы уже импортируются напрямую в `__init__.py` — `__getattr__`
   был мёртвый код с cycle S175 Phase 2).

Сам файл — **shared module для 4 reliability-процессоров** (Redelivery,
Expiration, Correlation Identifier, Return Address). Имя `_legacy.py` —
misleading: префикс `_` в Python convention обозначает private, а суффикс
`_legacy` намекает на deprecated. Ни то, ни другое не верно.

## Решение

### Rename файла

* `git mv src/backend/dsl/engine/processors/eip/reliability/_legacy.py`
  → `src/backend/dsl/engine/processors/eip/reliability/common.py`.

### Изменения содержимого `common.py`

1. **Docstring обновлён**: явно говорит что файл — shared module, не legacy.
   Удалена старая секция "Apache Camel EIP catalog (reliability / routing-metadata)"
   со списком Processor-классов (они в своих собственных модулях).

2. **`__all__` очищен**: удалены Processor-классы (они не определены в
   common.py). Оставлены только header constants + type aliases.

3. **`__getattr__` удалён**: мёртвый код после S175 Phase 2 (Processor-классы
   импортируются в `__init__.py` напрямую).

### Обновления импортёров

| Файл | Изменение |
|---|---|
| `reliability/__init__.py` | `from ._legacy import ...` → `from .common import ...`. Docstring обновлён со ссылкой на rename. |
| `reliability/correlation_identifier.py` | import `HEADER_CORRELATION_ID` из `common`. |
| `reliability/message_expiration.py` | import `HEADER_EXPIRATION`, `HEADER_MESSAGE_ID`, `ExpirationResolver` из `common`. |
| `reliability/redelivery_policy.py` | import `HEADER_REDELIVERED`, `HEADER_REDELIVERY_COUNT`, `RedeliveryAttempt` из `common`. |
| `reliability/return_address.py` | import `HEADER_RETURN_ADDRESS` из `common`. |

### Обновление теста

`tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py`:

* Старый тест `test_legacy_processor_exports_resolve_lazily` (проверял
  backward-compat через `_legacy.__getattr__`) заменён на
  `test_common_module_exposes_constants_and_types` — проверяет что
  новый модуль `common` экспортирует header constants + type aliases
  с правильным `__all__`.

## Альтернативы (рассмотренные, отклонённые)

* **Оставить `_legacy.py`**: отклонено — misleading имя путает читателя
  (см. ADR-0307 classification как `misleading-name`).
* **`__getattr__` оставить для backward-compat**: отклонено — `__getattr__`
  мёртвый код (Processor-классы импортируются напрямую); старый тест
  проверял его, но это был тест на dead functionality.
* **`_common.py` (с underscore prefix)**: отклонено — `common` явно
  подчёркивает назначение, без `_` (Python видит как обычный public
  sub-module внутри `reliability/`).

## Последствия

**Плюсы**:

* Misleading имя устранено — `common.py` явно говорит о shared-nature.
* Мёртвый `__getattr__` удалён (-25 LOC, упрощение maintenance).
* `__all__` теперь соответствует реальному содержимому.
* Все импорты работают через `__init__.py` (re-export из common.py).

**Минусы / риски**:

* `from reliability import _legacy` больше не работает (но это был
  internal API для теста, не public).
* Любой downstream tooling, использующий `from reliability import _legacy`,
  нужно обновить. Mitigated: если такие есть, regression в тестах
  покажет. На момент cycle 152 — 0 production импортёров за пределами
  reliability/ subpackage + 1 тест (обновлён).

## Verification

```
python3.14 -m compileall -q src/backend/dsl/engine/processors/eip/reliability/
  → exit 0
python3.14 -m compileall -q src/ extensions/ scripts/ tools/ tests/
  → exit 0
python3.14 tools/checks/check_python3_syntax.py --root src/backend
  → exit 0
python3.14 -m pytest tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py -v
  → 16 passed (включая новый test_common_module_exposes_constants_and_types)

# Import sanity:
python3.14 -c "from src.backend.dsl.engine.processors.eip.reliability import (
    HEADER_CORRELATION_ID, HEADER_MESSAGE_ID, HEADER_EXPIRATION,
    HEADER_REDELIVERED, HEADER_REDELIVERY_COUNT, HEADER_RETURN_ADDRESS,
    CorrelationIdentifierProcessor, MessageExpirationProcessor,
    RedeliveryPolicyProcessor, ReturnAddressProcessor,
    IdFactory, ExpirationResolver, RedeliveryAttempt,
)"
  → OK
```

## Связанные изменения

* **`src/backend/dsl/engine/processors/eip/reliability/_legacy.py`** →
  **`common.py`** (rename via `git mv`).
* **`src/backend/dsl/engine/processors/eip/reliability/__init__.py`** —
  updated imports + docstring.
* **`src/backend/dsl/engine/processors/eip/reliability/{correlation_identifier,
  message_expiration,redelivery_policy,return_address}.py`** — updated imports.
* **`tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py`** —
  test renamed: `test_legacy_processor_exports_resolve_lazily` →
  `test_common_module_exposes_constants_and_types`.
* **`docs/adr/0309-w3-p0-4-phase2a-reliability-rename.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0309 зарегистрирован (102 ADRs total).
* **`CHANGELOG.md`** — запись цикла 152.
* **`docs/roadmap/PROGRESS_LEDGER.md`** — wave-memo для cycle 152.

Refs: MINIMAX W3 P0-4 Phase 2A, ADR-0307 (inventory + classification),
ADR-0309 (this), cycle 152.