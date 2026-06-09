# ADR-0107: transport.py god-object decomposition (990 LOC → 6 modules)

**Date:** 2026-06-09
**Status:** Draft (S84 W2 B1+B2 landed, B3-B5 deferred S85+)
**Sprint:** S84
**Deciders:** platform team
**Related:** ADR-0102 (ai_processors pattern), ADR-0105 (lifecycle.py pattern),
R-V15-9 (WorkflowBuilder)

## Context

S80 W1 audit found 4 god-objects >1000 LOC. S82 закрыл lifecycle.py (1142
→ 5 files). После S82 — следующие по размеру:

```
990  src/backend/dsl/builders/transport.py
986  src/backend/entrypoints/api/generator/actions.py
828  src/backend/dsl/engine/processors/ai_banking.py
823  src/backend/dsl/engine/processors/rpa.py
```

S84 W2 B1+B2 — **первый шаг decomp transport.py** (32 methods, 990 LOC,
single class `TransportMixin`).

**Mixed concerns** в одном файле:
1. Proxy / forward / redirect (`expose_proxy`, `forward_to`, `proxy`, `redirect`)
2. External services (HTTP, GraphQL, web search)
3. Persistence (db, JDBC, file, S3) — 9 methods
4. Scheduling (timer, poll, directory_scan)
5. Sinks (10 outbound публикаций) — 10 methods, ~350 LOC
6. Sources (WebDAV, NATS JetStream) — 3 methods

## Decision

**Decompose** `transport.py` (990 LOC, 32 methods) → `dsl/builders/transport/`
package с 6 модулями (per S82 lifecycle pattern), 4-wave plan:

```
src/backend/dsl/builders/transport/
├── __init__.py       (518 LOC) — TransportMixin (22-9=13 non-extracted) + MRO composition
├── sinks.py          (379 LOC) — SinksMixin: 10 sink_* (S84 W2 B1) ✅
├── persistence.py    (162 LOC) — PersistenceMixin: 9 db/file/storage (S84 W2 B2) ✅
├── proxy.py          (TBD)    — ProxyMixin: expose_proxy, forward_to, proxy, redirect (S85+)
├── external.py       (TBD)    — ExternalServicesMixin: http_call, graphql_query, web_search (S85+)
├── scheduling.py     (TBD)    — SchedulingMixin: timer, poll, directory_scan (S85+)
└── sources.py        (TBD)    — SourcesMixin: from_webdav, from_nats_js, to_nats_js (S85+)
```

**Pattern** (per S82 lifecycle + eip.py decomp):
1. Sub-module = `*Mixin` class с метододами одной concern.
2. `TransportMixin(*Mixin)` композитный через MRO (stateless).
3. Backward-compat: `from src.backend.dsl.builders.transport import TransportMixin`
   работает как раньше.

## S84 progress (B1+B2 landed)

| Wave | Scope | Result | Verification |
|------|-------|--------|--------------|
| **B1** | sinks.py (10 methods) | transport.py 990 → 647 LOC, sinks.py 379 LOC | mypy/ruff clean, MRO verified |
| **B2** | persistence.py (9 methods) | __init__.py 647 → 518 LOC, persistence.py 162 LOC | mypy/ruff clean, MRO verified |
| **Total** | 19/32 methods extracted (60%) | transport.py 990 → 518 LOC (1.9x reduction) | mypy/ruff clean, 32 methods preserved |

## S85+ backlog (per S84 W2 W4 plan)

- **B3**: extract `proxy.py` (4 methods, ~95 LOC) + `scheduling.py` (3 methods, ~70 LOC)
  → __init__.py 518 → ~350 LOC
- **B4**: extract `external.py` (3 methods, ~70 LOC) + `sources.py` (3 methods, ~155 LOC)
  → __init__.py 350 → ~80 LOC (compositional re-export only)
- **B5**: closure commit + ADR-0107 final status update

After B5: `transport/` package = 6 sub-modules, ~80 LOC __init__.py composition
shell. Total LOC = 990 (no actual reduction, just modularization).

## Consequences

### Positive

- **S84 B1+B2 landed**: 19/32 methods extracted, transport.py 990 → 518 LOC
  (1.9x reduction in main file).
- **Sub-module ownership**: sinks (10 methods) и persistence (9 methods)
  теперь independent testable sub-modules.
- **Backward-compat preserved**: `from src.backend.dsl.builders.transport
  import TransportMixin` работает как раньше; 32 methods все ещё
  доступны через MRO composition.
- **MRO**: `TransportMixin → PersistenceMixin → SinksMixin → object`
  (явная цепочка composition).

### Negative

- **No total LOC reduction**: total = 990 → 1026 (sinks) + 541 (__init__ + persistence)
  = 1567 LOC (1.6x growth из-за docstrings, MRO, type hints). Это
  acceptable per S82 lifecycle pattern (где total вырос 1142 → 1274).
- **Cross-cutting concerns**: some methods (e.g. file_move) тематически
  между persistence и scheduling. B1+B2 остановились на
  persistence (имя `file_move` → там).
- **Per-S82 pattern**: B3-B5 требуют ещё 3 волны (5 total для full decomp).
  S84 = 2/5 + ADR-0107 draft. S85+ backlog = 3 more waves.

### Neutral

- **Sprint number drift**: "B1" / "B2" в commit messages соответствуют
  S84 sub-waves. Не sprint number drift — это decomposition step labels.
- **S83 closure commit** (d42c550d) уже включал transport.py-related
  S3 fix (s3.py, не transport.py). No overlap.

## Verification

- `mypy src/backend/dsl/builders/transport/` — **0 errors** (3 files)
- `ruff check src/backend/dsl/builders/transport/` — **0 errors** (3 files)
- Import test: `from src.backend.dsl.builders.transport import TransportMixin`
  works, all 32 methods accessible via MRO.
- Backward compat: `src/backend/dsl/builders/integration.py` imports
  `TransportMixin` — no changes needed.

## References

- ADR-0105: lifecycle.py decomposition (S82 pattern, 4 working waves + closure)
- ADR-0102: ai_processors decomposition (S80/S81 pattern, ai_processors 1164→87 LOC)
- S77 W3: 31_DSL_Visual_Editor split 1269→1082 LOC (partial decomp pattern)
- R-V15-9: WorkflowBuilder DSL
- S80 W1 audit: 4 god-objects >1000 LOC → S82+S84 closure plan
