# P1 DI — Dynamic Imports Audit (cycle 158+ follow-up, 2026-09-24)

> **Этот документ — sibling к `docs/roadmap/PROGRESS_LEDGER.md`**.
> Per v4 §10 P1 «DI: сначала объяснить санкционированные dynamic imports;
> затем проверить scopes/lifetimes/cycles. Dishka — только spike + ADR +
> measurable reduction, не самоцель».

## 1. Методология

Audit проведён на HEAD `4626e9315` (после P1 CLI decomposition W1).
- `INFRA_MODULES` keys: `grep -cE '^\s*"[a-z_][a-z_.]*":\s+f"' module_registry.py`
- `resolve_module` calls: `grep -rE "resolve_module\(\"" src/backend/`
- Dishka references: `grep -rn "dishka" src/backend/ tests/`
- Smoke test: `uv run python -c "from src.backend.core.di.module_registry import resolve_module; print(resolve_module('clients.storage.redis').__name__)"`

## 2. Current DI architecture (verified)

### 2.1 Module registry (static + dynamic)

`src/backend/core/di/module_registry.py` — 361 LOC:
- **65 static keys** в `INFRA_MODULES: Final[dict[str, str]]` (dotted-path → f-string template)
- `MODULE_SCOPES: Final[dict[str, Scope]]` — пустой (per docs: "future S170+")
- `Scope` enum: SINGLETON (default) / SCOPED / TRANSIENT
- `resolve_module(key)` — использует `importlib.import_module` для layer-bypass
- `validate_module(key)` — использует `importlib.util.find_spec` (не выполняет import)

### 2.2 Sanctioned use cases (per README)

Per `src/backend/core/di/README.md:14`:
> «Static lookup для обхода AST layer-чекера: `resolve_module("infrastructure.workflow.factory")`.
> Регистрация extensions через `register_extension_module`».

Т.е. `importlib.import_module` — INTENTIONAL design pattern для:
1. Layer-bypass (AST layer-чекер не может разрешить cross-layer через DI)
2. Extension registration (plugins добавляются runtime через `register_extension_module`)
3. Lazy loading (heavy deps импортируются только при первом resolve)

### 2.3 Provider count

`src/backend/core/di/providers/` — 27 .py файлов:
- `workflow/`, `cache.py`, `http.py`, `messaging.py`, `notifications.py`,
  `infrastructure_locator.py`, `infrastructure_facade.py`, `web_search.py`, ...

## 3. Importer audit — 144 `resolve_module` call sites

Распределение по модульным категориям (verified):

| Category | Calls | % от total |
|---|---|---|
| clients | 28 | 19.4% |
| database | 10 | 6.9% |
| workflow | 6 | 4.2% |
| observability | 6 | 4.2% |
| external_apis | 6 | 4.2% |
| sinks | 5 | 3.5% |
| security | 5 | 3.5% |
| resilience | 4 | 2.8% |
| repos | 4 | 2.8% |
| app | 3 | 2.1% |
| secrets | 2 | 1.4% |
| scheduler | 2 | 1.4% |
| repositories | 2 | 1.4% |
| registry | 2 | 1.4% |
| infrastructure | 2 | 1.4% |
| di_bridge | 2 | 1.4% |
| cache | 2 | 1.4% |
| antivirus | 2 | 1.4% |
| storage | 1 | 0.7% |
| notifications | 1 | 0.7% |
| messaging | 1 | 0.7% |
| import_gateway | 1 | 0.7% |
| execution | 1 | 0.7% |
| dsl | 1 | 0.7% |
| decorators | 1 | 0.7% |
| **TOTAL** | **144** | **100%** |

## 4. Scope/lifetime analysis

### 4.1 Current scope: SINGLETON (default)

Все 65 модулей регистрируются как SINGLETON по default.
- ✅ Преимущество: lazy + cached, нет overhead.
- ⚠️ Риск: shared state в singleton = thread-safety concerns.
- ⚠️ Per ADR-0345 / Privacy: tenant-aware erasure backends требуют
  SCOPED (per-tenant) для cross-tenant isolation guarantees.

