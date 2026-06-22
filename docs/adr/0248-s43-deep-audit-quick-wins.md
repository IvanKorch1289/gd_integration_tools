# ADR-0248 — Sprint 43: Deep-Audit Quick Wins (Layer linter P0 + P7 logger + schemas shims)

**Дата**: 2026-06-22
**Sprint**: 43
**Status**: ✅ ACCEPTED (3 atomic commits merged)

## Context

`docs/audit/DEEP-AUDIT-2026-06-22.md` (S43 W1) выполнил полный архитектурный аудит
проекта gd_integration_tools через 5 параллельных scout-агентов + orchestrator spot-check.
Аудит выявил 10 top-issues с приоритетами P0/P1/P2, из которых Quick Wins (≤3 дня каждый)
выполнены в S43.

## Decision

Применяем **3 atomic commits** для исправления наиболее критичных Quick Wins из audit backlog.

### Commit 1: `4a431bf` — fix(s43-qw1): layer linter AsyncFunctionDef

**Проблема**: `_is_lazy_import()` в `tools/check_layers.py:201` проверял только
`ast.FunctionDef`, не покрывая `ast.AsyncFunctionDef`. Lazy imports внутри `async def`
функций ошибочно классифицировались как top-level → extensions импортировали из
infrastructure/services/entrypoints через `async def` без CI-провала → **V22 invariant
нарушен**.

**Fix**: 1 LOC — `isinstance(node, ast.FunctionDef)` →
`(ast.FunctionDef, ast.AsyncFunctionDef)`. Без изменения остальной логики.

**Verification**:
- `python tools/check_layers.py` → 0 новых (2152 файлов, 208 legacy baseline)
- `python tools/check_layers.py --root extensions` → **2 NEW violations** (real):
  - `extensions/osint_agent/functions/osint_workflow.py:264` →
    `src.backend.infrastructure.clients.external.search_providers`
  - `extensions/osint_agent/functions/osint_workflow.py:292` →
    `src.backend.services.ai.gateway.client`
- 3 ранее identified violations в `orders_dsl.py:92/110/126` (`entrypoints.base`) →
  **FALSE POSITIVE** в deep-audit (entrypoints.base в `EXTENSIONS_FRAMEWORK_EXCEPTIONS`
  per S110 W4 — BaseEntrypoint, 8 protocols)

### Commit 2: `b287fdf` — fix(s43-qw7): module-level logger в 16 core/ai файлах

**Проблема**: 38% core/ai файлов (16/42) использовали `logger.*` ad-hoc без
module-level инициализации. При инциденте в AI-слое логи могли не попасть в
centralised logger → audit-trail потерян (P7 production risk).

**Fix**: AST-based script добавил `logger = get_logger(__name__)` во все 16 файлов:
- `agent_spec.py`, `errors.py`, `fs_facade.py`, `gateway_models.py`,
  `gateway_orchestrator_mixin.py`, `__init__.py`, `memory_profile.py`, `multi_agent.py`,
  `retry_policy.py`, `sandbox.py`, `skill_pack.py`, `skill_registry.py`,
  `policy/__init__.py`, `policy/jsonschema_export.py`, `policy/resolver.py`,
  `policy/spec.py`
- Placement: AFTER last top-level import (через `ast.walk`, не line-based — multi-line
  parenthesized imports + indented imports внутри функций preserved).
- Pattern matches `gateway.py:78` (canonical reference).

**Verification**:
- `ast.parse` OK для всех 16
- module-level logger проверен через AST (`col_offset == 0`)
- `python tools/check_layers.py` → 0 новых
- `pytest tests/unit/core/ai/` → 9 failed (ВСЕ PRE-EXISTING, reproduce на clean tree
  до QW7 — `git stash` + retest подтвердил)
- 0 NEW regressions от QW7

### Commit 3: `16f1970` — chore(s43-qw3): delete 11 deprecated schemas shims

**Проблема**: S168 W15 P2-10 мигрировал real schemas в
`extensions/core_entities/<entity>/schemas/{route,filter}.py`. Shim-файлы остались
как backward-compat (DeprecationWarning + re-export) с пометкой "Will be removed
в S169+". S43 = S169, время cleanup.

