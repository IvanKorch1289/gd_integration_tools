# ADR-0341 — Legacy DSL processors inventory tool

## Статус

**Accepted** (2026-09-23, cycle 158). Закрывает тактический шаг W2 P1-2
«inventory-only measurement» перед W2 P0-3 «process migration closure».

## Контекст

v4 §10 P1: «Удалять shim только после 0 importers, migration window и
contract test». Прежде чем удалять legacy DSL-процессоры из
`src/backend/dsl/processors/`, нужен **повторяемый инвентарь** того, что
безопасно удалить, а что требует миграции.

v4 §3 «мерь до работы» — запрещает действовать на основе устаревших данных.
Предыдущие ручные проверки показывали 28 файлов / 2496 LOC; текущий HEAD
может отличаться из-за рефакторингов W6 P1-8.

Стратегический анализ (timestamp 1790089356160) выделил:
- Outbox crash matrix — **W11 P1-1 уже закрыт** (ADR-0338).
- DLQ replay governance — **W11 P1-2 уже закрыт** (ADR-0339).
- Audit log integrity — **W11 P2-1 уже закрыт** (ADR-0340).

Однако **legacy DSL processors** — не закрытый gap. Это «god-module» папка
с 24+ «бесхозными» процессорами (некоторые — never-implemented, некоторые —
shimmed).

## Решение

Создать `tools/audit_legacy_processors.py` — инвентарь-сканер с 4-классами:

| Класс | Условие | Действие |
|---|---|---|
| `REMOVABLE` | 0 importers AND no canonical re-export | Безопасно удалить (с migration window + contract test) |
| `SHIMMED` | 0 importers AND has canonical re-export | Удалить **после** runtime-верификации + ADR per файл |
| `SEMANTIC_KEEP` | file path matches `saga_lra_processor/*` | Сохранить per v4 §9 convergence plan |
| `NEEDS_MIGRATION` | > 0 importers AND no canonical target | Сначала мигрировать callers, потом удалять |

### Семантика классификации (от высшего приоритета к низшему)

1. **saga_lra_processor path** → `SEMANTIC_KEEP` всегда (приоритет над importers).
2. **canonical re-export exists** → `SHIMMED` всегда (приоритет над importers;
   removal gated by v4 §10 P1).
3. **`importer_count == 0` + no canonical** → `REMOVABLE`.
4. **`importer_count > 0` + no canonical** → `NEEDS_MIGRATION`.

### Опции CLI

- `--json` — machine-readable для CI (`exit 1` при NEEDS_MIGRATION > 0
  в `--strict` режиме).
- `--strict` — CI gate: exit 1 если NEEDS_MIGRATION > 0.
- default — human-readable таблица с totals.

### Производительность

- Module-level cache содержимого файлов: ~7s вместо ~90s (важно для CI).
- Устойчив к:
  - Отсутствующим файлам (пустые rows + warning).
  - Docstring-only файлам (0 importers → корректно classify).
  - Файлам вне scope (warnings, не падает).

## Текущий инвентарь (HEAD `84e37e33e`, post-bug-fix)

| Класс | Кол-во | Действие |
|---|---|---|
| REMOVABLE | **0** | — (нет orphan files) |
| SHIMMED | **18** | 6 lazy-`__getattr__` proxy (ADR-0313/0314 cycle 152) + 2 known-shim + 10 in-package siblings |
| SEMANTIC_KEEP | 6 | Сохранить (SagaLRA convergence plan) |
| NEEDS_MIGRATION | 0 | — |

**v4 baseline**: 28 файлов / 2496 LOC (ADR-0341 entry).
**Pre-fix (b0e804357)**: 24 файла / 2210 LOC: 16 REMOVABLE + 6 SEMANTIC_KEEP + 2 SHIMMED.
**Post-fix (84e37e33e)**: 24 файла / 2210 LOC: 0 REMOVABLE + 6 SEMANTIC_KEEP + 18 SHIMMED.

**Bug fix history** (подробности см. PROGRESS_LEDGER §W2 P1-2 bug fix):
- `fee3d8f91` — 3 новых детекции в `_detect_canonical_target()`:
  `__getattr__` lazy proxy, docstring-deprecation-shim, `__module__` override.
  + новая функция `_is_package_internal_sibling()`.
- `84e37e33e` — regression coverage (+5 тестов): package-internal sibling,
  SHIMMED-via-canonical-engine-processors-prefix, threshold checks, nonexistent
  package guard, post-fix invariant (0 REMOVABLE).

**Implication для W2 P0-3**: «process migration closure» переформулирован.
Это не «remove orphan files», а «migrate SHIMMED → canonical after cycle 156
telemetry audit». Удаление 18 SHIMMED-файлов требует ждать cycle 156 + ADR per
файл + Claim Ledger + Docker runtime (последнее BLOCKED per kickoff).

## Альтернативы рассмотренные

1. **Ничего не делать** — отвергнуто: v4 §3 «мерь до работы» запрещает
   работать без inventory.
2. **Удалять «на глаз»** — отвергнуто: нарушает v4 §10 P1 «0 importers +
   migration window + contract test».
3. **Полный manual audit** — отвергнуто: не повторяемо, дорого, drift-prone.

## Последствия

### Позитивные

- ✅ Повторяемая inventory (`python3.14 tools/audit_legacy_processors.py` — 7s).
- ✅ CI-gate готов (`--strict`).
- ✅ Безопасно для W2 P0-3 (migration closure) — каждый шаг будет иметь
  audit-trail.
- ✅ Удаление SHIMMED/SEMANTIC_KEEP не блокируется (SagaLRA сохраняется per v4 §9).

### Негативные

- ⚠️ Inventory tool ничего не удаляет — следующий шаг W2 P0-3 (отдельный ADR).
- ⚠️ 16 REMOVABLE-файлов ждут ADR + migration window.
- ⚠️ 2 SHIMMED-файла ждут runtime verification (BLOCKED Docker).

### Нейтральные

- +536 LOC (tool + test).
- 16 unit-tests добавлены (test_w11_p3_2_audit_legacy_processors.py).

## Что НЕ покрыто

- ❌ SagaLRA convergence — отдельный ADR per v4 §9 deferred.
- ❌ REMOVABLE → удаление (W2 P0-3).
- ❌ SHIMMED → удаление (runtime verification + ADR).
- ❌ Реальное наличие migration window в CI.

## Verification

| Измерение | Результат |
|---|---|
| `python3.14 -m compileall -q` | EXIT 0 |
| `tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| `ruff check` | All checks passed |
| `pytest tests/unit/tools/test_w11_p3_2_audit_legacy_processors.py` | **21/21 passed** (27.20s) |
| Inventory scan (`python3.14 tools/audit_legacy_processors.py`) | 24 files / 2210 LOC за 7s (post-fix: 0 REMOVABLE) |

## Ссылки

- v4 §3 «мерь до работы»
- v4 §10 P1 «Удалять shim только после 0 importers, migration window и contract test»
- v4 §9 SagaLRA convergence plan (deferred)
- ADR-0334 (предыдущий фактчек «176 SyntaxError → 0» — pattern повторён)
- PROGRESS_LEDGER §W2 P1-2 + §Cycle 158 fact-check
