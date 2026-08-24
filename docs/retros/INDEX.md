# Sprint Retrospectives — `docs/retros/`

> **Purpose**: Index of per-sprint retrospectives. Each retro captures
> wins, losses, lessons, and process changes within a bounded time
> window. Use this index to navigate retrospective archive.
>
> **Updated**: 2026-08-30 (Sprint 44 close, after W9 wrap-up commit
> `61c72300`).

## Sprint retrospective chronology

| Date | Sprint | Document | Commits covered |
|---|---|---|---|
| 2026-07-01 | S172-S177 | `SPRINT_S177_RETROSPECTIVE.md` (older) | 32 commits, 6 sprints |

## Sprint 43 (2026-08-30, single-day intensive)

| Wave | Document | Focus |
|---|---|---|
| W1-W3 | [`SPRINT_43_W1-W3_RETRO_2026-08-30.md`](./SPRINT_43_W1-W3_RETRO_2026-08-30.md) | Layer fix + stubs regen + GraphQL skipxfail + STATUS.md + DEPENDABOT_REVIEW + graphql_router + agent_security 5/5 + R12 update |

## Sprint 44 (2026-08-30, single-day intensive)

| Wave | Document | Focus |
|---|---|---|
| W1-W4 | [`SPRINT_44_W1-W4_RETRO_2026-08-30.md`](./SPRINT_44_W1-W4_RETRO_2026-08-30.md) | L5 chain restoration + 3 R12 FALSE CLAIMs retracted + live HTTP smoke + real coverage measurement |
| W5-W8 | [`SPRINT_44_W5-W8_RETRO_2026-08-30.md`](./SPRINT_44_W5-W8_RETRO_2026-08-30.md) | Multi-agent synthesis + admin services 100% coverage + clickhouse_admin bug fix |

## Per-wave inventory (Sprint 44)

| Wave | Wins | Losses | Lessons | Process changes |
|---|---:|---:|---:|---:|
| W1-W4 | 5 | 3 | 6 | 3 |
| W5-W8 | 6 | 4 | 4 | 3 |

## How to use these retros

1. **For first read of a sprint**: start with the wave retrospective.
2. **For specific finding**: search within the retrospective for the
   keyword (e.g. "FALSE CLAIM", "lazy import", "facade").
3. **For retrospective synthesis**: read all retros in chronology
   order (S172-S177 → S43 → S44) to get cumulative arc.
4. **For comparison**: compare "Wins" tables across sprints to see
   velocity trends.

## Cross-references

- [`docs/STATUS.md`](../STATUS.md) — single source of truth (per-wave rows)
- [`docs/audit/INDEX.md`](../audit/INDEX.md) — 12+ R12 audit docs
- [`docs/adr/INDEX.md`](../adr/INDEX.md) — ADR-0254 through ADR-0257

## ADR/audit documents referenced in retros

- ADR-0254 (`docs/adr/0254-agent-security-godobject-refactor-plan.md`) — S43
- ADR-0255 (`docs/adr/0255-l5-security-chain-restoration.md`) — S44 W1
- ADR-0256 (`docs/adr/0256-otel-pin-full-pytest-confirmed-runnable.md`) — S44 W2
- ADR-0257 (`docs/adr/0257-coverage-extension-real-measurement-13pct.md`) — S44 W4
- FUNCTIONAL_LIVE_2026-08-30.md (`docs/audit/FUNCTIONAL_LIVE_2026-08-30.md`) — S44 W3
- DEPENDABOT_REVIEW_2026-08-30.md (`docs/audit/DEPENDABOT_REVIEW_2026-08-30.md`) — S43

## Conventions

Each retrospective includes:
1. **Sprint goal** — what was achieved vs target
2. **Wins** — specific achievements with commit references
3. **Losses** — honest numbers (velocity drops, unfinished items)
4. **Lessons** — patterns discovered (not generic advice)
5. **Process changes** — 2-3 specific rules for next sprint
6. **Cumulative** — references to all commits/documents in scope
