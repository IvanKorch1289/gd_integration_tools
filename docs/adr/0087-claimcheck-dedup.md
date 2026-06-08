# ADR-0087 — ClaimCheckProcessor Dedup (S63 W2.1)

**Status:** Accepted
**Date:** 2026-06-08
**Authors:** K3
**Sources:** роевой аудит 2026-06-08 (verify-analysis-claims), CLAUDE.md §EIP coverage
**Supersedes:** S38 W1 (S38-ClaimCheckProcessor-S3-DI)
**See also:** ADR-0086 (aiocache, sibling scope-reduction pattern), [eip/transformation.py](../../../src/backend/dsl/engine/processors/eip/transformation.py)

## Context

Роевой аудит 2026-06-08 выявил 2 реализации Claim Check EIP в проекте:

| Реализация | Путь | LOC | Backend | API |
|---|---|---|---|---|
| **S38 W1 (старая)** | `src/backend/dsl/processors/claim_check_processor.py` | 132 | S3-only (DI `s3_client`) | `direction="store"\|"retrieve"`, `s3_bucket` |
| **EIP canonical** | `src/backend/dsl/engine/processors/eip/transformation.py:177` | 404 | Redis + S3 composite (lazy providers) | `mode="store"\|"retrieve"`, `store="redis"\|"s3"`, `ttl_seconds` |

**Проблемы дубля:**

1. **Дублирование кода** — 132 LOC кастома S3-only, при том что канонический eip-вариант уже покрывает S3 + Redis с 256KB auto-routing.
2. **Дрейф API** — `direction` vs `mode`, `s3_client=callable` DI vs lazy `get_s3_client()` / `redis_client()`.
3. **Дублированные тесты** — `tests/unit/dsl/processors/test_claim_check_processor.py` (200 LOC) тестирует S38 W1; eip-вариант тестируется в `tests/unit/dsl/engine/processors/eip/test_transformation.py:74+` (8 тестов, 27 passed).
4. **Inconsistency** — extensions, импортирующие через `from src.backend.dsl.processors.claim_check_processor import ClaimCheckProcessor`, получают старую S3-only версию.

**Анализ scope** (S63 W2.1 verify):

* `grep -rn "from src.backend.dsl.processors.claim_check_processor"` →
  ровно 1 импорт: `src/backend/dsl/processors/__init__.py:19` (свой __init__).
  Никаких external extensions/importers.
* `grep -rn "ClaimCheckProcessor"` (везде): используется в 5 файлах,
  но **все** импорты — из `engine.processors.eip.transformation`,
  НЕ из старого `dsl.processors.claim_check_processor`.
* Тесты: `test_claim_check_processor.py` (200 LOC) — единственный test
  старого варианта; eip-вариант покрыт в `test_transformation.py`.

**Принципы** (CLAUDE.md, sprint rules):

* "минимизация кастомного кода" — старый 132 LOC кастома дублирует готовый eip.
* "отсутствие мертвого кода" — старый используется только в своём __init__.
* "разделение ядра от роутов/расширениц" — canonical eip в `engine/processors/`
  (core layer), старый в `dsl/processors/` (extension layer) — нарушение.
* "libraries > custom" (S58 W1 lesson) — eip-вариант использует lazy
  factory pattern (стандарт для проекта), старый — DI callable (anti-pattern).

## Decision

**Удалить `src/backend/dsl/processors/claim_check_processor.py` (132 LOC) и его тесты (200 LOC).**

**Канонический путь:** `src.backend.dsl.engine.processors.eip.transformation.ClaimCheckProcessor` — Redis+S3 composite, `mode="store"|"retrieve"`, `store="redis"|"s3"`, `ttl_seconds`, `threshold_bytes`.

**Действия (S63 W2.1):**

1. `git rm src/backend/dsl/processors/claim_check_processor.py` (132 LOC).
2. `git rm tests/unit/dsl/processors/test_claim_check_processor.py` (200 LOC).
3. UPDATE `src/backend/dsl/processors/__init__.py`: убрать re-export,
   добавить `.. deprecated::` docstring pointing to eip-вариант.
4. Fixup `src/backend/dsl/engine/processors/eip/transformation.py`:
   ruff organize-imports (1 fixable).
5. Verify: pytest 27 passed, ruff check passed.

**Coverage не теряется:** eip-вариант покрыт в `test_transformation.py`
(8 тестов: store_s3, store_redis, threshold, retrieve_redis, retrieve_s3,
fail_no_token, ttl, mode_validation).

**No backward-compat shim:** единственный импортёр (`processors/__init__.py`)
внутренний, не external API. Удаление безопасно.

## Consequences

### Positive
* **-332 LOC** кастома (132 implementation + 200 tests).
* **0 dead code** — старый путь больше не существует.
* **Единая точка изменения** для Claim Check логики (eip/transformation.py).
* **Нет дрейфа API** — extensions используют только canonical путь.

### Negative
* **API breaking change** для hypothetical external importers
  `from src.backend.dsl.processors.claim_check_processor import …` —
  но grep подтверждает: таких importers нет.
* **Documentation debt** — некоторые docs/ могут ссылаться на старый путь;
  решается в S63 W4 (docs/audit wave).

### Neutral
* **EIP coverage dashboard** в Streamlit (S63 W4) покажет 1/10 pattern
  с dual-source warning, если dedup когда-нибудь будет отменён.

## Verification

```bash
# Tests
pytest tests/unit/dsl/engine/processors/eip/test_transformation.py -v
# Expected: 27 passed (8 ClaimCheck-related)

# Imports OK
.venv/bin/python -c "from src.backend.dsl.engine.processors.eip.transformation import ClaimCheckProcessor; print('OK')"
.venv/bin/python -c "from src.backend.dsl.processors import BatchProcessor, PlanExecuteProcessor, SagaLRAProcessor; print('OK')"

# Old path is gone
.venv/bin/python -c "from src.backend.dsl.processors.claim_check_processor import ClaimCheckProcessor"
# Expected: ModuleNotFoundError

# Ruff clean
.venv/bin/python -m ruff check src/backend/dsl/processors/ src/backend/dsl/engine/processors/eip/transformation.py
# Expected: All checks passed
```

S63 W2.1 [wave:s63/w2-eip-pattern-completeness]
