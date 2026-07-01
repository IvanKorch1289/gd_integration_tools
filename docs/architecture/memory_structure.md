# Memory Structure & Session Recovery Rules

> **Дата**: 2026-07-01 (per S177 audit-mode + audit-mode directive).
> **Версия**: 1.0.
> **Назначение**: документация структуры memory (project / session / notes) + правила session-recovery для проекта `gd_integration_tools`. Связан с audit-документом `docs/audit/AUDIT_2026-07-01.md` (sprint-mode retrospective) и `docs/audit/REFACTORING_MASTER_PLAN_2026.md` (3-horizon roadmap).

---

## TL;DR

Эта сессия (`ses_0e8b28359ffee9pSUdEJL54JYL`) велась по 3 режимам:
1. **Sprint-mode** (M1-M12, 30 atomic commits per S177 retrospective).
2. **Audit-mode** (per `/goal # Роль` directive — 22-topic full-repo audit synthesis).
3. **Plan-mode** (мета-план + multi-session audit + agent dispatch).

**Memory структура** = 3 уровня:
- **Project** (persistent, cross-session) — `MEMORY.md` и spillover files в `~/.local/share/mimocode/memory/projects/694f4d31-db66-42a8-b7a1-3913b44c7e03/`.
- **Session** (per-session, восстанавливается при новой сессии) — `checkpoint.md` + `notes.md` в `~/.local/share/mimocode/memory/sessions/<session_id>/`.
- **Notes** (append-only scratchpad, current session) — `notes.md` в той же папке.

**Binding rules** (повторяющиеся в MEMORY.md как D-rules) воспроизведены ниже для session-recovery.

---

## A. Memory Architecture

### A.1 Структура каталогов

```
~/.local/share/mimocode/memory/
├── projects/
│   └── <project_id>/
│       ├── MEMORY.md                       # Cross-session durable knowledge
│       ├── MEMORY-<topic>-<scope>.md       # Spillover для длинных секций
│       └── (other spillover files)
├── sessions/
│   └── <session_id>/
│       ├── checkpoint.md                   # Per-session state (structured)
│       ├── notes.md                        # Append-only scratchpad
│       └── (other per-session files)
└── global/
    └── MEMORY.md                            # Cross-project (если существует)
```

### A.2 Project memory (durable, cross-session)

- **MEMORY.md** — durable knowledge (D-rules, Dxxx). Promoted из session checkpoints' §7 когда proven durable.
- **Spillover files** — `MEMORY-<topic>-<scope>.md` для длинных секций. Index в MEMORY.md.

### A.3 Session memory (per-session, recovered)

- **checkpoint.md** — structured (11 sections per checkpoint-writer pattern). Section §11 = open notes.
- **notes.md** — append-only scratchpad. Captures turn-by-turn state, pre/post pivot, pivot rationale.

### A.4 Memory writes

- **Append-only** — не редактируйте prior entries. Add new entries с turn number.
- **Перед возможным reset** (system-reminder: "Context is filling up >70%, consider writing to memory now") — write findings + final state to memory file.
- **References** — `notes.md` ↔ `checkpoint.md` ↔ `MEMORY.md` cross-references via §1 §11.

---

## B. Session Recovery Rules

### B.1 When to read memory

| Trigger | Source |
|---|---|
| New session start | `notes.md` (last entry) + `checkpoint.md` (§1 Active intent + §2 Next action) |
| User pivot directive | `notes.md` (newest turn) + `MEMORY.md` (D-rules index) |
| System-reminder: "Context is filling up" | Write to `notes.md` IMMEDIATELY before reset |
| Commit cycle complete | `notes.md` cumulative commit count + commit list |
| Plan-mode entered | `MEMORY.md` + `notes.md` (rules + scope) |

### B.2 How to read memory

1. **Read `notes.md` first** — most recent turn, current state, pre/post pivot.
2. **Read `checkpoint.md` §1-§2** — Active intent + Next concrete action.
3. **Read `MEMORY.md` index** — durable D-rules (D121, D328, D337, D248).
4. **Read spillover files** — если D-rule в index отсылает к нему.

