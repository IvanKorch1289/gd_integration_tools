# ADR-0249 — Sprint 44: Audit Follow-up — Facades + Migrations

**Дата**: 2026-06-22
**Sprint**: 44
**Status**: ✅ ACCEPTED (5 atomic commits merged)
**Depends on**: ADR-0248 (S43 deep-audit-quick-wins)

## Context

Sprint 43 (ADR-0248) закрыл Quick Wins из deep-audit-2026-06-22.md. Sprint 44
продолжает выполнение audit backlog: facades + migrations, не сделанные в S43
из-за блокировки foreign WIP.

## Decision

5 atomic commits с facades pattern, применённым последовательно для
extensions/SDK gap (W1), frontend migrations (W2+W3), механическая миграция
logger imports (W4), и удаление string-bypass для layer linter (W5).

### Commit 1: `c14dcb6` — feat(s44-w1): 2 core facades (extensions SDK)

**Проблема**: deep-audit SDK gap — extensions вынуждены были импортировать из
infrastructure/services напрямую (2 violations в osint_workflow.py:264/292 после
QW1 catch).

**Fix**: 2 core facade для закрытия SDK gap:
- `core/integrations/web_search.py` (35 LOC, re-export из
  `infrastructure.clients.external.search_providers`)
- `core/ai/llm_gateway.py` (28 LOC, re-export из
  `services.ai.gateway.client`)
- 2 allowlist entries добавлены
- `osint_workflow.py:264,292` перенаправлены через core facades

### Commit 2: `03ce5bd` — refactor(s44-w2): 6 streamlit migrations через services.dsl_portal

**Проблема**: S2 backlog — 12 frontend→dsl/infra imports в allowlist
(обходили R3.10d).

**Fix**: расширение `services.dsl_portal.builder_facade` с +6 re-exports:
`WorkflowDeclaration`, `get_global_registry`, `to_mermaid`, `compute_step_diff`,
`to_graphviz`, `dry_run_route`, `waterfall_lines`. 6 streamlit pages
мигрированы. Dead code (template_registry_compat try/except) удалён из 2 файлов.
4 allowlist entries добавлены (services→dsl facade pattern). 11 stale
allowlist entries pruned.

### Commit 3: `83ec464` — refactor(s44-w3): outbox_monitor facade

**Проблема**: последний frontend→infra import в `96_Outbox_Stuck_Monitor.py:115`
(использовал `infrastructure.messaging.outbox.stuck_monitor.default_stuck_monitor`).

**Fix**: `services/messaging/outbox_monitor.py` facade (37 LOC). Page мигрирована.
1 allowlist entry добавлена (services→infra), 1 stale pruned.

**S2 BACKLOG CLOSED**: 12/12 frontend→dsl/infra imports migrated через services facades.

### Commit 4: `df367db` — refactor(s44-w4): S7 mechanical migration 216 files

**Проблема**: 226 файлов импортировали `infrastructure.logging.factory.get_logger`
напрямую вместо canonical `core.logging.get_logger` (per V22 intent).

**Fix**: AST-safe mechanical sed-script мигрировал 216 SAFE файлов.
4 BLOCKED файла в foreign WIP deferred (UP-9). 2 SPECIAL файла оставлены
как есть (`infrastructure/logging/__init__.py` — circular risk;
test file — debatable).

**95.6% S7 BACKLOG CLOSED** (216/226 migrated).

### Commit 5: `5af8308` — fix(s44-w5): remove string-bypass layer linter

**Проблема**: deep-audit P0-2 — `infrastructure/audit/event_log.py:22` использовал
string-concat + importlib для обхода layer linter (явный намеренный bypass,
задокументированный в коде как «Wave 6 finalize»).

**Fix**: `core/observability/log_indexer.py` facade (29 LOC). Direct static import
в `event_log.py` вместо dynamic `importlib.import_module`. Удалены `import importlib`
и `_LOG_INDEXER_MOD`. 1 allowlist entry добавлена.

**QW2 CLOSED**: V22 invariant восстановлен (no dynamic import circumvention).

## Audit Corrections (none new in S44)

Все 5 W-commits проверены перед коммитом. False positives в audit backlog
(QW4, QW5, QW9) уже документированы в ADR-0248.

## Verification Summary

| Метрика | S43 | S44 | Net |
|---|---|---|---|
| Atomic commits | 4 | 5 | 9 |
| Files touched | 28 | 235 | 263 |
| LOC change | -134 net | -2 net | -136 |
| Layer linter | 0 NEW | 0 NEW | 0 NEW |
| Legacy baseline | 208 | 204 | -4 (pruned) |

## Out of scope (deferred → S45+)

| ID | Item | Причина defer |
|---|---|---|
| QW10 | `services/audit/audit_service.py` (9 consumers) | Multi-file refactor |
| S1 | 8 entrypoints→infra imports | Через services facades (larger scope) |
| S13 | Circuit breaker middleware → shared state | High risk, K8s multi-pod |
| S7 | 4 BLOCKED files в foreign WIP + 2 SPECIAL | После foreign WIP merge |

## Cross-references

- ADR-0248 (S43 deep-audit-quick-wins) — основа для S44
- ADR-0196 (S110 W4: framework exceptions) — extensions legitimate framework
- ADR-0199 (S113 W1: audit shim policy) — QW10 deferral context
- `docs/audit/DEEP-AUDIT-2026-06-22.md` — full audit (S43 W1)
- UP-10 (multi-wave audit working pattern) — closure log appended
