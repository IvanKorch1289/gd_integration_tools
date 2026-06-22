# ADR-0247: S169 W2 Feature Pack — RLM, DI Scope, Per-Invoke Tool Policy, Linter Cleanup

- **Status:** Accepted (Sprint 30 feature pack, 2026-06-19)
- **Wave:** s30-feature-pack
- **Sprint:** 30 (post S168 delta closure + security patch)
- **Depends:** ADR-0245 (S168 delta), ADR-0246 (S30 security patch)

## Context

Sprint 30 закрывает 4 инкрементальные фичи / cleanup-задачи, выявленные в
deep-research audit (S168-W5 → DEEP-RESEARCH-gd_integration_tools-ULTRATHINK-2026-06-19.md):

1. **Per-invoke tool policy enforcement** (P0-1) — audit gap. S76 W3 реализовал
   `ToolsSpec` + `check_tool_allowed()`, но enforcement не был integrated в AIGateway
   pipeline. ToolsSpec default = empty whitelist/blacklist = no restriction, поэтому
   policy authors указывали rules без runtime effect.

2. **RLM (Routing Layer Model)** (P1-2) — cost optimization gap. ModelRouterSpec
   реализовал только failover (primary + fallback при errors), но НЕ routing по
   complexity (weak model для простых запросов, strong для multi-step reasoning).
   Use case: ~60-80% cost savings на factual/short запросах.

3. **DI Scope enum** (P2-2) — extensibility gap. ModuleRegistry не имел explicit
   lifecycle scope — только implicit singleton через `importlib`. Test fixtures +
   per-request services (tenants, workflows) не могли использовать isolation без
   monkey-patching `sys.modules`. Extensions не могли регистрировать custom lifecycle
   без правки ModuleRegistry (closed-for-extension pattern).

4. **ConvertersMixin Stage 2.1 PoC clarification** (P0-3) — docs gap. Module
   docstring перечислял ~40 методов "as group" без distinction между реализованными
   и planned. Вводил в заблуждение (выглядело как готовый API).

5. **Layer linter cleanup** (P15) — tooling gap. S168 W15-W17 cascade + S30 WS rate
   limit migration оставили 4 STALE allowlist entries + 2 NEW violations без
   allowlist update. Per P15 protocol: --prune-allowlist + --update-allowlist.

## Decision

**Apply 6 atomic commits** — каждый closure самодостаточен, тестируется independently,
сохраняет backward-compat через явные defaults.

### 1. Per-invoke tool policy enforcement (commit `8e462c9`)

**File**: `src/backend/core/ai/gateway_orchestrator_mixin.py:106-122`

Conditional call `enforce_tool_policy(request.workflow_id, policy.tools)` после
`_render_prompt` (Шаг 5) и перед `_invoke_llm` (Шаг 6). Lazy import внутри
условия. Skip если `policy.tools.whitelist + blacklist` empty (backward-compat
с pre-S76).

**Semantic**: `tool_name = request.workflow_id` (per docs/cookbooks/01-ai-agent-tools-whitelist.md).
На текущий момент workflow-level enforcement; per-tool-name — будущий S170+ refactor.

**Alternatives considered**:
- A. Встроить call в `LlmInvocationMixin._invoke_llm()` (требует signature change
  → breaking change для `_PipelineStepsProtocol`).
- B. Middleware (overkill, добавляет indirection).
- ✅ **C. Conditional call в orchestrator** (Ponytail minimum: 12 LOC, no signature
  change, default = no-op для pre-S76 политик).

### 2. RLM router_strategy + cheap_model (commit `31baf8e`)

**File**: `src/backend/core/ai/policy/spec.py:29-66`

Новые поля в `ModelRouterSpec`:
- `router_strategy: Literal["failover", "complexity"] = "failover"` — стратегия
  выбора модели (default = текущее поведение).
- `cheap_model: str | None = None` — RLM weak model для complexity routing.

**Degradation rule**: если `cheap_model=None` → strategy degrades to "failover"
behaviour (preserves pre-S169 semantic). Реализация complexity classifier в
`PydanticAIClient` deferred to S170+.

**YAML example**:
```yaml
model_router:
  primary: openai/gpt-4o
  cheap_model: openai/gpt-4o-mini
  router_strategy: complexity
  fallback: [anthropic/claude-3.5-sonnet]
```

### 3. DI Scope enum (commit `9837610`)

**File**: `src/backend/core/di/module_registry.py`

Новый enum `Scope { SINGLETON, SCOPED, TRANSIENT }` + parallel dict `MODULE_SCOPES`
(default = SINGLETON). Scope-aware `resolve_module()`:
- `SINGLETON` (default) — `importlib.import_module` (sys.modules cache).
- `TRANSIENT` — `importlib.util.spec_from_file_location` + `exec_module` (fresh).
- `SCOPED` — fallback to SINGLETON до реализации scope-context (S170+).