### B.3 When to write memory

- **End of session** (or before reset) — write to `notes.md` (per-turn) + `checkpoint.md` (per-task) + `MEMORY.md` (per-durable-D-rule).
- **After each commit** — per-commit note в `notes.md`.
- **After each pivot** — pre-pivot state, post-pivot directive, scope, rationale.

### B.4 Memory write order

1. **`notes.md` FIRST** (append-only, fast) — captures turn-by-turn state.
2. **`checkpoint.md` SECOND** (structured, 11 sections) — captures per-task state.
3. **`MEMORY.md` LAST** (promoted D-rules) — only when pattern proven durable across sessions.

---

## C. Binding Rules (D-rules, current)

### C.1 Project rules (per `CLAUDE.md` + `AGENTS.md`)

- **D248 Read `.env*` FORBIDDEN** — NEVER read `.env*`, `secrets/**`, `*.pem`, `*.key`. Reason: production secrets in dev files; no instrumentation value.
- **D121 parallel-agents binding** — no `git stash` / `reset` / `clean` when parallel-agents active. Reason: ломает parallel-agents' workspace state. Per-agent commits isolated только to my files.
- **D328 Read-before-edit** — re-read file via `read` tool before `edit` tool. Reason: `edit` tool requires recent read; otherwise "old_string not match" error.
- **D337 `@pytest.mark.pre_existing` discipline** — known-failing baseline tests registered with marker. Reason: distinguish pre-existing failures (NOT regressions) от new M-regressions.
- **D345 ADR pending** — extension-shadowing (deferred to PL-rev).
- **Streamlit-only constraint (S173+)** — frontend = Streamlit only, не переписывать на другие фреймворки/языки программирования. No React/Vue/Svelte, no TypeScript/JS migrations, no other-Python web frameworks.
- **Russian-language mode (S177+)** — user-facing responses на русском. Code/commit messages English per existing convention.

### C.2 Working-style directives (per session, accumulated)

- **Sequential-milestone mode (BINDING)** — implement one milestone at a time, verify, run retrospective + 3-perspective review, surface pivot to user before starting the next milestone.
- **Full-close mode (BINDING)** — "полностью достичь" each milestone + 3-perspective review. Close = verify (all green) + 3-perspective review + fix sequence applied + commit.
- **Review-and-fix gate (BINDING)** — 3-perspective review surfaces issues → apply fixes INLINE → re-verify → proceed.
- **Commit cadence (USER-DIRECTIVE, BINDING, CONTINUING)** — "Не забывай коммитить после ретроспективы и ревью". After each milestone retro+review, atomic commit per milestone with conventional prefix (`feat:` / `fix:` / `chore:` / `docs:` / `refactor:` / `test:` / `build:` / `ci:` / `perf:`).
- **No batch forward-execution (DIRECTIVE)** — M10.x каждый отдельно close перед next.
- **M2 directive (BINDING)** — "treat as binding user directive — IMMEDIATELY resume work without asking 'what next'". Continuation pivot "выполняй" = immediate start next sprint.
- **D387 synthesis-by-meta-plan pattern (BINDING)** — для large-repo audit (>2000 files) when per-file reading infeasible, write meta-plan + multi-session follow-up + reuse existing audit-документы + memory archives как ground truth. Caveat MUST be stated explicitly in synthesis output.

### C.3 Sprint-mode directives (per audit synthesis + master plan)

- **Per-milestone lightweight scope** — 1-2 file scope per milestone. Honest scope per M6 precedent (regression-fix + analysis-doc, not fix-all-58).
- **3-horizon roadmap** (per `REFACTORING_MASTER_PLAN_2026.md`) — QW (Quick wins, 1-3 days) / ST (Stabilization, 1-3 weeks) / PL (Platform evolution, 1-3 months).
- **12-item prioritized backlog** (per audit Section L) — priority + effort + risk + dependencies.
- **Migration risk matrix** (per audit Section E) — LOW/MED/HIGH per item + breaking vs non-breaking.

