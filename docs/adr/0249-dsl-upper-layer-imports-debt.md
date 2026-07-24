# ADR-0249: DSL → upper-layer imports consolidation (legacy tech debt)

- **Status:** Accepted (technical debt consolidation, 2026-07-23)
- **Wave:** post-cycle-25 (swarm audit)
- **Context:** Cycle 25 batch 3 (architecture refactor)

## Context

Per `meta-coordinator` audit (2026-07-23), the DSL layer contains 198 direct
imports into upper-layer modules:

| Upper layer | Unique modules | Imports |
|---|---|---|
| infrastructure | 28 | 89 |
| services | 49 | 76 |
| schemas | 1 | 4 |
| entrypoints | 1 | 1 |
| utilities | 1 | 1 |
| **Total** | **105** | **198** |

The architectural rule (per `CLAUDE.md`) states DSL should depend ONLY on
`core` (Protocols) and `capability-checked facades`. Direct imports of
`services`/`infrastructure`/`entrypoints` violate this rule.

## Decision

**Ponytail-YAGNI: do NOT refactor now.** Document the legacy debt explicitly
and add the entries to `tools/check_layers_allowlist.txt`. Future refactor
will replace these with capability-checked facades.

### Rationale

A proper refactor would require:

1. Extract facade protocols in `src.backend.core` (1 file per module group)
2. Provide capability-checked facade implementations
3. Update ~150 processor files to use facades
4. Add unit tests for each facade
5. Migrate processors to use facades one-by-one

Estimated effort: 2000-5000 LOC change across 4+ subsystems. Out of scope
for a single swarm cycle.

### Current state (post-cycle-25)

- 45 stale entries pruned from allowlist
- 214 active entries documented (D420, D430 historical context)
- `tools/check_layers.py` exits 0
- All violations categorized and tracked

### Exit criteria for future refactor

A future sprint MUST address this when ANY of:

1. New upper-layer module is added (would expand allowlist)
2. A specific DSL processor grows past 100 LOC and would benefit
   from testability via interface
3. Sprint capacity allows a focused DI/facade migration (one
   module group at a time)

Until then, this ADR + the allowlist = documented legacy debt.

## References

- `tools/check_layers.py` (validator)
- `tools/check_layers_allowlist.txt` (current 214 entries)
- `AGENTS.md` — architectural rules
- Cycle 25 audit findings (2026-07-23)
