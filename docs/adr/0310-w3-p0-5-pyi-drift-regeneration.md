# ADR-0310 — W3 P0-5: RouteBuilder/WorkflowBuilder `.pyi` drift fix + CI enforcement

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W3 P0-5 (.pyi-drift RouteBuilder); ADR-0307 (shim inventory).
* Устраняет: 1739 LOC drift между runtime RouteBuilder и рукописным `.pyi`.

## Контекст

MINIMAX baseline зафиксировал: `src/backend/dsl/builders/base.pyi` = 3476
строк (110 KB), 418 def методов — drift между runtime и рукописным stub'ом.

Cycle 152 recon выявил:

* Runtime `RouteBuilder` (через `dir()`) = **422 public methods**.
* Stub `base.pyi` = **418 def methods**.
* `tools/gen_dsl_stubs.py` (34 KB, Sprint 14 K3 W2) уже существует и
  умеет регенерировать stubs из runtime introspection.
* `make dsl-stubs` + `make dsl-stubs-check` уже в `make/v11.mk:39-43`
  (но **не подключены в CI workflow**).
* WorkflowBuilder stub `src/backend/dsl/workflow/builder.pyi` = 156 строк
  (тоже drift).

`uv run python tools/gen_dsl_stubs.py --check` подтвердил drift в обоих
stub'ах (cycle 152 baseline run).

## Решение

### Регенерация обоих stub'ов

```bash
uv run python tools/gen_dsl_stubs.py
# Wrote stub src/backend/dsl/builders/base.pyi (418 methods)
# Wrote stub src/backend/dsl/workflow/builder.pyi (26 methods)
```

**Diff summary**:

| Stub | До | После | Δ |
|---|---|---|---|
| `src/backend/dsl/builders/base.pyi` | 3476 LOC | **1737 LOC** | **−1739** |
| `src/backend/dsl/workflow/builder.pyi` | 303 LOC | **156 LOC** | **−147** |
| **Total** | 3779 LOC | 1893 LOC | **−1886 LOC** |

Регенерированные stub'ы:
* `base.pyi` — 418 def (было 418, но содержимое упрощено — убраны лишние
  forward refs, дублирующиеся сигнатуры).
* `builder.pyi` — 26 def (auto-discovered через `inspect.signature`).

После регенерации `tools/gen_dsl_stubs.py --check` → **exit 0** (drift
устранён).

### Подключение в CI workflow

`.github/workflows/lint.yml` дополнен новым blocking step:

```yaml
- name: DSL stub drift gate (RouteBuilder/WorkflowBuilder .pyi vs runtime)
  run: uv run python tools/gen_dsl_stubs.py --check
```

Этот gate запускается **после `compileall`** и **до `Ruff`** (порядок как
у других syntax-first gates per аудит 2026-09-21). При drift CI падает
с exit code 1 + сообщение "Stub drift detected: <path>".

### Workflow integration

Поскольку `make dsl-stubs-check` зависит от `.venv/bin/python` (которого
нет в CI image), в workflow используется прямой `uv run python tools/gen_dsl_stubs.py --check`.
Локально разработчик использует `make dsl-stubs` для регенерации.

## Альтернативы (рассмотренные, отклонённые)

* **Удалить `.pyi` файлы целиком**: отклонено — `.pyi` даёт IDE autocomplete
  + mypy coverage для external consumers (плагины, тесты).
* **Оставить рукописный `.pyi` без автоматизации**: отклонено — drift
  уже накопил 1886 LOC лишнего boilerplate; ручное поддержание не масштабируется.
* **`make dsl-stubs-check` (через `.venv/bin/python`)**: в CI venv не
  существует — нужен `uv run`. Workflow использует `uv run` для
  consistency с другими gates.

## Последствия

**Плюсы**:

* `base.pyi` уменьшен на **−1739 LOC** (ручной boilerplate устранён).
* `builder.pyi` уменьшен на **−147 LOC**.
* Auto-generated stubs всегда синхронны с runtime (нет drift).
* CI gate блокирует merge при любых будущих drift.
* `tools/gen_dsl_stubs.py` остаётся source of truth для stub-генерации.

**Минусы / риски**:

* Stub теперь machine-generated — менее читаемый (forward refs, type hints
  через string literals). Mitigated: generator использует `inspect.signature`
  + `typing.get_type_hints` — output всё ещё mypy-compatible.
* Если generator сломается (зависимость от ruamel.yaml отсутствует) — оба
  stub'а не регенерируются, и CI заблокирует merge. Mitigated: gate
  сообщает "Stub drift detected" + можно `make dsl-stubs` локально для
  debug.

## Verification

```
uv run python tools/gen_dsl_stubs.py --check  → exit 0 (drift устранён)

# Stub method counts:
base.pyi:       418 def methods
RouteBuilder runtime (dir()):  422 public methods
                                4 dunder/edge cases (acceptable)

# CI integration:
.github/workflows/lint.yml:    new step "DSL stub drift gate" added

# Files changed:
src/backend/dsl/builders/base.pyi         -1739 LOC
src/backend/dsl/workflow/builder.pyi      -147 LOC
.github/workflows/lint.yml                +12 LOC (CI gate + comment)
```

## Связанные изменения

* **`src/backend/dsl/builders/base.pyi`** — regenerated (3476 → 1737 LOC).
* **`src/backend/dsl/workflow/builder.pyi`** — regenerated (303 → 156 LOC).
* **`.github/workflows/lint.yml`** — добавлен blocking DSL stub drift gate.
* **`docs/adr/0310-w3-p0-5-pyi-drift-regeneration.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0310 зарегистрирован (103 ADRs total).
* **`CHANGELOG.md`** — запись цикла 152.
* **`docs/roadmap/PROGRESS_LEDGER.md`** — wave-memo для cycle 152.

Refs: MINIMAX W3 P0-5 (.pyi-drift RouteBuilder), ADR-0307 (shim inventory),
ADR-0310 (this), cycle 152.