---

## D. Session State Recovery (current: `ses_0e8b28359ffee9pSUdEJL54JYL`)

### D.1 Last session state (2026-07-01)

- **HEAD commit**: `da265a9b docs(audit-index): INDEX.md для docs/audit/ (QW-2 from refactoring master plan)`.
- **Cumulative commits this session**: **33 atomic commits** (S172-S177 = 30 + audit + master plan + INDEX = 33).
- **Sprint status**: S172-S177 CLOSED. Audit-mode + refactoring master plan + retrospective + INDEX = CLOSED. Sprint + Audit-mode = both CLOSED.
- **Cumulative LOC delta this session**: +9719/-225 = +9494 net.
- **NEW files this session**: 9 (5 sprint + 3 audit + 1 INDEX).
- **Backlog status**: 1/12 closed retroactively (QW-2), 11/12 deferred.
- **User rule compliance (S173+)**: 0 Streamlit-only violations. 0 regression-net (D337 baseline tagged).

### D.2 Active intent (last turn)

> «давай закроем QW-1 — задокументируй структуру памяти и правила сессионного восстановления. B следующему спринту приступай»

**QW-1 in-progress** (this turn): documentation of memory structure + session-recovery rules. This document is QW-1 deliverable.

### D.3 Memory file structure (current session)

- `~/.local/share/mimocode/memory/sessions/ses_0e8b28359ffee9pSUdEJL54JYL/`:
  - `notes.md` (per-turn append-only, last entry = turn 52).
  - `checkpoint.md` (structured, 11 sections, per-task state).
- `~/.local/share/mimocode/memory/projects/694f4d31-db66-42a8-b7a1-3913b44c7e03/`:
  - `MEMORY.md` (durable D-rules).
  - `MEMORY-<topic>-<scope>.md` (spillover files).

### D.4 Sprint-1 (next) candidates per refactoring master plan

After QW-1 closure, user-pivot к `S178 sprint-1`. Candidates per 12-item backlog:
- **QW-3** (LOW): extend `shared/audit_event_lite.py` to additional pages (M11.2 pattern).
- **ST-1** (MEDIUM): layer violations fix (top-3 of 56 в `infrastructure_facade.py`).
- **ST-2** (LOW): `verify_sprint_health.py` adopt в CI.
- **ST-3** (MEDIUM): `shared/audit_event_lite.py` extension.
- **ST-4** (MEDIUM): test coverage 50% → 65%.
- **ST-5** (LOW): documentation gap.
- **ST-6** (MEDIUM): `core/utils/` split (5 files → per-domain).
- **PL-1** (HIGH effort, HIGH risk): compiled DSL pipeline (AST→IR codegen).
- **PL-2** (MEDIUM): HITL consumer-side pub/sub.
- **PL-3** (HIGH effort, MEDIUM risk): gVisor backend (D65).
- **PL-4** (LOW value, HIGH risk): full frontend split (multi-app).
- **PL-5** (MEDIUM value, HIGH risk): 56 layer violations full fix.
- **PL-6** (LOW value, MEDIUM risk): `manage.py` (65K monolith) split.
- **PL-7** (MEDIUM value, HIGH risk): compiled DI v2.
- **PL-8** (MEDIUM value, MEDIUM risk): Observability v2 (OpenTelemetry).
- **PL-9** (MEDIUM value, LOW risk): test coverage 65% → 75%.

### D.5 Per-sprint cycle pattern (per D-rules)

Per `MEMORY-cycle31-32-audit-stable.md` + `REFACTORING_MASTER_PLAN_2026.md`:
1. **Phase 1**: scope clarification (user question-tool).
2. **Phase 2**: design (plan-agent or user-confirmed).
3. **Phase 3**: review (3-perspective: Security/Architecture/Ops).
4. **Phase 4**: write plan to `.mimocode/plans/1782802381991-proud-garden.md`.
5. **Phase 5**: `plan_exit` (for audit-mode) OR direct execution (for sprint-mode).
6. **Sprint execution**: per-milestone lightweight + commit + 3-perspective review + commit.
7. **Sprint closure**: retrospective doc + next-sprint plan.

