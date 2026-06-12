# TODO Catalog (S97 W3)

Каталог открытых TODO в `src/backend/core/`, `src/backend/dsl/` (НЕ
тестов). Найдено grep'ом `rg "TODO|FIXME|XXX" src/backend/core/ src/backend/dsl/`.

## Категории

### 1. Long-standing tech debt (deferred since S18-S40)

| Файл:стр | TODO | Спринт | План |
|----------|------|--------|------|
| `core/middleware/__init__.py:12` | full implementation per ADR-A-01 | S18 (deferred) | S98+ — middlewares registry builder |
| `dsl/cli/generate.py:304` | Implement {name} — audit placeholder | S40 W6 (deferred) | S98+ — DSL codegen |
| `dsl/engine/processors/express/_common.py:32` | callback-приёмник (Wave 4.2) | S40 (deferred) | S99+ — express integration |
| `dsl/workflow/compiler/step_compilers.py:319` | integrate LangGraph Checkpointer | S24 W3 (deferred) | S99+ — LangGraph integration |

### 2. Documentation markers (NOT real TODOs)

| Файл:стр | Текст | Почему НЕ TODO |
|----------|-------|----------------|
| `core/config/features/__init__.py:12` | "flag-deprecation — отдельный шаг с TODO в коде" | Описание в docstring, не actual TODO |
| `core/security/pii_masker.py:30,31,53` | `XXX-XXX-XXX XX` (формат SNILS/passport) | Regex pattern placeholder, не actual TODO |
| `dsl/codec/json.py:144` | `\\uXXXX` (escape reference) | JSON-escape format, не actual TODO |

## S97 W3 Action

**Не фикшу** реальные TODO — каждое требует отдельной фичи (Sprint-scale work).

**Документирую** каталог в `docs/tech-debt/TODO-CATALOG.md` для tracking.

## False positives identification

Grep `TODO|FIXME|XXX` даёт **много false positives** в:
- Regex patterns (placeholder для matching, e.g., `\\d{3}-\\d{3}-\\d{3}`)
- Docstrings describing format (e.g., "passport — RU ``XXXX XXXXXX``")
- Generated code placeholders
- Comments о архитектурных notes ("Wave 4.2 — TODO" в design comment)

Только 4 entries — actual deferred features. Остальные — документация/паттерны.

## S98+ Plan

S98+ будет инкрементально закрывать по 1 TODO за sprint. Приоритет:
1. `core/middleware/__init__.py:12` (high impact — middleware registry)
2. `dsl/cli/generate.py:304` (medium — DSL codegen)
3. `step_compilers.py:319` (LangGraph integration, large)
4. `_common.py:32` (express integration, small)
