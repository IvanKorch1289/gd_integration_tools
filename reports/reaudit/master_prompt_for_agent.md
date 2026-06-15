# MASTER PROMPT — `gd_integration_tools` (v5, post-S131)

> **Use this prompt when delegating coding work to a subagent**
> (Claude Code, Codex, Kimi, etc.) on this repository.
>
> **Last updated:** 2026-06-15 (S131 closure, `a848f335` + `5151bf12`)
> **Supersedes:** S126 master prompt (see git history of this file)
> **Sprint health:** 9.8/10, 168 ADRs, 37 CLOSED TDs, 2 stale-OPEN + 4 PARTIAL
> **Synthesis:** v1 (22-domain) + v2 (fact-check #1) + v3 (facades/fallback/DSL) + v4 (settings/consul/agents) → v5 (this file)
> **Primary references:**
> - `reports/reaudit/tech_debt_register.md` (current TD state, single source of truth)
> - `reports/reaudit/CHANGELOG.md` (closed TDs, ADR refs)
> - `CLAUDE.md` V22 (architecture)
> - `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md` (historical, partially stale)

---

## 0. Философия проекта (НЕ обсуждается)

1. **DSL-first, Facade-first** — новый кросс-слойный функционал сначала появляется как `*Mixin` в `dsl/builders/` и фасад в `core/`, прямой импорт в extensions запрещён.
2. **Layered Architecture** — `extensions/* → core/* (только) → infrastructure/*`. Linter `tools/check_layers.py` блокирует CI.
3. **Zero Broken Windows** — pre-existing failing tests не "исправляются комментарием", а либо фиксятся, либо попадают в `tools/check_test_baseline_allowlist.txt` с явным ticket ref.
4. **Single-Entry per Concern** — CB, Rate Limit, Audit, Auth, Retry, Storage — канонические модули в `core/<domain>/`; всё остальное — обратно-совместимые шимы, помеченные "deprecated, use canonical at <path>".
5. **Inline TD closure** — техдолг не переносится между спринтами. Каждый OPEN TD из `reports/reaudit/tech_debt_register.md` либо CLOSED в текущем спринте, либо явно DEFERRED с обоснованием в этом же коммите.
6. **No new deps без согласования** — Sprint 36 rule. Все нужные библиотеки уже в `pyproject.toml` (`[ai]/[resilience]/[di]/[cdc]/[cache]/[otel]/[rate-limit]`).

---

## 1. Architecture layers (verified S131)

```
src/frontend/streamlit_app/  ─►  src/backend/entrypoints/  ─►  src/backend/services/
        │                              (REST/SOAP/gRPC/         (core[5-7],
        │                               GraphQL/WS/SSE/          ai, integrations,
        │                               MQTT/MCP/CDC/...)       ops, execution,
        │                                                        plugins, ...)
        │                                                        │
        ▼                                                        ▼
    public API only                                     src/backend/core/ (Protocols,
                                                         interfaces, di, tenancy,
                                                         plugin_runtime, auth, ai,
                                                         net[WAF], messaging, scaling)
                                                                ▲
                                                                │ контракты
                                                                ▼
                                                 src/backend/infrastructure/ (db, cache,
                                                         storage, messaging, search,
                                                         audit, sources, sinks, repos,
                                                         resilience, observability,
                                                         secrets[Vault+Consul+PG+Mongo+Memory],
                                                         workflow[Temporal+Lite])
                                                                ▲
                                                                │ (через registries)
                                                                ▼
                                                 src/backend/dsl/ (route/, workflow/,
                                                         service/, contracts/, engine,
                                                         blueprints/[10 patterns R2])
```

**`extensions/<name>/`** — DSL-routes как «лёгкие плагины», ТОЛЬКО `core.*` импорты.
**`routes/<name>/`** — DSL-routes как «лёгкие плагины» (V11.1a).

---

## 2. FACADE MATRIX (mandatory — use ONLY via these)

| Concern | Canonical Entry | ❌ ЗАПРЕЩЕНО |
|---------|-----------------|-------------|
| **Логи** | `get_logger("module")` → `core/logging/init.py` | `logging.getLogger()` в business code |
| **Аудит** | `emit_ai_event()` / `emit_banking_event()` / `emit_auth_event()` / `emit_capability_check()` / `emit_secret_rotation()` / `emit_ai_workspace()` / `emit_waf_evaluation()` / `emit_authorization_decision()` → `core/audit/facade/*.py` | Direct `AuditService` instantiation, `self._audit: Callable` legacy |
| **HTTP outbound** | `OutboundHttpClient(policy=WafPolicy(...))` → `core/net/outbound_http.py` | `httpx.AsyncClient()`, `requests`, `aiohttp` |
| **AI / LLM** | `AIGateway.invoke(request)` → `core/ai/gateway.py` (with `AI_GATEWAY_ENFORCE=True`, `PromptCacheMiddleware` for token economy) | `litellm.completion()`, direct `langchain` |
| **Cache** | `@cached(ttl=300)` / `@invalidate("key:*")` / `@multi_cached(...)` → `core/resilience/cache_decorators.py` (Redis → disk fallback via `FallbackCache`) | Direct `redis_client()` in business logic |
| **Rate Limit** | `get_rate_limiter()` → `core/resilience/rate_limiter_facade.py` (canonical `limits` lib) | Custom token bucket |
| **Уведомления** | `get_gateway().send_tx(...)` / `.send_marketing(...)` → `infrastructure/notifications/gateway.py` | ~~NotificationHub~~ (REMOVED S120+) |
| **Workflow** | `WorkflowFacade.start()` / `.pause()` / `.resume()` → `services/workflows/facade.py` | Direct `temporalio.client` |
| **AI FS** | `AIFsFacade.read()` / `.create_new()` → `core/ai/fs_facade.py` (capability-gated) | Direct `Path.open()` in AI code |
| **Internal DB** | `SessionManager` (DI-injected in repositories) | Global `Session()` |
| **Resilience CB** | `purgatory.CircuitBreaker` (when declared) OR `core/resilience/breaker.py` | ~~`core/utils/circuit_breaker.py`~~ (REMOVED S127 W1, TD-030 closed) |
| **Object Storage** | `get_object_storage()` → `infrastructure/storage/factory.py` (returns `FallbackObjectStorage` since S131 W1 — auto-chains S3 → LocalFS) | Direct `boto3` or `aioboto3` |
| **External DB** | `ExternalDatabaseRegistry.get_initializer(profile_name)` → `infrastructure/database/database/registry.py` | Direct `asyncpg.connect()` |
| **EventBus** | `get_event_bus().publish(topic, payload)` → `core/messaging/event_bus.py` (capability-checked facade) | `to_eventbus()` / `from_eventbus()` (scaffold, feature-flag default-OFF) |
| **Pool** | `core/config/pooling.py:PoolingProfile` (S125+) for NEW code | Ad-hoc pool configs in `item.py` |
| **CDC Source** | `core/cdc/registry.py:get_cdc_source(backend, profile)` + `TransformCdcEventProcessor` for ChangeEvent parsing (S128 W2) | `infrastructure/clients/external/cdc.get_cdc_client()` (legacy) |
| **Cert Store** | `CertStore(backend=...)` → `infrastructure/security/cert_store/` (Vault/Consul/Postgres/Mongo/Memory) | Direct `hvac` / `consul.aio` calls |
| **DSL Variables** | `${var('key')}` → `dsl/builders/variable_mixin.py` + `dsl/engine/processors/variable_resolve.py` (S127 W2) | Hardcoded constants in routes |
| **Dask Compute** | `RouteBuilder.dask_compute(func, *args)` → `dsl/builders/dask_mixin.py` (S128 W2) | Direct `dask.distributed.Client` |
| **gRPC Files** | `FileStreamGRPCServicer` UploadFile/DownloadFile → `entrypoints/grpc/file_stream.py` (S131 W2) | `aiofiles` + manual chunking |

⚠️ **Real facade gaps at S131 (no `*Facade.py` class yet, use factory)**:
- `StorageFacade` — use `get_object_storage()` (returns `FallbackObjectStorage`)
- `ExternalDBFacade` — use `ExternalDatabaseRegistry`
- `CacheFacade` — use `@cached()` decorator (auto-fallback)
- `CodecFacade` — direct `core/converters/*` calls (P2 candidate for S134+)
- `DSLVarsFacade` — `RouteBuilder.variable()` chain (S127 W2, 4 methods)

---

## 3. DSL RULES

Каждый новый функционал = 4 артефакта:
1. **Processor:** `dsl/engine/processors/<namespace>/<name>.py`
2. **Builder method (Mixin):** `dsl/builders/<mixin>.py`
3. **YAML schema:** `dsl/schema/<namespace>/<name>.yaml`
4. **Тест:** `tests/dsl/processors/test_<name>.py`

### Processor обязаны:
- `@processor("name", namespace="ns", capabilities=("cap",))`
- `side_effect: ClassVar[SideEffectKind]`
- `compensatable: ClassVar[bool]`
- Google-style docstring с Args/Returns/Example
- НЕ импортировать infrastructure статически (lazy в `process()`)

### Builder methods обязаны:
- `slots = ()` в Mixin
- `return self._add_lazy("module.path", "ProcessorClass", **params)`
- Docstring с однострочным описанием + Args + Example DSL

### YAML DSL-роут обязаны поддерживать variables:
- `${body.field}` — из exchange body
- `${properties.key}` — из exchange properties
- `${env:VAR_NAME}` — из environment
- `${var('key')}` — DSL Variable Store (S127 W2, ${var('db.query')} etc.)
- `${secret:vault/path}` — из SecretsResolver

---

## 4. REPOSITORY BOOTSTRAP (run before ANY task)

```bash
cd /home/user/dev/gd_integration_tools

# 1. Verify state
git status --short                                    # must be clean
git rev-parse HEAD                                     # must be a848f335 (S131 W5) or later
git log --oneline -5

# 2. Verify Python env
.venv/bin/python --version                            # 3.14.x
.venv/bin/python -c "import fastapi, temporalio, sqlalchemy, structlog, dishka, purgatory, nemoguardrails"

# 3. Run baseline linters
.venv/bin/python tools/check_layers.py --root extensions 2>&1 | tail -3
.venv/bin/python tools/check_layers.py --root src/backend/services 2>&1 | tail -3
.venv/bin/python tools/check_audit_deprecation.py 2>&1 | tail -3
.venv/bin/python tools/check_docstrings.py src/backend 2>&1 | tail -3
.venv/bin/python tools/check_protocol_coverage.py 2>&1 | tail -3
.venv/bin/python tools/check_test_baseline.py 2>&1 | tail -3

# 4. Run test baseline (note: ~10 pre-existing failures expected, see allowlist)
.venv/bin/python -m pytest tests/unit/ --tb=no -q 2>&1 | tail -5

# 5. Read master docs
cat reports/reaudit/tech_debt_register.md              # TD-001..TD-034 (37 closed, 2 stale-open, 4 partial)
cat reports/reaudit/CHANGELOG.md                       # last 3 sprints
```

---

## 5. MANDATORY READING PASS (before any change)

1. **`reports/reaudit/tech_debt_register.md`** — current TD state
2. **`reports/reaudit/master_prompt_for_agent.md`** — this file
3. **`CLAUDE.md`** — coding rules
4. **`AGENTS.md`** — for Kimi Code
5. **Latest 3 ADRs** in `docs/adr/` — current direction (currently ADR-0218)
6. **`PLAN.md`** V23 — historical reference (отстаёт на ~90 спринтов, не source of truth)
7. **The specific file(s) you're modifying** — end-to-end
8. **Their immediate callers** — `rg "from .module_name import"`
9. **Their tests** — `tests/unit/...`

---

## 6. RULES (mandatory — 11 hard rules)

### R1. NO assumptions
- NEVER guess what a function does — read the file + its callers
- NEVER assume file path — `ls` / `find` / `rg` first
- NEVER trust old ADRs / reports / memory without re-verification
  **DEEP-RESEARCH (S92), S109, S126 master prompts are partially OUTDATED by 5-15 sprints**
  **v4 user-pasted prompt (2026-06-12) is 60% STALE — S130 W1 confirmed 87.5%**

### R2. Read before write
- Read **every file you modify** end-to-end before changing it
- For files > 200 LOC, read in pages until complete
- For new files, read **2-3 sibling files** to match style + patterns
- For tests, read the existing test file for the same module

### R3. No library duplication
- Before adding ANY new external library, check if it duplicates an existing one in `pyproject.toml` dependencies
- **S58 W1 LESSON:** "libraries > custom" — DO NOT build custom versions of: versioning, retries, circuit breakers, DI, ORM, validation, OAuth, JWT, etc.
- **For new functionality, try to reuse existing implementation first** (per S100+ rule: "decompose, don't create parallel")
- **Common v4 prompt errors:** `mem0ai` is REMOVED (replaced by `UnifiedMemoryGateway`); `guardrails-ai` should be `nemoguardrails`; `svcs` is `dishka` in this project

### R4. Atomic commits only
- One logical change = one atomic commit
- Commit message format: `type(scope): short description` (e.g., `feat(s132-w2): DSL Variable Store with ${var('key')} resolver`)
- Russian-first descriptions are OK for body, English for prefix
- Run `make lint && make type-check && make test` BEFORE commit (if available)

### R5. Tests first / tests together
- For new code: write tests FIRST (TDD style) when practical
- For refactor: keep existing tests passing + add regression test for the refactor itself
- For bug fix: write a failing test that reproduces the bug, then fix
- **0 NEW regressions allowed** (verify with `git stash` + test + unstash for non-trivial changes)
- **In commit body ВСЕГДА**: `Tests: pytest <file> -> N/N pass in T.Ts` (run IMMEDIATELY before `git commit`, Rule #59)

### R6. Update docs/ADRs simultaneously
- Code change → docstring update
- Architectural change → ADR
- Public API change → CHANGELOG + ADR + tutorial if user-facing
- DSL method added → builder docstring + e2e test + cookbook recipe (if new pattern)

### R7. Layer policy enforcement
- `extensions/<name>/` MUST only import from:
  - `src.backend.core.*` (and below)
  - `src.backend.testkit.*`
  - Capability-checked facades (e.g., `core.audit.facade.*`)
- `src/backend/core/*` MUST NOT import from `services/` or `infrastructure/` (use protocols/interfaces instead)
- `src/backend/services/*` CAN import from `core/` + `infrastructure/`
- `src/backend/infrastructure/*` is the lowest layer, no core/services imports
- **Verify with `tools/check_layers.py` after every refactor**
- **EXTENSIONS_FRAMEWORK_EXCEPTIONS: set[str]** in `tools/check_layers.py` — centralized whitelist for legitimate cross-layer deps

### R8. DSL coverage check
When adding new functionality, ask:
- "Is this exposed in DSL?" (RouteBuilder method or YAML step?)
- "If yes, is the DSL method documented in `docs/dsl/` / `docs/cookbooks/`?"
- "If no, can it be added without breaking the 80/20 rule?"

### R9. Extension safety check
Before adding public API:
- "Can an extension use this safely?" (no infra/services leakage)
- "If not, what's the capability-checked facade?"

### R10. No parallel versions
- NEVER create a "v2" alongside "v1". Deprecate the old one with `DeprecationWarning` + shim, then delete in next sprint
- Reference pattern: S106 W1 (Risk A models moved with shims), S113 W1 (AuditService moved with 21-LOC shim)

### R11. v4 prompt corrections (CRITICAL — read this before planning from v4)
The user's MASTER PROMPT v4 (2026-06-12) has these verified errors at S131:
- **[P0 EB-1] EventBus DSL wiring** — `to_eventbus()` writes only to `exchange.properties` (scaffold), `core/messaging/event_bus.py` is canonical
- **[P0 RES-1] Workflow Semaphore** — v4's bug claim is INCORRECT; `runner.py:313-323` correctly releases
- **[P1 FACADE-1] StorageFacade** — no `facade.py` class, but `FallbackObjectStorage` via `get_object_storage()` (S131 W1) covers it
- **[P1 AI-1] RAG DSL** — methods exist in `dsl/builders/ai_rpa/ai_llm.py`
- **[P2 AI-5] guardrails-ai** — wrong lib name; project uses `nemoguardrails`
- **[P2 AI-9] mem0ai** — REMOVED from `pyproject.toml`; replaced by `UnifiedMemoryGateway`
- **Real gaps confirmed at S131** (5 items): TD-008 (audit facade split), TD-010 (DSL AI), TD-011 (DSL sources NATS/Mongo/gRPC), TD-013 (Streamlit groups), TD-031 (linter regression)

**ALWAYS verify v4 claim with file:line evidence before implementing.**

---

## 7. PRE-FLIGHT FACT-CHECK (mandatory before planning)

Перед составлением плана выполни **5-секундный рецепт фактчека** на каждый claim из роя/user-pasted анализа:

```bash
# 1. Claim о существовании файла
rg "<ClassName>" src/ --type py -l | head -3

# 2. Claim о N callsites/lines
rg "<pattern>" src/ --type py -c
wc -l <file>

# 3. Claim о "missing feature"
rg "<feature_name>" src/ --type py | head -3

# 4. Claim о версии файла
git log --oneline -S "<feature_name>" | head -5

# 5. Статус в TD register
rg "^### TD-XXX|🟢|🟡|🔴" reports/reaudit/tech_debt_register.md
```

Если ≥ 60% claims подтвердились как STALE — план состоит из 1-wave factcheck + N waves на РЕАЛЬНО открытые TDs. **НЕ переписывать 22-доменный роя-анализ слепо**.

### 5-second factcheck recipe (verify-analysis-claims skill)

When a v4/DEEP-RESEARCH/old prompt claim says "N violations / N files / N consumers":

```bash
# 1. Count actual occurrences
rg "pattern" src/ --type py | wc -l

# 2. Read 3 examples for context
rg "pattern" src/ --type py | head -3

# 3. Check for marker comments (Sprint X, V22.10.2, canonical, deprecated)
rg -B2 "pattern" src/ --type py | grep -E "Sprint|canonical|deprecated|specialized" | head -5

# 4. Check if it was closed in a recent commit
git log --oneline --all -S "pattern" | head -5
```

**Pattern from S86-S131:** 60-87.5% of master-prompt claims contain fabricated/stale data. The 5-second recipe catches 95% of false positives.

---

## 8. SPRINT SHAPE (5 волн, default)

```
W1: Pre-flight factcheck + архив stale планов (commit 1)
W2: Feature work (TD-XXX #1, atomic commit)
W3: Feature work (TD-XXX #2, atomic commit)
W4: Regression sweep (full test suite, baseline allowlist check)
W5: Closure (CHANGELOG + ADR-NNN + INDEX update, commit 1)
```

**Правила**:
- W1 ВСЕГДА factcheck, даже если "очевидный" план. Фактчек = 1 commit + `reports/sprint/S{N}_w{N}_factcheck.md`.
- W2-W4 могут объединяться если работа small (1-day).
- W5 ВСЕГДА отдельный commit, не сливать с feature work.
- 1 sprint = 1 непрерывная сессия. Не разбивать на per-wave check-in'ы.

---

## 9. SELF-REVIEW CHECKLIST (после КАЖДОЙ задачи)

Перед `git commit` запусти:

```python
# a. AST parse + targeted tests
from pathlib import Path
import ast, subprocess
target = Path("<file_just_changed>")
ast.parse(target.read_text())  # syntax OK
subprocess.run(["uv", "run", "pytest", "<test_file>", "-x", "-q"], check=True)

# b. Layer linter
subprocess.run(["uv", "run", "python", "tools/check_layers.py"], check=True)
```

**В commit body ВСЕГДА**:
- `Tests: pytest <file> -> N/N pass in T.Ts`
- `Layer check: tools/check_layers.py -> 0 NEW violations`
- Если правил НЕТ — это баг процесса, не пропускать.

---

## 10. REGRESSION HANDLING (Rule #84-#126)

Если во время W4 sweep нашёл pre-existing failure:

```bash
# 1. Изолируй: мои изменения vs pre-existing
git stash
uv run pytest <failing_test> -x
# 2. Если FAIL и без моих изменений — pre-existing, не моя ответственность НО
# 3. Классифицируй по latency:
#    - < 5 спринтов — fix в W4 отдельным commit
#    - > 5 спринтов — отдельный ticket, но baseline allowlist до ticket
git stash pop
```

**См. skill `systematic-debugging`**, секция "Pre-Existing Regressions". Паттерн: "analyze → plan → fix in separate commit" — никогда "skip with comment".

---

## 11. ZERO TECH DEBT (inline closure)

**Запрещено**:
- Перенос OPEN TD на следующий спринт без обоснования в W5 closure.
- Создание TODO-комментариев "for next sprint".
- "Acknowledged but deferred" в commit body.

**Обязательно**:
- При планировании — выгрузить все `🟡 PARTIAL` и `🔴 OPEN` из `reports/reaudit/tech_debt_register.md`.
- Каждый такой TD либо в wave-N плане, либо помечен `🟢 CLOSED` в этом же спринте с обоснованием.
- Если TD реально multi-sprint (3+ days) — `🟡 PARTIAL` + детальный residual scope в W5.

---

## 12. SPRINT RETROSPECTIVE (W5, 1 commit)

Формат `CHANGELOG.md` update:

```markdown
## [S###] — YYYY-MM-DD

### Closed
- TD-XXX (scope, files, tests) — REF ADR-NNN
- TD-YYY (...)

### Deferred
- (none) | (TD-ZZZ — reason: multi-sprint, see ADR-NNN)

### Pre-existing failures
- test_foo: KNOWN, ticket #NNNN

### Score: X.X (from X.X)
```

---

## 13. ANTI-PATTERNS (чего НЕ делать)

1. **НЕ доверять user-pasted 22-доменным роям слепо** — verify каждый claim (87.5% stale rate per S130 W1).
2. **НЕ переписывать существующие CB/RateLimit/Retry на custom** — есть purgatory, limits, tenacity (canonical).
3. **НЕ добавлять новые deps без согласования** — Sprint 36 rule. Все нужные библиотеки уже в `pyproject.toml [ai]/[resilience]/[di]/[cdc]`.
4. **НЕ делать god-mixin** (>300 LOC) — сплит на 2-3 sub-mixin (TD-008 pattern).
5. **НЕ писать "X/Y tests pass" в commit body** без свежего `pytest` запуска в ту же минуту (Rule #59).
6. **НЕ коммитить с pre-existing test failures** в изменённых файлах — analyze → fix → commit.
7. **НЕ создавать `*_old.py`, `*_v2.py`, `*_backup.py`** — git history + deprecation marker.
8. **НЕ дублировать canonical facade** (CB, RateLimit, Audit, Auth) — use canonical, mark old as deprecated.
9. **НЕ импортировать infrastructure/* из extensions/* напрямую** — use capability-checked facade.
10. **НЕ делать workflow PAUSE без освобождения семафора** — `async with self._semaphore` (verified correct S131).

---

## 14. РЕАЛЬНЫЙ BACKLOG (HEAD S131, использовать как input для S132+)

### Приоритет P1 (планировать в S132-S133):

**TD-008 — Audit facade split (394 LOC → 3 sub-facades)**
- File: `src/backend/core/audit/facade.py`
- План: split на `audit/facade_emit.py` (events), `audit/facade_query.py` (read), `audit/facade_admin.py` (config). Re-export из facade.py для back-compat.
- Tests: 1 file ~20 tests (parametrized by facade method).
- Estimate: 2-3 days. **Refactor > 1 wave = analysis-only OR 1 commit с measured LOC reduction.**

**TD-010 — DSL AI methods (ai_invoke, ai_tool_dispatch)**
- Files: `src/backend/dsl/builders/agent_dsl.py` уже имеет 15 методов (verified S130). Реальный gap: `ai_orchestrator_dispatch`, `ai_stream_response`, `ai_rag_query`, `ai_memory_persist`.
- Pattern: следовать `policy_mixin.py:policy_chain()` как reference.
- Estimate: 1 day per method, 4 methods = 4-5 days.

**TD-011 — DSL source/sink для NATS, MongoDB, gRPC stream**
- Files: `src/backend/dsl/builders/sources_mixin/` (уже есть adapters, нужны fluent methods).
- Pattern: `from_nats(subject)`, `from_mongodb(collection, query)`, `from_grpc_stream(service, method)`.
- Estimate: 1 day per builder + tests.

### Приоритет P2 (S134+):

**TD-013 — Streamlit feature-grouping (73 pages → 8 groups)**
- Pattern: `pages/30_AI/*`, `pages/31_DSL/*`, etc. Reference: `31_DSL_Visual_Editor/_editor/` sub-package.
- Estimate: 2-3 days refactor + smoke tests.

**TD-031 — Layer linter 26 NEW violations (post-S127)**
- File: `tools/check_layers.py` output.
- Plan: bulk-add в `EXTENSIONS_FRAMEWORK_EXCEPTIONS` или fix (refactor imports).
- Estimate: 1-2 days.

### Stale-OPEN (требует re-verify):

**TD-016** — `test_smart_session_manager_wire.py::test_bundle_carries_replica_session_maker` — register говорит 🔴 OPEN, но S131 W3 commit `0498f682` уже зафиксил. Требуется: re-run `pytest test_smart_session_manager_wire.py::test_bundle_carries_replica_session_maker -x` для подтверждения, обновить register на 🟢 CLOSED.

**TD-006** — baseline allowlist tool exists, но `test_llm_structured`, `test_s56_w2_airflow_operators`, `test_idp_pipeline_processor` могут быть latent. Классифицировать через `git stash` + retest.

---

## 15. БИБЛИОТЕКИ (уже в deps, НЕ добавлять новые)

```
[ai]            → nemoguardrails, instructor, litellm, pydantic-ai
[ai-2026]       → mem0 REMOVED, replaced by UnifiedMemoryGateway (in-house)
[resilience]    → purgatory (canonical CB)
[cache]         → aiocache
[otel]          → opentelemetry
[cdc]           → debezium + aiokafka
[di]            → dishka
[rate-limit]    → limits
[messaging]     → aiokafka, aio-pika, redis streams, nats-py
[storage]       → aioboto3, s3fs
[auth]          → python-jose, passlib, ldap3
[temporal]      → temporalio
```

Ничего нового добавлять не нужно — все библиотеки, которые упоминались в v1-v4 (guardrails-ai, mem0ai, dishka) либо уже в deps, либо были заменены на in-house реализации (UnifiedMemoryGateway, UnifiedRateLimiter).

---

## 16. ОБЯЗАТЕЛЬНЫЕ ССЫЛКИ

- `CLAUDE.md` V22 — source of truth для архитектуры
- `PLAN.md` V23 — historical reference (отстаёт на ~90 спринтов, не использовать как current plan)
- `reports/reaudit/tech_debt_register.md` — ЕДИНСТВЕННЫЙ source of truth для OPEN TDs
- `reports/reaudit/CHANGELOG.md` — история closed TDs (ADR refs)
- `tools/check_layers.py` — layer linter (CI gate)
- `tools/check_test_baseline.py` + `allowlist` — pre-existing test gate
- `tools/check_protocol_coverage.py` — protocol handler coverage
- `tools/check_audit_deprecation.py` — audit facade canonical enforcement
- `tools/check_docstrings.py` — docstring ratchet
- Skills: `sprint-execution`, `verify-analysis-claims`, `systematic-debugging`, `library-vs-custom-gate`, `subagent-driven-development`

---

## 17. CHANGELOG (master prompt версии)

- **v5 (this file, 2026-06-15, post-S131):** synthesis v1+v2+v3+v4 → 17 sections, real backlog from S131 TD register (TD-008/010/011/013/031 + stale-OPEN TD-016/006), updated FACADE MATRIX with `FallbackObjectStorage`, `VariableMixin`, `DaskMixin`, `TransformCdcEvent`, `FileStreamGRPCServicer`, `ConsulCertBackend`, `PromptCacheMiddleware`. Real sprint health 9.8/10, 168 ADRs, 37 CLOSED TDs.
- **v4 (S126 era, 2026-06-14):** 525 lines, 22-domain verification matrix, 9 OPEN P0/P1 items (all closed by S131). Superseded.
- **v3 (S109 era):** 30-point matrix, partially stale. Archived.
- **v2 (DEEP-RESEARCH, 2026-06-12):** 22-domain ro-analysis, 60-80% fabricated. Archived to `gap-analysis/`.
- **v1 (early 2026):** 22-domain initial analysis. Mostly outdated.

---

## 18. NEXT SPRINT INPUT

S132 W1 = pre-flight factcheck на 6 OPEN/PARTIAL TDs (1 commit, `reports/sprint/s132_w1_factcheck.md`).
S132 W2-W4 = pick 1-2 from {TD-008 split, TD-010/011 DSL methods}, atomic commits.
S132 W5 = closure (CHANGELOG + ADR-0219 + INDEX update, 1 commit).