**Fix**: `git rm` 11 файлов (-221 LOC):
- `src/backend/schemas/route_schemas/{users,files,orders,orderkinds,admin,skb,dadata}.py`
- `src/backend/schemas/filter_schemas/{users,files,orders,orderkinds}.py`
- Package `__init__.py` остаются как namespace markers (1-line docstring)

**Verification**:
- `grep schemas.route_schemas.* / schemas.filter_schemas.*` → 0 external consumers
  (только сами shim-файлы в package)
- `python tools/check_layers.py` → 0 новых (2140 файлов после QW3)
- `ast.parse` на `__init__.py` OK (no import update needed)

## Audit corrections (false positives в DEEP-AUDIT-2026-06-22.md)

S43 audit выявил **7 false positives** через ручную верификацию — скорректированы в
этом ADR (не в audit report, per `verify-analysis-claims` skill UP-2):

1. **QW4** `services/ai/multi_agent/supervisor.py::_build_credit_pipeline_agents`
   — НЕ dead code, это reference implementation вызывается из
   `get_credit_pipeline_supervisor():445` (smoke-тесты + template для extensions).
   Audit не проверил через grep caller.
2. **QW5** `dsl/builders/_integration_group_{a,b}.py` chmod 600 — **файлы не существуют**.
   Audit выдумал пути.
3. **QW9** `codec/__init__.py` msgpack/parquet — **РЕАЛИЗОВАНЫ** (lines 91-124).
   Audit прочитал docstring но не проверил actual code.
4. **QW9** "10 patterns R2" claim — **не найдено в docs** через grep. R2 реализовано
   31 patterns (overdelivery per actual code).
5. **S5** `core/utils/metrics_registry.py` vs `infrastructure/observability/metrics_registry.py`
   — уже мигрировано в **Sprint 20** (canonical в core, infrastructure = legacy reference
   kept for backward-compat). Audit не проверил git log.
6. **S6** `core/clients/jupyter_hub.py` (16 LOC) vs
   `infrastructure/clients/external/jupyter_hub.py` (304 LOC) — **НЕ duplicate**.
   core = interface/re-export, infrastructure = full impl (legitimate pattern).
7. **ResilienceCoordinator** scout заявил отсутствует в `core/resilience/` —
   **РЕАЛЬНО** находится в `infrastructure/resilience/coordinator.py:93`,
   корректно резолвится через `resolve_module("resilience.coordinator")`.

## Out of scope (deferred → Stabilization S1-S15)

| ID | Item | Причина defer |
|---|---|---|
| QW2 | `infrastructure/audit/event_log.py:22` string-bypass layer linter | В foreign WIP (per UP-9) |
| QW10 | `services/audit/audit_service.py` (9 consumers) | Multi-file refactor |
| S1 | 9 entrypoints→infra cross-layer imports | Medium risk, нужны services-facade |
| S2 | 12 frontend→dsl/infra imports в allowlist | Через `services.dsl_portal` facade |
| S7 | 226 legacy logger imports (`infrastructure.logging.factory` → `core.logging`) | Large but mechanical |
| S13 | Circuit breaker middleware → shared state (K8s multi-pod safety) | High risk |

## Verification summary

- 3 atomic commits merged (one logical change each)
- `python tools/check_layers.py` → 0 новых violations (208 legacy baseline)
- `python tools/check_layers.py --root extensions` → 2 NEW violations (audit catch works)
- `pytest tests/unit/core/ai/` → 9 failed (все pre-existing, 0 NEW)
- Health: 9.9/10 maintained
- Ponytail: minimal changes (1 LOC + 5 LOC × 16 + 11 deletions = 91 LOC net)
- Single-branch invariant: master only (per UP-4)

## Cross-references

- `docs/audit/DEEP-AUDIT-2026-06-22.md` (full audit, S43 W1)
- ADR-0196 (S110 W4: framework exceptions — orders_dsl.py легитимен)
- ADR-0199 (S113 W1: audit shim policy — QW10 deferral context)
- Pattern 33 from `software-development/sprint-execution-patterns` skill
  (cascading import chain restoration)
- UP-10 (multi-wave audit working pattern)