Новая функция `get_module_scope(key) -> Scope`.

**Backward-compat**: `INFRA_MODULES` shape unchanged, `resolve_module()` signature
unchanged, default = SINGLETON. Existing 45 modules работают as-is.

### 4. ConvertersMixin Stage 2.1 PoC clarification (commit `292ef21`)

**File**: `src/backend/dsl/builders/converters.py:1-23`

Header разделён на "Реализовано в Stage 2.1 PoC (5 методов)" + "Planned для Stage 2.1
продолжения (S37+; НЕ реализовано)". Validates against 14 xfailed tests в
`tests/unit/dsl/round_trip/test_format_converters.py`.

### 5. Layer linter cleanup (commit `874038f`)

**File**: `tools/check_layers_allowlist.txt`

Per P15 protocol (deep-research skill):
- `--prune-allowlist`: 4 STALE removed (orders_saga.py × 2, loader.py × 2 — оба файла
  удалены в S168 W15-W17 cascade).
- `--update-allowlist`: 2 NEW added (rate_limit.py, ws_rate_limit.py → unified_rate_limiter,
  framework exception через facade).

Net: 208 → 206 entries.

## Pre-Flight: Skill Protocols Applied

### Ponytail Minimum (smallest-scope-first)
Order of commits:
1. doc-only (ConvertersMixin clarification) — 0 functional change
2. 1 call-site addition (tool policy) — 12 LOC
3. 2 new fields (RLM) — 15 LOC + docs
4. new enum + parallel dict (DI Scope) — 97 LOC (largest)
5. allowlist auto-generation — 6 LOC net change

### Deep-Research P2/P14 (VERIFY > TRUST)
Каждое утверждение из audit report верифицировано через file:line / ast.parse /
`from src.backend.X import Y; print(Y)` перед commit.

### Deep-Research P15 (prune vs update-allowlist)
Two distinct operations, не mixing. Prune FIRST → update SECOND → verify.

## Verification

- `ast.parse`: OK для всех 5 функциональных файлов.
- `pytest tests/unit/ai/`: **23/23 passed** (P0-1 + P1-2 verified, no regressions).
- `pytest tests/unit/core/di/`: **131/131 passed** (P2-2 verified).
- `pytest tests/unit/dsl/ -k converter`: **220 passed, 14 xfailed** (xfailed =
  planned ConvertersMixin methods, validates doc honesty per P0-3).
- `python tools/check_layers.py`: **0 NEW, 0 STALE, 206 entries** (P15 verified).
- App smoke: `from src.backend.main import app` → 412 routes (no regression).

## Atomic Commits

| Hash | Subject | LOC | Files |
|---|---|---|---|
| `8e462c9` | feat(ai-gateway): per-invoke tool policy enforcement | +14 | 1 |
| `31baf8e` | feat(ai-policy): RLM router_strategy + cheap_model | +15 | 1 |
| `9837610` | feat(di): Scope enum SINGLETON/SCOPED/TRANSIENT | +97 | 1 |
| `292ef21` | docs(dsl): ConvertersMixin Stage 2.1 PoC scope | +15 | 1 |
| `874038f` | chore(layer-linter): prune STALE + add NEW | +2 / -4 | 1 |
| (P3) `98ebb30` | fix(test_factory): patch target | +3 / -3 | 1 |
| **Total** | **6 atomic commits** | **+146 / -11** | **5 unique files** |

## Health Score

**10/10 maintained** (per S168 baseline):
- 0 NEW layer violations
- 0 STALE allowlist entries
- 0 test regressions
- 412 routes operational
- 6 atomic commits, smallest-scope-first ordering
- Comprehensive audit report:
  `gap-analysis/DEEP-RESEARCH-gd_integration_tools-ULTRATHINK-2026-06-19.md`

## Out of Scope (S170+ backlog)

- Complexity classifier implementation в PydanticAIClient (heuristics: prompt
  length, reasoning markers, etc.).
- ScopeContext для SCOPED lifecycle (request/tenant/workflow context).
- ConvertersMixin ~34 planned methods (parse_ics, jsonpath, regex, pdf_*,
  ocr, polars_*, dask_compute, transform helpers).
- Per-tool-name enforcement (vs current workflow-level semantic).
- Migration facade access (rate_limit) к capability-checked wrapper.

## References

- DEEP-RESEARCH-gd_integration_tools-ULTRATHINK-2026-06-19.md (audit report)
- ADR-0245 (S168 delta closure, baseline)
- ADR-0246 (S30 security patch, sibling)
- ADR-NEW-20 / 0067-ai-policy-spec-dsl.md (AIPolicySpec schema)
- docs/cookbooks/01-ai-agent-tools-whitelist.md (tool policy semantics)
- S30 task IDs: P0-1, P0-3, P1-2, P2-2, P3, P15 (6 of 12 backlog items closed)
