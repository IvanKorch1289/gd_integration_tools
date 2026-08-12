# Cycle 3 — T-07 / C3-07 — WorkflowFlags defaults lie fix

- **Дата:** 2026-08-06
- **Global task ID:** `C3-07`
- **Source task ID:** `workflow:DOMAIN-WF-P0-001` (PHASE-2 §3.1, Tier A #A14)
- **Plan ref:** PHASE-3-PLAN.md §2 T-07
- **Автор:** dev-агент (read source + tests + workflow flags, не правил cycle-1/cycle-2 uncommitted work)
- **HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`

## 1. Что сделано

### 1.1 Source change — `src/backend/core/config/features/workflow.py`

Добавлен docstring-маркер `cycle-3/D-AUDIT-07` в class docstring `WorkflowFlags`:

```python
class WorkflowFlags(BaseSettings):
    """K4 — Workflow (K3 K4). Owner: K4 Workflow, K3 Workflow DSL.

    Per S38 T1.3.6, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.workflow import WorkflowFlags
        class FeatureFlags(..., WorkflowFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).

    # cycle-3/D-AUDIT-07: defaults aligned with description "default-OFF"
    # (workflow_legacy_disabled, workflow_yaml_round_trip, workflow_bpmn_import,
    # workflow_gateways_enabled — все default=False, не default=True).
    """
```

### 1.2 Defaults verification — grep подтверждает

```bash
$ grep -nE "workflow_legacy_disabled|workflow_yaml_round_trip|workflow_bpmn_import|workflow_gateways_enabled" \
    src/backend/core/config/features/workflow.py
4:- workflow_legacy_disabled
5:- workflow_yaml_round_trip
6:- workflow_bpmn_import
7:- workflow_gateways_enabled
30:    # (workflow_legacy_disabled, workflow_yaml_round_trip, workflow_bpmn_import,
31:    # workflow_gateways_enabled — все default=False, не default=True).
36:    workflow_legacy_disabled: bool = Field(
47:    workflow_yaml_round_trip: bool = Field(
57:    workflow_bpmn_import: bool = Field(
67:    workflow_gateways_enabled: bool = Field(
```

Все 4 объявления (строки 36, 47, 57, 67) имеют `default=False` — см. §3.

### 1.3 New test file — `tests/unit/core/config/features/test_workflow_flags.py`

Создан (ранее не существовал по этому пути). 4 assertions:

- `test_workflow_legacy_disabled_default_false` — `WorkflowFlags().workflow_legacy_disabled is False`
- `test_workflow_yaml_round_trip_default_false` — `WorkflowFlags().workflow_yaml_round_trip is False`
- `test_workflow_bpmn_import_default_false` — `WorkflowFlags().workflow_bpmn_import is False`
- `test_workflow_gateways_enabled_default_false` — `WorkflowFlags().workflow_gateways_enabled is False`

31 LOC total (с docstring'ом и импортами).

## 2. Diff stat

```
$ git status --short
 M src/backend/core/config/features/workflow.py  (+5 lines cycle-3 marker; -4/+4 default=True→False уже из T-0.1 cycle-1 uncommitted)
?? tests/unit/core/config/features/test_workflow_flags.py  (new file, 31 LOC)

$ git diff --stat src/backend/core/config/features/workflow.py tests/unit/core/config/features/test_workflow_flags.py
 src/backend/core/config/features/workflow.py | 12 ++++++++----
 1 file changed, 8 insertions(+), 4 deletions(-)
```

**Net cycle-3 diff для T-07:**
- `workflow.py`: +5 строк (только docstring marker; default=False — это T-0.1 cycle-1 uncommitted правка, НЕ моя).
- `test_workflow_flags.py`: новый файл, 31 LOC.

## 3. Runtime verification — `.venv/bin/python` (system Python лишён пакетов)

### 3.1 Новый тест-файл

```bash
$ .venv/bin/python -m pytest tests/unit/core/config/features/test_workflow_flags.py -v
...
collected 4 items
tests/unit/core/config/features/test_workflow_flags.py::test_workflow_legacy_disabled_default_false PASSED [ 25%]
tests/unit/core/config/features/test_workflow_flags.py::test_workflow_yaml_round_trip_default_false PASSED [ 50%]
tests/unit/core/config/features/test_workflow_flags.py::test_workflow_bpmn_import_default_false PASSED [ 75%]
tests/unit/core/config/features/test_workflow_flags.py::test_workflow_gateways_enabled_default_false PASSED [100%]
============================== 4 passed in 0.46s ==============================
```

### 3.2 Существующий test (cycle-1 T-0.1 uncommitted, не трогал)

```bash
$ .venv/bin/python -m pytest tests/unit/core/config/test_features_workflow.py -v
...
collected 6 items
tests/unit/core/config/test_features_workflow.py::TestWorkflowFlagsClass::test_workflow_flags_importable PASSED [ 16%]
tests/unit/core/config/test_features_workflow.py::TestWorkflowFlagsClass::test_workflow_flags_instantiates PASSED [ 33%]
tests/unit/core/config/test_features_workflow.py::TestWorkflowFlagsClass::test_workflow_env_vars PASSED [ 50%]
tests/unit/core/config/test_features_workflow.py::TestWorkflowFlagsClass::test_workflow_field_count PASSED [ 66%]
tests/unit/core/config/test_features_workflow.py::TestWorkflowFlagsComposition::test_feature_flags_inherits_workflow_fields PASSED [ 83%]
tests/unit/core/config/test_features_workflow.py::TestWorkflowFlagsComposition::test_feature_flags_class_mro PASSED [100%]
============================== 6 passed in 0.45s ==============================
```

### 3.3 Оба файла вместе

```bash
$ .venv/bin/python -m pytest tests/unit/core/config/features/test_workflow_flags.py \
                          tests/unit/core/config/test_features_workflow.py -v
...
============================== 10 passed in 0.50s ==============================
```

**Python interpreter:** `.venv/bin/python` (Python 3.14.0, pytest-9.1.1, prometheus_client/fastapi/hypothesis installed в venv).

## 4. Preflight + baseline checks

```bash
$ bash tools/cycle-1-preflight.sh
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 35  (T-02 ещё не завершён параллельно; после T-02 → 27)
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 37 entries (pre-existing: cycle-1/cycle-2 uncommitted + parallel T-02/T-08 правки; не атрибутируется T-07)
  [FAIL] uv.lock churn — 45 lines (pre-existing drift, не атрибутируется T-07)
  [OK]   s3.py untouched — не modified
```

Pre-existing failures (`working tree` dirty, `uv.lock churn > 15`) — НЕ вызваны T-07:
- `working tree 37 entries` = 24 modified (cycle-1+cycle-2+cycle-3 T-02+T-08 параллельные) + 12 untracked + 1 (`uv.lock`).
- `uv.lock churn 45 lines` — это drift от parallel T-02 (или cycle-1), не от T-07 (T-07 не трогает uv.lock).
- **T-07 не имеет зависимости от T-01** (per PHASE-3-PLAN.md §2 T-07 "Зависимости: нет"); pre-existing state зафиксирован, не моя зона.

```bash
$ make check-docstrings MAX_ALLOWED=0
uv virtual environment detected
Running docstring policy check...
Total: 0 missing docstrings in 0 files
Files scanned: 838
docstring policy OK
```

```bash
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2274; baseline: 175 legacy)
```

```bash
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
28
```

(28 не 35 потому что parallel T-02 уже удалил 8 stale CVE в uncommitted правке — это не моя зона.)

## 5. Защищённые файлы (НЕ затронуты)

```bash
$ git diff src/backend/infrastructure/storage/s3.py | wc -l
0
$ git diff tools/blue_green.sh | wc -l
0
$ git diff tests/unit/tools/test_blue_green_switch.py | wc -l
0
$ git diff uv.lock | wc -l
45   # pre-existing drift, не атрибутируется T-07
```

## 6. Что НЕ сделано (явно out-of-scope per task)

1. **5 uncommitted cycle-1 правок** (T-0.1, T-1.4, T-1.5, T-3.1) — НЕ переписывал.
   - T-0.1 уже сделал `default=True → default=False` (закоммичено в uncommitted working tree; видно в `git diff` строки 36, 47, 57, 67).
   - Cycle-3 T-07 НЕ дублирует T-0.1 — только добавляет docstring marker (Ponytail YAGNI).
2. **3 uncommitted cycle-2 правки** (T-W1-01, T-W1-05, T-W1-08) — НЕ переписывал.
3. **Pre-existing residual** `services/ai/gateway_adapter.py:128-129` (`except Exception: pass`) — НЕ трогал.
4. **Pre-existing drift** `uv.lock` (-15 svcs), `pip-audit.json`, `.blue_green.state` — НЕ трогал.
5. **Не удалял** `except Exception` без concrete handling — verified, не было такого действия в scope.
6. **s3.py, blue_green.sh, allowlist** — не моя зона (parallel T-02/T-03; uv.lock — pre-existing drift).
7. **Description update для Field(description=...)** — НЕ требовался: descriptions уже
   говорят "default-OFF до миграции ...", что **консистентно** с `default=False`.
   Cycle-1 fix уже синхронизировал descriptions с defaults.
8. **`plugins.py:41-52` (`credit_pipeline_v2`)** — отдельная задача (T-09 в Wave 2), в PHASE-3-PLAN.md явно вынесена отдельно от T-07 per C-2 caveat.

## 7. Cycle-3 DoD (PHASE-3-PLAN.md §8) для T-07

| # | Инвариант | T-07 status |
|---|---|---|
| 1 | Layer checker 175/0 | ✓ (2274 файлов, 0 новых) |
| 2 | Allowlist 27 (после T-02) / 35 (до T-02) | N/A (T-02 scope); current 28 — pre-existing drift от parallel T-02 |
| 3 | Docstring gate 0 missing | ✓ |
| 4 | Runtime `.venv/bin/python -m pytest` | ✓ (10/10 passed на двух файлах) |
| 5 | uv.lock churn не растёт от T-07 | ✓ (T-07 не трогает uv.lock) |
| 6 | Pre-existing drift | ✓ (uv.lock/pip-audit.json/.blue_green.state не атрибутируется) |
| 7 | gateway_adapter.py:128-129 не тронут | ✓ (verified) |
| 8 | Uncommitted cycle-1/2 не переписан | ✓ (T-0.1 default=True→False оставлен as-is) |
| 9 | TM-cascade | N/A (TM относится к T-08, не T-07) |
| 10 | Docstring marker `cycle-3/D-AUDIT-07` | ✓ (в class docstring WorkflowFlags) |
| 11 | Composition root не затронут | ✓ (нет изменений в `src/backend/plugins/composition/`) |

## 8. Возврат родителю

- **Status:** T-07 / C3-07 DONE.
- **Изменённые файлы:** `src/backend/core/config/features/workflow.py` (+5 строк marker) + новый `tests/unit/core/config/features/test_workflow_flags.py` (31 LOC).
- **Diff stat:** `1 file changed, 8 insertions(+), 4 deletions(-)` для workflow.py (4 default=True→False — это T-0.1 cycle-1 uncommitted правка, не моя; моя — только +5 строк docstring marker).
- **Тестовый output:** 4/4 passed на новом файле (Python 3.14.0, `.venv/bin/python`); 6/6 passed на существующем файле (не трогал); 10/10 passed суммарно.
- **Preflight:** exit 1 (pre-existing failures: working tree dirty + uv.lock churn — оба pre-existing drift, не от T-07); layer checker OK, docstring gate OK, s3.py untouched OK.
- **Allowlist:** 28 (parallel T-02 убрал 8 stale CVE; T-07 не меняет allowlist).
- **uv.lock:** не изменён T-07; 45 строк diff — pre-existing drift от cycle-1/2 и parallel T-02.
- **Composition root:** не затронут.
- **Docstring marker:** `# cycle-3/D-AUDIT-07` присутствует в class docstring `WorkflowFlags` (verified via grep).
- **Report path:** `docs/audit/swarm-2026-08-06/cycle-3/cycle-3-D-AUDIT-07-report.md` (этот файл).
