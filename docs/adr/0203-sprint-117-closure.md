# ADR-0203: Sprint 117 Closure — Tenant Models Fact-Check (NO-OP)

- **Status:** Accepted (Sprint 117 W1, 2026-06-12)
- **Wave:** s117-w1-factcheck
- **Sprint:** 117

## Context

Sprint 117 plan: 3 tenant models без TenantMixin — `WorkflowEvent`, `DslSnapshot`, `RuleEngine`. Фактчек выявил **3 разных состояния**, не однотипный gap.

## Fact-Check Results

| Model | Location | TenantMixin | State |
|---|---|---|---|
| `WorkflowEvent` | `core/domain/models/workflow_event.py` | ✅ `class WorkflowEvent(BaseModel, TenantMixin)` | closed (S89-S92 pilot) |
| `DslSnapshot` | `core/domain/models/dsl_snapshot.py` | ✅ `class DslSnapshot(BaseModel, TenantMixin)` | closed (S101 W4 — V2 P0 #6) |
| `RuleEngine` | `core/domain/models/rule_engine.py` | ❌ uses own `RuleEngineBase(DeclarativeBase)` | **by-design alternative** |

## D1. WorkflowEvent — closed

S89-S92 tenant migration pilot. `BaseModel + TenantMixin`. No work needed.

## D2. DslSnapshot — closed (S101 W4)

Documented in model: *"S101 W4 (V2 P0 #6): TenantMixin добавлен для multi-tenant blue/green deployments. `tenant_id` backfilled к `"default"` для existing rows"*.

## D3. RuleEngine — by-design alternative pattern

**Не нуждается в TenantMixin**:
- Использует собственный `RuleEngineBase(DeclarativeBase)` — by-design (избегает SQLAlchemy-Continuum для config table).
- `tenant_id` колонка уже есть: `Mapped[str | None] = mapped_column(String(128), nullable=True)` (строка 56).
- Composite unique key включает `tenant_id`: `name + version + tenant_id` (строка 39) — это **explicit multi-tenancy** на schema level.
- TenantMixin даёт auto-filter через SQLAlchemy event listener — это **другой механизм** (transport-layer isolation), не схемный. Для rule_engine config table фильтрация делается вручную в `SQLRuleEngineRepository.list_active()` (см. `infrastructure/repositories/rule_engine_repository.py`).

Это **architectural decision**, не баг. Менять RuleEngine на TenantMixin сломает:
- Изоляцию от SQLAlchemy-Continuum (rule_engine config не нуждается в row-level versioning)
- Composite unique key contract (изменение PK повлечёт data migration)
- Manual filter pattern в repository (уже работает)

## Decision

**S117 = NO-OP**. Все 3 модели либо имеют TenantMixin, либо имеют by-design alternative (RuleEngine).

## Honest Scope

Sprint plan был основан на предположении "3 модели без TenantMixin". Реальность: 2 closed, 1 by-design alternative. NO code changes required.

## Consequences

- **TD closed:** 0 (NO-OP, not action)
- **Score:** 9.8/10 (maintained)
- **S118 next:** docstring ratchet baseline verify

## Honest scope reduction

Это **honest scope reduction** по правилу S58 W6 (ADR-0085): перед выполнением — verify каждое утверждение через find/wc -l/grep. План S117 был **stale** — 3 модели уже tenant-scoped, не нуждаются в изменениях.

Lesson learned: Sprint planning требует fact-check перед W1 (это S61 rule "перед каждой задачей обновляй graphify" + S58 rule "verify каждое утверждение").