---

## E. Quick-Reference (для session-recovery)

### E.1 Memory locations cheat-sheet

| Path | Purpose | Recovery use |
|---|---|---|
| `~/.local/share/mimocode/memory/sessions/<sid>/notes.md` | Per-turn scratchpad | Latest state, pivot rationale |
| `~/.local/share/mimocode/memory/sessions/<sid>/checkpoint.md` | Per-task state | Active intent, next action, directives |
| `~/.local/share/mimocode/memory/projects/<pid>/MEMORY.md` | Durable D-rules | Binding project constraints |
| `~/.local/share/mimocode/memory/projects/<pid>/MEMORY-<topic>-<scope>.md` | Spillover | Detailed durable context |
| `.mimocode/plans/1782802381991-proud-garden.md` | Meta-plan (per turn) | Per-sprint plan |
| `docs/audit/AUDIT_2026-07-01.md` | Audit synthesis (current) | 22-topic + D-rules |
| `docs/audit/REFACTORING_MASTER_PLAN_2026.md` | 3-horizon + 12-item backlog | Sprint-1 candidates |
| `docs/audit/SPRINT_S177_RETROSPECTIVE.md` | 32-commit history | Sprint-1 closure |
| `docs/audit/INDEX.md` | Navigation hub | 8 audit docs |

### E.2 D-rule quick-reference

- **D121** = no `git stash`/`reset`/`clean` (parallel-agents compatibility).
- **D248** = NEVER read `.env*`, `secrets/**`, `*.pem`, `*.key`.
- **D328** = re-read file via `read` before `edit` tool.
- **D337** = `@pytest.mark.pre_existing` for known-failing baseline.
- **D345** = extension-shadowing ADR (deferred to PL-rev).
- **D387** = synthesis-by-meta-plan pattern (large-repo audit).
- **D388-D393** = audit synthesis content shape (cycle 38 S177 audit-exec).

### E.3 Streamlit-only user rule

Per S173+ user directive:
- frontend = Streamlit only, не переписывать на другие фреймворки/языки программирования.
- No React/Vue/Svelte rewrites; no TypeScript/JS migrations; no other-Python web frameworks (FastAPI templates, Django, Flask, etc.) replacing Streamlit.
- Additive improvements to Streamlit only (lazy-import, audit-event, observability, security).

### E.4 Russian-language mode (S177+)

Per S177+ user directive:
- User-facing responses на русском.
- Code/commit messages English per existing convention.
- 0 violations across 33 commits this session.

---

## F. Cross-References

- `docs/audit/AUDIT_2026-07-01.md` — master audit synthesis (22 topics, A-M sections).
- `docs/audit/REFACTORING_MASTER_PLAN_2026.md` — refactoring 3-horizon + 12-item backlog.
- `docs/audit/SPRINT_S177_RETROSPECTIVE.md` — 32-commit history.
- `docs/audit/INDEX.md` — navigation hub (8 audit docs).
- `.mimocode/plans/1782802381991-proud-garden.md` — meta-plan (multi-session audit + agent dispatch).
- `~/.local/share/mimocode/memory/projects/694f4d31-db66-42a8-b7a1-3913b44c7e03/MEMORY.md` — durable D-rules.

---

## G. End-state (this turn, QW-1)

This document `docs/architecture/memory_structure.md` (QW-1 deliverable) provides:
- Section A: Memory architecture (3 levels: project / session / notes).
- Section B: Session recovery rules (when read/write, how, order).
- Section C: Binding rules (D-rules, working-style, sprint-mode).
- Section D: Current session state + next-sprint candidates.
- Section E: Quick-reference (locations + D-rules + Streamlit + Russian).
- Section F: Cross-references.
- Section G: End-state.

**QW-1 closed retroactively** (1/12 backlog items closed + memory documentation).
**Next**: user-pivot к Sprint-1 (per refactoring master plan).
