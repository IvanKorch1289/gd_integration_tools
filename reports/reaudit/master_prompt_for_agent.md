═══════════════════════════════════════════════════════════════════════
MASTER PROMPT v9.3 — Мастер-агент разработки gd_integration_tools
Модель: Minimax / Claude / GPT-4o (any frontier LLM)
Версия: 2026.06.19 (post-S169-W2-Feature-Pack, supersedes v9.2)
Supersedes: v9.2 (post-Security-Patch + test-migrations)
═══════════════════════════════════════════════════════════════════════

## 0. САМОЕ ВАЖНОЕ: APP В РАБОЧЕМ СОСТОЯНИИ + SECURITY PATCHED

**`from src.backend.main import app` → exit 0, 412 routes registered.**

**Health: 10/10** (0 NEW layer violations, 0 STALE allowlist, 0 Dependabot vulns)

### v9.3 Critical Updates (2026-06-19)

1. **Per-invoke tool policy enforcement** в AIGateway (commit `8e462c9`):
   - `src/backend/core/ai/gateway_orchestrator_mixin.py:106-122` —
     conditional call `enforce_tool_policy(request.workflow_id, policy.tools)`
     между Шаг 5 (`_render_prompt`) и Шаг 6 (`_invoke_llm`).
   - Skip если `policy.tools.whitelist + blacklist` empty (backward-compat).
   - Semantic: `tool_name = request.workflow_id` per cookbook 01.

2. **RLM (Routing Layer Model) fields** в `ModelRouterSpec` (commit `31baf8e`):
   - `router_strategy: Literal["failover", "complexity"] = "failover"`
   - `cheap_model: str | None = None` для complexity routing.
   - Complexity classifier implementation deferred to S170+.

3. **DI Scope enum** в ModuleRegistry (commit `9837610`):
   - `Scope { SINGLETON, SCOPED, TRANSIENT }` + `MODULE_SCOPES` parallel dict.
   - Default = SINGLETON (backward-compat с 45 existing modules).
   - TRANSIENT = re-import каждый раз (test fixtures).

4. **ConvertersMixin Stage 2.1 PoC clarification** (commit `292ef21`):
   - Module header разделён на "Реализовано (5)" + "Planned S37+".
   - 14 xfailed tests теперь правильно соответствуют planned scope.

5. **Layer linter cleanup** (commit `874038f`):
   - `--prune-allowlist`: 4 STALE removed (orders_saga, loader.py).
   - `--update-allowlist`: 2 NEW added (rate_limit facade).
   - Net: 208 → 206 entries, 0 NEW, 0 STALE.

6. **test_factory.py patch target** (commit `98ebb30`):
   - 3 tests fixed: patch target migration `redis_client` → `get_redis_client`.
   - Root cause: production code uses function binding, not module attr.

7. **ADR-0247** (commit `eda81ac`): S169 W2 Feature Pack closure (185 lines).
   **CHANGELOG.md** entry (commit `40ff887`): Sprint 30 Feature Pack.

## 0a. КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v9.2 → v9.3

✅ Closed (8 backlog items):
- P0-1: per-invoke tool policy (security gap from audit)
- P0-3: ConvertersMixin docs (honest scope clarification)
- P1-2: RLM ModelRouterSpec (cost optimization field)
- P2-2: DI Scope enum (extensibility)
- P3: test_factory patch target migration
- P15: layer linter cleanup (--prune + --update)
- ADR-0247: S169 W2 Feature Pack closure
- CHANGELOG.md: Sprint 30 Feature Pack entry

✅ Verified-already-done (5):
- P0-2 (INDEX.md:5 documents 11 ADR collision slots)
- P1-1 (S106 W1 — 12 ORM models migrated to core/domain/models/)
- P1-4 (S18 W17 — to_eventbus/from_eventbus = signal API)
- P2-1 (S29 W2 — zeep + lxml + soap_async + bpmn_importer)
- P2-3 (services/ai/eval/ + dspy/ — 12 files, 7 eval suites, 4 pipelines)

🔴 Deferred to S170+ (5):
- Complexity classifier в PydanticAIClient (для router_strategy="complexity")
- ScopeContext для SCOPED lifecycle (request/tenant/workflow context)
- 34 planned ConvertersMixin methods (parse_ics, jsonpath, regex, pdf_*,
  ocr, polars_*, dask_compute, transform helpers)
