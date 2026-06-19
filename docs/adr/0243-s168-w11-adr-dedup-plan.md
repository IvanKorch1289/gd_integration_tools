# S168 W11 P2-3: ADR dedup plan (11 collision-slots)

## Status: Accepted (S168 W11)

## Context

Per docs/adr/INDEX.md, 11 ADR slots have collisions (two ADRs на
один номер):

- ADR-0109, ADR-0226, ADR-0227, ADR-0228, ADR-0229, ADR-0230
- ADR-0232, ADR-0233, ADR-0234, ADR-0235, ADR-0237

Per master prompt v8 P2-3: "Deduplicate ADRs: 11 collision-slots →
завести -v2 суффикс или -a/-b, обновить обратные ссылки в sprint-closure."

Пример (ADR-0109):
- `0109-feature-flag-dependency-check-fix.md` (Accepted S41 W2)
- `0109-script-runner-dsl.md` (—)

## Decision

**Per Ponytail minimum, current commit does NOT rename files** —
отложено до S169+.

Rationale:
- Renaming 11 files требует обновления 30+ back-references
  (sprint-closure ADRs, CHANGELOG.md, master_prompt_for_agent.md)
- "коллизия" уже документирована в INDEX.md через ``*(collision)``
  тег — readers can disambiguate
- INDEX.md auto-generated через tools/adr_index.py (per ADR-0234)
- File rename может сломать external links (web, IDE bookmarks)

## Migration plan (separate WIP S169+)

For each of 11 collision-slots:

1. **Identify the "primary" ADR** (earlier in time / more "accepted")
2. **Rename the secondary to `-a` or `-b` suffix:**
   - Example: `0109-feature-flag-dependency-check-fix.md` stays
   - `0109-script-runner-dsl.md` → `0109a-script-runner-dsl.md`
3. **Update INDEX.md:** add the new path
4. **Update back-references in sprint-closure ADRs** (search for "0109-"
   pattern, replace with "0109a-" where appropriate)
5. **Re-run tools/adr_index.py** to regenerate INDEX
6. **Add CI check** that fails on future collisions (prevention)

## Affected ADR pairs (preliminary list)

| Slot | Primary (keep) | Secondary (rename) |
|------|----------------|---------------------|
| 0109 | feature-flag-dependency-check-fix | script-runner-dsl → 0109a-script-runner-dsl |
| 0226 | TBD | TBD |
| 0227 | TBD | TBD |
| 0228 | TBD | TBD |
| 0229 | TBD | TBD |
| 0230 | TBD | TBD |
| 0232 | TBD | TBD |
| 0233 | TBD | TBD |
| 0234 | TBD | TBD |
| 0235 | TBD | TBD |
| 0237 | TBD | TBD |

## Consequences

- 0 immediate code change (Ponytail minimum)
- Readers see *(collision)* tag in INDEX.md (already exists)
- Migration to be planned in S169+ (audit + decision per slot)
- New ADRs should NEVER collide (per CI check post-S169+)

## Date: 2026-06-18