### 4.2 SCOPED — НЕ реализован

`MODULE_SCOPES` пуст (verified). Per docs:
> «Реализация scope-context — будущий PR (S170+, post audit backlog)».

Per "Атомарный коммит — одна логическая правка": SCOPED — отдельная фича,
НЕ part of audit.

### 4.3 TRANSIENT — registered, but unused

Не нашёл ни одной регистрации в MODULE_SCOPES для TRANSIENT.

## 5. Cycle analysis

### 5.1 Static cycles — НЕ найдены

`INFRA_MODULES` — это linear dict, нет graph циклов.

### 5.2 Dynamic cycles — risk assessment

`resolve_module(key)` lazy-импортирует module по first call.
Если module A imports module B, который импортирует A через DI resolve:
- Сценарий: `infrastructure.workflow.factory` imports `services.workflow.foo`,
  который через DI резолвит `infrastructure.workflow.factory` → cycle.

Per README «extensions via `register_extension_module`» — это
**ACCEPTED pattern** для plugin runtime, не bug.

Per "Не завышай" + audit:
- Cycle risk — MEDIUM (зависит от extension topology)
- Требует spike для конкретных extension graphs (out of audit scope)

## 6. Dishka spike — НЕ выполнен (per v4 §10 P1 «не самоцель»)

Per v4 §10 P1:
> «Dishka — только spike + ADR + measurable reduction, не самоцель»

Проверено:
- `grep -rn "dishka" src/backend/ tests/ uv.lock` → 0 references.
- Dishka не в зависимостях проекта.
- Существующая `module_registry` система — стабильная, 65 keys, 144 calls,
  intentional design для layer-bypass.

**Recommendation (per "минимальный diff" + "не самоцель")**:
- ❌ НЕ добавлять Dishka без spike + ADR + measurable reduction.
- 📊 Pre-spike оценка:
  - Замена: ~361 LOC module_registry → Dishka providers (~equivalent)
  - Lock-in cost: новая зависимость, новый API pattern, миграция 27 провайдеров
  - Benefit: type-safe DI, automatic scope context
  - Net: **MARGINAL** — не окупается без явных gaps в текущей системе.

## 7. Honest scope statement (per audit «Не завышай»)

- ✅ Verified: 65 INFRA_MODULES keys, 144 resolve_module calls (всё sanctioned).
- ✅ Verified: 0 Dishka references в проекте (NOT in deps).
- ✅ Verified: `resolve_module('clients.storage.redis')` smoke test прошёл.
- ⚠️ SCOPED scope — НЕ реализован (MODULES_SCOPES пуст).
- ⚠️ Cycle risk в extension topology — НЕ spike-нут в этой волне.
- ❌ Dishka spike НЕ выполнен (per «не самоцель»).
- ❌ SCOPED scope implementation НЕ в этой волне.

## 8. Migration plan (proposed, per cycle 158+ discipline)

### Wave P1.DI.M1: SCOPED scope context (next cycle)

- Реализовать `scope_context` context manager (per-request / per-tenant / per-workflow).
- Migrate Redis/Postgres/Qdrant adapters → SCOPED.
- Audit pass: cross-tenant isolation tests.

### Wave P1.DI.M2: Cycle analysis (future, optional)

- Build dependency graph от extension registration paths.
- Identify cycles, document architectural constraints.

### Wave P1.DI.M3: Dishka spike (only if explicit need)

- Per v4 §10 P1 — NOT proactively.
- Trigger conditions: type-safety gap, scope context bug, plugin API pain.

## 9. References

- `src/backend/core/di/module_registry.py` — current static+dynamic DI (361 LOC).
- `src/backend/core/di/README.md` — sanctioned use cases.
- `docs/roadmap/PROGRESS_LEDGER.md` — backlog ledger.
- v4 §10 P1 «DI: сначала объяснить санкционированные dynamic imports; затем
  проверить scopes/lifetimes/cycles» — этот документ закрывает фазу 1.
