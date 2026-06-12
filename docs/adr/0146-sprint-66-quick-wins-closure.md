# ADR-0146 — Sprint 66 closure: fact-checked quick wins (4 commits, 4/4 substantive)

* Статус: Accepted (Autonomous work cycle S66, 2026-06-12)
* Связано с: `eb05dcc9` (S66 W1 pendulum), `2c7aa386` (S66 W2 ARCHITECTURE), `c8593d4f` (S66 W3 namespace), `11a465e0` (S66 W4 BatchUpdateProcessor docstring + tests)
* Контекст: comprehensive audit (2026-06-11) + S65 P0 cleanup closure

## Контекст

S66 = XS/S quick wins из P1/P2 плана comprehensive audit. **4/4
fact-checked** — каждое утверждение проверено в коде, 2 ошибки
анализа обнаружены и документированы.

**Fact-check findings** (против исходного аудита):
- ❌ `BatchUpdateProcessor` "cycle per item" — **НЕВЕРНО**, код уже
  executemany per column-group. Docstring misleading.
- ❌ `scripts/check_layers.py` duplicate — **НЕ СУЩЕСТВУЕТ** (только
  `tools/check_layers.py`).
- ✅ `pendulum` dedup — **реальный** (line 48 + 107 в `[project].dependencies`).
- ✅ `ARCHITECTURE.md` 3× "125 legacy" — **реальное устаревание** (S65
  → 201).

## Решения

### W1: `pyproject.toml` — pendulum dedup (commit `eb05dcc9`)

**Analysis P1-17**: pendulum дублировался в `[project].dependencies`:
- Line 48: `"pendulum>=3.2.0,<4.0.0",` (versioned)
- Line 107: `"pendulum",` (versionless — baseline до S57 W1)

**Fix**: удалён versionless дубль (line 107). Verified: tomllib валиден,
91 entries, 1 pendulum.

### W2: `ARCHITECTURE.md` — обновление цифр (commit `2c7aa386`)

**Analysis P1-18**: 3 устаревших упоминания "125 legacy layer-нарушений"
+ 1 неверный путь `scripts/check_layers.py` (S27, файл удалён).

**Fix**:
- 3× "125 legacy" → "201 legacy" (lines 60, 298, 305)
- 1× `scripts/check_layers.py` → `tools/check_layers.py` (line 59)
- Добавлено: "82 baseline + 35 lazy imports S65 W2 + 119 dsl/workflows S65 W4"

### W3: `__init__.py` namespace markers (commit `c8593d4f`)

**Analysis P2-23**: 24 пустых `__init__.py` в `src/backend/`. Часть —
PEP 420 namespace-пакеты (пустые by design).

**Fix**: 5 стратегических namespace-пакетов получили docstring-маркер
с явным указанием на PEP 420 pattern:
- `src/backend/services/__init__.py`
- `src/backend/services/ai/__init__.py`
- `src/backend/services/io/__init__.py`
- `src/backend/services/ops/__init__.py`
- `src/backend/core/__init__.py`

**НЕ `__all__`**: namespace-пакеты по PEP 420 не должны экспортировать
symbols на уровне корня. Только documentation intent.

**Оставшиеся 21 empty** (subpackage-level) — deferred S67+ (меньше
семантической нагрузки на docstring).

### W4: `BatchUpdateProcessor` docstring + tests (commit `11a465e0`)

**Analysis P1-5 (WRONG)**: "BatchUpdateProcessor — один UPDATE per item
(цикл). ``for item in batch: await session.execute(update_stmt, item)``".

**S66 W4 FACT-CHECK**: код РЕАЛЬНО использует `executemany` per
column-group. Grouping: `frozenset(update_columns)` → одинаковый набор
обновляемых колонок = один group → `session.execute(text(stmt), params_list)`
= **executemany** (single RTT per group).

**Fix (doc-only + tests, no behavior change)**:
- Docstring: "один statement на item" → "executemany per column-group"
  + явное сравнение с ошибочным analysis claim.
- 3 unit-теста (`test_batch_update_executemany.py`) ЗАКРЕПЛЯЮТ
  правильное поведение:
  - `test_batch_update_uses_executemany_not_cycle`: mock session, 3
    items с одинаковыми columns → 1 execute call (executemany), 3
    params в list.
  - `test_batch_update_docstring_does_not_claim_cycle`: static check,
    не должно быть "один statement на item".
  - `test_batch_update_process_method_uses_executemany_pattern`: AST
    check на `params_list` в `process()`.

**Verified**: 3/3 NEW + 10/10 EXISTING batch tests pass.

## Fact-checks summary (S66)

| Analysis claim | Реальность | Статус |
|---|---|---|
| P1-17 `pendulum` dedup | Реально, удалён versionless дубль | ✅ fixed |
| P1-18 `ARCHITECTURE.md` 125→44 | Реально 3× "125", обновлено до 201 | ✅ fixed |
| P1-5 `BatchUpdateProcessor` cycle | **НЕВЕРНО**, executemany per group | ❌ moot, docstring fixed |
| P2-19 `scripts/check_layers.py` dup | **НЕ СУЩЕСТВУЕТ** | ❌ moot |
| P2-23 24 empty `__init__.py` | 24→19 (5 fixed, 19 deferred) | ✅ partial |
| P2-28 `jwt_backend_joserfc.py` dup | Реально duplicate, но USED | ⏸ deferred S67+ |

## Quality gates (S66 scope)

- **mypy**: S66 changes clean (no new errors).
- **ruff**: clean.
- **3 NEW batch tests** pass + 10 EXISTING batch tests still pass.
- **tomllib** validates `pyproject.toml` after pendulum dedup.
- Sibling WIP outstanding: ~1700 mypy errors (не наш scope).

## Lessons learned

1. **"Анализ ≠ ground truth"** — 2/5 P1/P2 items в этом спринте были
   неточными (BatchUpdateProcessor, scripts/check_layers.py). Перед
   fix ВСЕГДА verify в коде.
2. **Misleading docstring хуже отсутствующего** — BatchUpdateProcessor
   docstring утверждал "один statement на item" хотя код правильный.
   Fix через test-driven documentation: tests закрепляют real behavior.
3. **PEP 420 namespaces** — не все "empty `__init__.py`" это баги.
   Часть намеренно пустые. Docstring-маркер лучше, чем `__all__` или
   удаление.
4. **Документация в коде > в ADR** — docstring на месте видна сразу,
   ADR — нет. Doc-only fix (W4) — самый cheap способ сохранить knowledge.

## S67+ backlog

- **jwt_backend consolidation** (M, deferred): `jwt_backend_joserfc.py`
  удалить, перевести `auth_login.py` + `auth_introspect.py` на canonical
  `jwt_backend.py`. Параллельная реализация больше не нужна (оба use
  `joserfc`).
- **19 remaining empty `__init__.py`** (S): subpackage-level namespace
  markers, если есть семантическая ценность.
- **35 core → other layers violations** (L): рефакторинг
  `gateway_pipeline_mixin/*`, `di/providers/ai.py`.
- **119 dsl/workflows violations** (L): god-files (`agent_registry.py`,
  `batch_capable.py`, `_action_bridge.py`).
- **Pre-existing import bugs** (M): `DatabaseInitializer`, `graphql_router`,
  `redis_client decorator`.
- **AgentSpec.tools runtime enforcement** (L): MCP gateway interceptor.