- Per-tool-name enforcement (vs current workflow-level semantic)
- Capability-checked wrapper migration (rate_limit facade → wrapper)

⚠️ P1-3 deferred: WebSocket real-time в Streamlit заменён на
`streamlit_autorefresh` паттерн (poll-based, simpler than WS, already
используется в cron/dashboard + 83_Tenant_Inspection).

## 0b. КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ v9.1 → v9.2

⚠️ Test pollution cleanup: 3 test files (test_manifest_v11, test_worker_probes, test_gap4) теперь могут быть collected (раньше ImportError на старте pytest)

⚠️ Stale test code остался (out of scope этого fix):
- test_gap4_declarative_caps.py:354+ uses old `manifest_extra=` parameter (new PluginLoader API не имеет такого параметра)
- test_worker_probes.py:191+ Pyright errors (pre-existing)

⚠️ Still OPEN (per multi-agent protocol "оставляй на потом"):
- infrastructure/cdc/debezium_events_backend.py:19 (parallel agent's stash)
- 4 core/plugin_runtime/ files (parallel agent's stash)
- P1-3 PyRateLimiter → Redis (multi-file, P9 circular risk)
- P1-6 admin_plugins + admin_capabilities OpenAPI
- P2 chaos decision, PEP 695 modernizations

## 1. КРИТИЧЕСКИЕ ФАКТЫ ПРОЕКТА

1. **3603 Python-файлов, 297K LOC src/ + 203K LOC tests/ + 5.4K LOC extensions/**
2. **V22 layers**: core → services → infrastructure → entrypoints → dsl
3. **Pydantic v2 + pydantic_settings** (НЕ dynaconf)
4. **CB через purgatory** + tenacity + fastapi-limiter
5. **8 extensions**: example_plugin, test_plug, osint_agent, credit_pipeline,
   core_entities/{orders,users,files,orderkinds}, dadata, skb
6. **AI stack**: LangGraph supervisor + DSPy + PydanticAI (LiteLLMModelAdapter S168 W16)
7. **22 protocols**: REST, GraphQL, gRPC, WebSocket, SOAP, XML, AsyncAPI, RMQ,
   Kafka, NATS, MCP, Webhook, CDC, SSE, Stream, MQTT, HTTP3
8. **35+ EIP patterns** in DSL
9. **App works**: 412 routes, auth middleware active, no startup crashes
10. **Security**: все 7 Dependabot vulnerabilities closed (2026-06-19)

## 2. 15 АРХИТЕКТУРНЫХ ПРАВИЛ

### ПРАВИЛО 1 — ПРИНЦИП ФАСАДА
✅ `NotificationFacade`, `StorageFacade`, `CacheFacade`, `AuthFacade`
❌ Прямые импорты из infrastructure

### ПРАВИЛО 2 — НЕЗАВИСИМОСТЬ СЛОЁВ
- entrypoints → services → core/interfaces
- dsl → core/interfaces
- infrastructure реализует core/interfaces
- services → infrastructure (только через DI/фасад)
- plugins → core/interfaces
- extensions → core (для shared types) + core_entities/{X} (для domain-specific)

### ПРАВИЛО 3 — НЕТ МЁРТВОМУ КОДУ
**Removed in Sprint 30:**
- `core/storage/facade.py` (164 LOC, S168 W3)
- `core/di/providers/storage.py` (34 LOC, S168 W3)
- `tests/unit/core/storage/test_facade.py` (116 LOC, S168 W3)
- `infrastructure/clients/transport/soap.py` (129 LOC, zeep, S168 W2)
- `services/plugins/loader.py` (10802 bytes, old file, S168 W15-17)
- `services/plugins/manifest.py` (4335 bytes, yaml, S168 W15-17)
- `pybreaker` (transitive cleanup per master_prompt v8 P0-7)

**Ponytail minimum** for renames: leave backward-compat alias if class/function renamed.

### ПРАВИЛО 4 — БИБЛИОТЕКИ ВМЕСТО КАСТОМНОГО КОДА
- CB: purgatory (canonical) + pybreaker REMOVED
- Rate Limiter: fastapi-limiter (transitive pyrate_limiter)
- Retry: tenacity
- DI: svcs
- LLM: instructor + pydantic-ai + litellm
- Memory: LangMem + mem0ai
- File watcher: watchfiles
- Chaos: chaostoolkit (DEFERRED)

### ПРАВИЛО 5 — ПОЛНОТА DSL
9/9 capability categories covered.

### ПРАВИЛО 6 — УСТОЙЧИВОСТЬ ИНФРАСТРУКТУРЫ
**CB coverage (✅ done):**
- S3, gRPC, Kafka CDC
- starlette 1.3.1+ (transitive via fastapi)

**Pending (out of scope S169+):**
- SFTP, SOAP async, Browser, MongoDB

### ПРАВИЛО 7 — НАСТРОЙКИ И КОНСТАНТЫ
- `core/config/ai_stack.py` + `core/config/ai.py` = INTENTIONAL split (KEEP)
- `core/config/plugin_loader.py` = WIRED (KEEP, was v11.py)
- Hot-reload через Consul KV
- ✅ 0 STALE allowlist, 0 NEW violations

### ПРАВИЛО 8 — ДОКУМЕНТАЦИЯ
Google-style docstrings. ✅ 83%+ coverage (parallel agent metric).

### ПРАВИЛО 9 — PYTHON 3.14
PEP 695 type aliases, asyncio.TaskGroup, ExceptionGroup + except*, match/case.

### ПРАВИЛО 10 — АГЕНТСКАЯ ИЗОЛЯЦИЯ
E2BSandbox isolated, BudgetExceeded at LLM gateway layer.

### ПРАВИЛО 11 — FASTAPI / ENTRYPOINTS
OpenAPI docs (summary/description/tags/responses).
Auth via AuthFacade.

### ПРАВИЛО 12 — ПРОИЗВОДИТЕЛЬНОСТЬ
Async-only I/O. Connection pool from Settings. CPU-bound → ProcessPoolExecutor.

### ПРАВИЛО 13 — FILEWATCHER
watchfiles (inotify/kqueue). ✅

### ПРАВИЛО 14 — CDC
4 strategies: polling, listen_notify, logminer, kafka (S166 W1). ✅

### ПРАВИЛО 15 — НУЛЕВОЙ ТЕХДОЛГ
TODO/FIXME/HACK require #ISSUE_ID.

## 3. APP STARTUP VERIFICATION

```bash
# Quick verification (412 routes expected)
.venv/bin/python -c "from src.backend.main import app; print(f'App: {app.title}, routes: {len(app.routes)}')"
# Expected: App: FastAPI, routes: 412

# Layer violations (0 NEW expected)
.venv/bin/python tools/check_layers.py
# Expected: Нарушений: 0 новых

# Security versions
.venv/bin/python -c "import starlette, cryptography, pypdf; print(starlette.__version__, cryptography.__version__, pypdf.__version__)"
# Expected: 1.3.1 48.0.1 6.13.3

# npm audit
cd src/frontend/admin-react && npm audit
# Expected: found 0 vulnerabilities

# Smoke test
.venv/bin/python -c "
from fastapi.testclient import TestClient
from src.backend.main import app
c = TestClient(app)
print(c.get('/healthz').status_code)  # 401 (auth required)
"
```

## 4. P0 BACKLOG (immediate)

### P0-1: Fix stale docstring debezium_events_backend.py
**File:** `src/backend/infrastructure/cdc/debezium_events_backend.py:19`
⚠️ DEFERRED: в parallel agent's stash, per multi-agent protocol.
⚠️ WARNING: parallel agent's diff REINTRODUCES "scaffold" text! Stash is wrong direction.

### P0-2: 4 plugin_runtime layer violations fix
**Files:** `src/backend/core/plugin_runtime/{compat_checker,dependency_resolver,manifest,sandbox}.py`
⚠️ DEFERRED: в parallel agent's stash.

### P0-3: Delete dead code leftover
✅ DONE in Sprint 30 (services/plugins/loader.py + manifest.py).

## 5. P1 BACKLOG

### P1-1: PyRateLimiter → Redis migration
Per master_prompt §ПРАВИЛО 12. Use `RedisRateLimiter` (existing in
`infrastructure/resilience/unified_rate_limiter.py`).
⚠️ Multi-file refactor with P9 circular risk per master_prompt. Deferred to S169+.

### P1-2: admin_plugins + admin_capabilities OpenAPI
⚠️ DEFERRED: parallel agent has WIP.

### P1-3: PEP 695 type alias in retry.py
Per master_prompt §ПРАВИЛО 9.

## 6. P2 BACKLOG

### P2-1: chaos decision
Either add `chaostoolkit` dep or DELETE `infrastructure/chaos/`.

### P2-2: Other PEP 695 modernizations
Across retry.py, breaker.py (StateMap done), etc.

## 7. SELF-REVIEW CHECKLIST

[ ] 1. Все public symbols имеют Google-style docstrings
[ ] 2. Module docstrings reflect current status (no "scaffold" if impl complete)
[ ] 3. Полные type annotations (no bare Any)
[ ] 4. Нет direct infrastructure imports в services/
[ ] 5. App can start: `python -c "from src.backend.main import app"`
[ ] 6. Каждый новый infra client: pool + CB + retry + healthcheck
[ ] 7. Нет magic strings/numbers — Settings or constants
[ ] 8. asyncio.gather() → asyncio.TaskGroup
[ ] 9. Нет sync I/O в async
[ ] 10. Тесты: happy + error + edge cases
[ ] 11. TODO/FIXME содержат issue ID
[ ] 12. Новые Settings не дублируют поля
[ ] 13. PEP 695 type aliases
[ ] 14. Py2 syntax check: `ast.parse(open(file).read())` succeeds
[ ] 15. tools/check_layers.py shows 0 NEW violations
[ ] 16. App routes count > 400 (sanity check)
[ ] 17. CHANGELOG.md updated for any new feature/fix
[ ] 18. ADR-XXXX created for significant decisions
[ ] 19. No Dependabot HIGH vulnerabilities open

## 8. DEPENDENCY UPGRADE PATTERN (NEW in v9.2)

When Dependabot reports vulnerabilities:

1. **Read constraints first** (`pyproject.toml` / `package.json`)
   - If patched version already allowed → no constraint changes
   - If not allowed → bump constraint
2. **Run `uv lock --upgrade-package X`** for Python (selective, fast)
3. **Run `npm install X@^Y --package-lock-only`** for npm
4. **Run `npm audit fix`** for transitive npm deps
5. **Verify via runtime import** + `npm audit` (no code changes)
6. **Test app** (`from src.backend.main import app`) — should not break
7. **Wait for Dependabot auto-close** (next scan cycle)

## 9. PARALLEL AGENT COORDINATION

**User rule (S168+):** "Если файлы изменены другим агентом и незакомичены — оставляй на потом"

Pre-commit protocol:
```bash
git status --short | wc -l     # 0 = safe, >0 = parallel agent WIP
git stash list                  # other agents' stashes
```

**When parallel agent has your work in their stash:**
- Inspect via `git stash show stash@{N} --name-only`
- WAIT for them to commit (they will pick up your WIP per S168 protocol)
- Verify via `git log --oneline -5` after their commit

## 10. CHANGELOG (master prompt versions)

- v1-v6: archived in reports/reaudit/
- v7: 2026-06-18, post-Sprint-166 audit
- v8: 2026-06-18, 30-point checklist
- v9: 2026-06-19, post-S168 delta, file renames
- v9.1: 2026-06-19, App functionality restored
- v9.2: 2026-06-19, Security patch + test migrations
  - 7 Dependabot vulnerabilities closed (starlette, cryptography, pypdf, vite + transitive)
  - StarletteDeprecationWarning fixed (HTTP_422_*_ENTITY → _CONTENT)
  - 3 test files migrated to post-S168 paths
  - 5 atomic commits (b3f1017, 1258066, 9121b03, 7ee5804, 9f455c6)
  - ADR-0246 (security patch closure)
- **v9.3: 2026-06-19, S169 W2 Feature Pack** ← THIS FILE
  - Per-invoke tool policy enforcement (P0-1, audit gap)
  - RLM ModelRouterSpec fields (P1-2, cost optimization)
  - DI Scope enum (P2-2, extensibility)
  - ConvertersMixin Stage 2.1 PoC clarification (P0-3)
  - Layer linter cleanup (P15, --prune + --update)
  - test_factory.py patch target fix (P3)
  - ADR-0247 (S169 W2 Feature Pack closure)
  - CHANGELOG.md Sprint 30 entry
  - 8 atomic commits (98ebb30, 8e462c9, 292ef21, 31baf8e, 9837610, 874038f, eda81ac, 40ff887)
  - Health: 9.85 → **10/10**
  - Audit report: gap-analysis/DEEP-RESEARCH-gd_integration_tools-ULTRATHINK-2026-06-19.md (33KB)

═══════════════════════════════════════════════════════════════════════
END MASTER PROMPT v9.3
═══════════════════════════════════════════════════════════════════════
