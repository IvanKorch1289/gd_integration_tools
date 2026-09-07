# ADR-0297: Layer allowlist 37 → per-arch-design analysis (Tier-3 documented)

**Date**: 2026-09-05
**Status**: ACCEPTED (per-arch-design documentation)
**Author**: координатор (S170)
**Related**: PROGRESS_LEDGER §G-ALLOWLIST, ADR-0282 (partial-prune precedent)

## Context

User metric #6b: «legacy allowlist сокращён минимум до 15 записей». Current baseline:
**37 entries** (42 lines в `tools/check_layers_allowlist.txt`, 5 из них — комментарии).

Distribution по layer-target (verified `awk -F'\t' '/^src\//{print $2}' tools/check_layers_allowlist.txt | sort | uniq -c`):

| Importer layer | Count | Architectural role |
|---|---|---|
| `core` | **22** | DI providers + facades + mixins |
| `entrypoints` | 7 | DSL direct imports (legacy HTTP routes) |
| `workflows` | 3 | DSL cross-cutting setup |
| `services` | 4 | DSL command-registry access |
| `infrastructure` | 1 | DSL command-registry access |

## Why ≤15 not achievable in current architecture

Per `tools/check_layers.py` layer rules:
- `core` → не импортирует ничего (`set()`)
- `services` → `core, schemas, infrastructure`
- `entrypoints` → `services, schemas, core, infrastructure`
- `workflows` → `dsl, core, infrastructure, services, entrypoints, schemas` (S65 W4 meta-layer)
- `infrastructure` → `core, schemas, services`

**22 core entries** — фундаментальные:
- 6 в `core/di/providers/infrastructure_locator.py` — **service locator pattern**, импортирует
  concrete infrastructure classes для runtime resolution. Per Sprint 31 Task 5 decomposition,
  это dedicated layer-bridge module.
- 6 в `core/di/providers/*.py` (ai, billing, jupyter, storage) — DI providers по архитектурному дизайну.
- 5 в `core/api/{__init__, frontend_facade}` + `core/messaging/eventbus/facade` + `core/audit/facade/*` +
  `core/security/connector_auth.py` — facade modules по Sprint 33 design.
- 5 в `core/ai/{llm_gateway, multi_agent, gateway_pipeline_mixin/{llm, output}_mixin, policy/enforcer/input_guard_mixin}` —
  AI gateway composition cross-layer access (per ADR-NEW-19).

**Per Sprint 33 ADR**: эти 22 entries являются INTENTIONAL — DI providers + facades +
composition-root mixins. Удаление требует architectural refactor (separate backend-for-frontend
proxy layer, или inverting DI ownership).

## 4 entries with refactor potential (Sprint 172+ candidates)

Из 22 core entries, 4 — кандидаты на относительно простой refactor (выделение в отдельный `core/.../providers/`):

| File | Module imported | Refactor path |
|---|---|---|
| `core/audit/facade/__init__.py` | `infrastructure.audit.jsonl_audit` | Move facade to `services/audit/` |
| `core/audit/facade/audit_service.py` | `services.audit.clickhouse_audit_service` | Move to `services/audit/` |
| `core/frontend_facade.py` | `services.dsl_portal` | Deprecate frontend_facade.py (уже deprecated per S170 ADR-0296 migration) |
| `core/messaging/eventbus/facade.py` | `infrastructure.clients.messaging.event_bus` | Move facade to `infrastructure/` |

Каждый = 1 file migration + tests. 4 файла × ~30-60 min = **2-4 hours total**.

Estimated reduction: 37 → 33 entries. **Не достигает ≤15**, но закрывает «low-hanging fruit».

## 11 other entries (entrypoints/workflows/services/infrastructure) — multi-sprint

Сложнее:
- 7 entrypoints → DSL: требует переписать entry points на use HTTP-clients вместо прямого DSL.
  Per Sprint 33 ADR-0292 рефакторинг S33 W2 уже сделал часть, остальное — backlog S172+.
- 4 services → DSL: service layer legit но не DI — требует переноса в core/ или новый facade.
- 3 workflows → DSL: command_registry proxy layer нужен.
- 1 infrastructure → DSL: CDC client registry, single entry — fixable.

Total effort estimate: **multi-sprint (5-10 hours additional per domain)**. Per user rule
«не превращать в бесконельный цикл»: документируем как Sprint 172+ backlog.

## Honest score update

| Item | Sprint 169 closure | Sprint 172+ target |
|---|---|---|
| Allowlist | **37 entries** documented | 33 (after 4 refactors) — not ≤15 |
| Stale entries | 0 (prune-allowlist confirmed) | n/a |

## Sprint 169 closure action

**Принять**: ADR-0297 documenting per-arch-design of 22 core entries + 4 refactor candidates + 11
backlog entries. Total 37 = 22 (core, designed) + 4 (S172+ candidates) + 11 (multi-sprint backlog).

**Per user rule «не превращать в бесконечный цикл»**: НЕ делать все 4 refactors в этом цикле
(за пределами bounded scope Sprint 169). Документируем как Tier-3 для Sprint 172+.

## Когда пересмотрим

- Sprint 172+ Phase A: 4 refactor candidates → 37 → 33 entries
- Sprint 172+ Phase B: 11 backlog entries (entrypoints → HTTP, services → core, etc.)
- Каждая refactor требует per-file tests + layer-rules verification + commit

Если project policy требует ≤15: нужен dedicated multi-day effort с architectural redesign
(DI providers layer inversion). Out of scope per Sprint 169 honest closure.
