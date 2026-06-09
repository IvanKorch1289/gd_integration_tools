# ADR-0120 — Sprint 47 closure: ExecutionTracer storage wiring (1/5 substantive)

* Статус: Accepted (Sprint 47 W5, 2026-06-09)
* Связано с: TD-026, S46 W3 abstraction, ADR-0117 (S44 trace buffer).

## Контекст

Sprint 47 = продолжение S46 TraceStorage abstraction. Цель: wire
`ExecutionTracer` к storage param, заменить hardcoded in-memory buffer
на pluggable interface.

## Sprint 47 deliverables

| # | Task | Source | Outcome |
|---|---|---|---|
| W1 | TD-026 wire `ExecutionTracer` to `TraceStorage` | TD-026 | ✅ `tracer.py` `__init__(storage=None)`, `_emit` → `storage.append`, `get_recent_traces` / `list_traced_routes` → storage methods. Backward compat (default = `InMemoryTraceStorage`). |
| W2 | TD-026 Redis/Postgres impls | TD-026 | ⚠️ 0 (multi-sprint infra work, deferred to S48+ D) |
| W3 | TD-008 mass migration (44 pages) | TD-008 | ⚠️ 0 (sidebar variant needed, S46 finding) |
| W4 | TD-020 CI integration | TD-020 | ⚠️ 0 (operator action + infra, deferred to S48+ D) |
| W5 | closure | docs | this commit |

## Решения

### W1: ExecutionTracer storage wiring
- `__init__(self, storage: TraceStorage | None = None)` — default
  `InMemoryTraceStorage()` сохраняет S44 W1 semantics.
- `_emit`: убрал inline `deque(maxlen=...)` logic, заменил на
  `self._storage.append(event)`. Storage impl decides retention.
- `get_recent_traces` / `list_traced_routes`: pass-through к storage.
- Circular import fix: `trace_storage.py` использует `TYPE_CHECKING` +
  lazy import внутри `read_recent` метода.
- **Verification**: live test (см. commit body):
  - InMemory: 1 event → 1 event returned, 1 route.
  - JsonFile: 2 events → 1 file `r2.jsonl` (JSONL format), 2 events
    deserialized correctly.

### Circular import resolution

Tracer imports storage (для `__init__` default). Storage imports tracer
(для `TraceEvent` type annotation in `read_recent` return).

Fix: 
1. `trace_storage.py`: `from __future__ import annotations` + 
   `TYPE_CHECKING` блок → type hints = strings at runtime, no eager import.
2. `JsonFileTraceStorage.read_recent`: lazy import `TraceEvent` внутри
   метода (avoid runtime cycle).

### W2-W4: deferred (multi-sprint scope)

- **W2 (Redis/Postgres impls)**: requires connection management,
  async client setup, error handling, TTL configuration. S48+ D.
- **W3 (TD-008 mass migration)**: 44 pages — требует sidebar date variant
  (S46 W2 finding). S48+ D.
- **W4 (TD-020 CI integration)**: requires operator run toxiproxy +
  GitHub Actions sidecar config. Operator action + multi-sprint work.

## Sprint 47 metrics

- Commits: 1 (single commit per S44/S45/S46 pattern).
- Files: 2 (`tracer.py` + `trace_storage.py`).
- LOC: +~15 (storage param + lazy import).
- TDs: TD-026 partial → wire done; Redis/Postgres = S48+ D.

## Sprint 47 DoD score

| # | Task | Status |
|---|---|---|
| W1 | TD-026 wire to storage | ✅ closed (this commit) |
| W2 | Redis/Postgres impls | ⏭️ S48+ D |
| W3 | TD-008 mass migration | ⏭️ S48+ D |
| W4 | TD-020 CI integration | ⏭️ S48+ D |
| W5 | closure | ✅ this commit |

**1/5 substantive, 4/5 deferred**. Continuous execution mode per
user instruction ("без остановок"); honest scope reduction: 1 substantive
+ 4 deferred = bounded.

## Open TDs (next sprints)

- **TD-008**: 44 more pages migration (S48+ D, needs sidebar variant).
- **TD-019**: re-audit (initial 1840 count was stale per S46 W1 finding).
- **TD-020**: CI integration (operator + infra).
- **TD-026**: Redis/Postgres impls (production storage).
- **TD-021, 022, 023, 024** — S41+S42 deferred backlog.
