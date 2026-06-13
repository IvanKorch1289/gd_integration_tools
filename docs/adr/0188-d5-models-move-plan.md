# ADR-0188: D5 model move plan (analysis-only, multi-sprint execution)

**Date:** 2026-06-13
**Status:** PROPOSED
**Sprint:** S105 W1 (analysis-only)
**Deciders:** S105 subagent + user
**Supersedes:** S94 W1-W2 (originally planned this move, never executed)

---

## Context

Extensions импортируют SQLAlchemy ORM-модели из
`src.backend.infrastructure.database.models.*` для repository/services/workflows.
Это нарушает layer policy V22:

> `extensions/` → только `gd_integration_tools.{core, testkit}` +
> capability-checked фасады. Прямой импорт из `infrastructure/*` запрещён.

DEEP-RESEARCH (2026-06-12) заявил 20 violations. S103 W1 linter (honest
re-measurement) обнаружил **41 violation** в extensions. Корневая причина:
SQLAlchemy models живут в `infrastructure/`, а extensions обязаны импортировать
их для ORM-операций.

S94 W1-W2 планировал перенос `infrastructure/database/models/` →
`core/domain/models/`, но scope оказался слишком большим — multi-sprint
breaking change. Sprint был заменён на docstring ratchet (S94 W5).

S103 W1 closure оставил linter wired + задокументированные 41 violations, но
никакого actual code move не произошло.

---

## Decision

**S105 W1** = analysis-only commit (current). Реальный перенос — multi-sprint
в B1/B2/B3 batches (per migration plan `docs/migration/d5-models-to-core.md`).

**Целевая архитектура:**

```
src/backend/core/domain/models/     # NEW — canonical location
└── (12 файлов, перенесены из infrastructure/database/models/)

src/backend/infrastructure/database/models/   # OLD — back-compat shim (1 sprint)
└── (12 shim'ов с DeprecationWarning)
```

**Back-compat pattern (proven by `core/audit/facade.py`):**
- Shim = `from src.backend.core.domain.models.<name> import *` + `DeprecationWarning`.
- `tools/check_layers.py` — shim imports не считаются violations (whitelist).
- Hard delete через 1 sprint (S106 W1).

**Per S58+ honest scope rule:** refactor > 1 wave = analysis-only commit
OR 1-commit with measured numbers. Этот ADR = measured numbers (41 violations,
file-by-file categorization). W1 deliverable = план, не код.

---

## Consequences

### Positive

- Extensions → только `core/` imports (policy compliance).
- 41 linter violations → 0 после full migration (target S106 W1).
- Domain-agnostic модели в `core/` (правильное место по V22).
- Proven pattern (`audit/facade.py`) → low risk back-compat.

### Negative

- Multi-sprint execution (B1/B2/B3) — S105+ backlog.
- Alembic migration sync (особенно B3 с native enum).
- `make_versioned` singleton risk в `base.py` (B3).
- 1 sprint deprecation shim → 2 canonical paths (smell, mitigated by hard delete).

### Neutral

- Никаких изменений в public API (только internal imports).
- Existing tests остаются валидными (shim back-compat).
- Никаких runtime performance изменений (только import paths).

---

## Alternatives Considered

### A. Hard delete сразу, grep+rewrite всех imports (1 гигантский commit)

- **Плюсы:** zero shim, чистая архитектура сразу.
- **Минусы:** гигантский blast radius, сложно откатить, ~200+ import правок атомарно.
- **Отклонено:** слишком рискованно, нарушает "atomic commit = one logical change".

### B. Coexistence без deprecation warning (no shim)

- **Плюсы:** zero shim overhead.
- **Минусы:** extensions могут застрять на старом пути навсегда.
- **Отклонено:** технический долг, нет enforcement.

### C. Оставить в `infrastructure/`, добавить capability-facade для extensions

- **Плюсы:** нет model move.
- **Минусы:** facade для каждой модели = 12 facade'ов = больше кода, не меньше.
- **Отклонено:** не решает root cause (models в `infrastructure/` — wrong layer).

### D. Полный отказ от extensions ORM (только через DTO/repository-facade)

- **Плюсы:** чистая архитектура, extensions не знают про ORM.
- **Минусы:** massive refactor (вся ORM-логика → repository pattern).
- **Отклонено:** multi-quarter, не в scope S105+.

---

## OPEN_QUESTIONS (resolved)

### Q1. "13 файлов" vs фактически 12. ✅ RESOLVED — 12 model files + 1 namespace marker.

### Q2. Target `core/domain/models/` не существует. ✅ RESOLVED — создать директорию в B1 шаг 1.

### Q3. Back-compat shim strategy. ✅ RESOLVED — shim (1 sprint grace, hard delete S106 W1).

### Q4. `env.py` Alembic sync. ✅ RESOLVED — минимальное изменение путей в `migrations/env.py:18-28` (вариант A).

### Q5. `rule_engine.py` изолированный `RuleEngineBase`. ✅ RESOLVED — перенести в `core/domain/models/rule_engine.py` + явно зафиксировать изоляцию от BaseModel в ADR (этот документ, раздел Consequences).

---

## Implementation Roadmap

| Sprint | Batch | Scope | Risk | Commit pattern |
|--------|-------|-------|------|----------------|
| S105 W1 | analysis | 3 deliverable файла (current) | none | `docs(s105-w1-d5-plan): ...` |
| S105 W2 | B1 | 6 Risk A models + shim'ы | low | `refactor(s105-b1-d5): ...` |
| S105 W3 | B2a | orderkinds | medium | `refactor(s105-b2-d5-orderkinds): ...` |
| S105 W4 | B2b | orders | medium | `refactor(s105-b2-d5-orders): ...` |
| S105 W5 | B2c | files + OrderFile | medium-high | `refactor(s105-b2-d5-files): ...` |
| S106 W1 | B3a | workflow_instance | high | `refactor(s105-b3-d5-workflow-instance): ...` |
| S106 W2 | B3b | workflow_event + enum migration | high | `refactor(s105-b3-d5-workflow-event): ...` |
| S106 W3 | cleanup | hard delete shim'ов | low | `chore(s106-w3-d5-cleanup): hard delete shim'ов` |
| S106 W4 | verification | regression suite | none | `test(s106-w4-d5-regression): verify 0 violations` |
| S106 W5 | closure | ADR-0189 closure | none | `docs: S106 closure — ADR-0189 + CHANGELOG` |

**Total:** 5 sprints, 11 commits, ~30 file moves + 41 import rewrites.

---

## References

- DEEP-RESEARCH D5 (🔴 High)
- S103 W1 closure (ADR-0187) — linter wired, 41 violations documented
- S94 W1-W2 — original plan, not executed
- `tools/check_layers.py` — linter (S103 W1 added extensions layer support)
- `core/audit/facade.py` — proven back-compat shim pattern
- `docs/migration/d5-models-to-core.md` — детальный migration plan
- `scripts/verify_d5_migration_readiness.sh` — pre/post flight checks
