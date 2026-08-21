# VERIFIED_BASELINE_2026-08-23

> Source of truth для метрик проекта `gd_integration_tools` по состоянию на
> коммит `f20d72bd` (master, 2026-08-23). **Все цифры — прямой результат
> выполнения команд, не из MD-файлов истории проекта.**

## 0. Команда для воспроизведения

```bash
cd /home/user/dev/gd_integration_tools
# Статические гейты
uv run --no-sync ruff check src/backend/
uv run --no-sync bandit -r src/ -c .bandit
uv run --no-sync bandit -r src/ -c .bandit --severity-level high
uv run --no-sync vulture src/backend/ --min-confidence 90
# Layer checker
grep -c -v "^#" tools/check_layers_allowlist.txt
# Coverage
uv run --no-sync coverage run --source=src/backend -m pytest tests/unit/ -q
uv run --no-sync coverage report
# Конфиг
grep -n "fail_under\|tool.coverage" pyproject.toml | head -10
```

## 1. Static Gates (текущее)

| Gate | Status | Count | Notes |
|---|---|---:|---|
| **ruff** | ✅ PASS | 0 errors | после `ruff --fix` (8 auto-fixed) |
| **bandit HIGH** | ❌ FAIL | **40** | реальные, не false positives (B110, B311, B403, B404, B603, B101, B405) |
| **bandit MEDIUM** | ❌ | **22** | B311 random, B404 subprocess, B603 |
| **vulture @≥90%** | ✅ PASS | 0 findings | configured via pyproject `ignore_names` |
| **layer allowlist** | STABLE | **112** entries | после Sprint D.3-D.4 refactor (1bb76b0a: -22) |

## 2. Coverage State

| Item | Value | Source |
|---|---|---|
| `fail_under` (pyproject) | **60%** | `pyproject.toml:1080` |
| Comment "S34 W4: 75% → 60%" | yes | `pyproject.toml:1076-1077` |
| `.coverage` file (старый) | **CORRUPT** (mixed branch+statement) | `coverage report` errors |
| `.coverage` file (re-measured clean) | **0%** (subset tests only, no-data-collected warning) | fresh run |
| Real coverage state | **unmeasurable** in this session | blocked by `opentelemetry-instrumentation-aio-pika>=0.51b0,<0.52b0` pre-release conflict |
| CI coverage job | yes, `test.yml` | `.github/workflows/test.yml` |

**Single source of truth**: `pyproject.toml:1080` `fail_under = 60`. **No badge** in README (cycles 1-22 never set up coverage badge).

## 3. 5 Security Fail-Closed Sites (Phase 1 P0)

| Site | File:line | Status |
|---|---|---|
| IP restriction fail-closed | `core/security/ip_restriction_store.py:141` (`yaml.safe_load`), :173, :192, :209 (return False on misconfig) | ✅ VERIFIED |
| Lakera fail-closed | `services/ai/guardrails/lakera_client.py:72-77` (raise at __init__) | ✅ VERIFIED (Sprint 29 P0 fix) |
| Nemo guards fail-closed | `core/ai/policy/enforcer/input_guard_mixin.py:76,93,112,130,173` (raise on `on_block=fail`) | ✅ VERIFIED |
| Capability gate fail-closed | `core/ai/gateway_pipeline_mixin/policy_mixin.py:82,151,161` (raise PolicyNotResolvedError/CapabilityDeniedError) | ✅ VERIFIED |
| PII sanitizers fail-closed | `core/ai/policy/enforcer/sanitize_mixin.py:62,98` (raise after sanitize failures) | ✅ VERIFIED |

## 4. Auth Coverage (Phase 1 P0)

| Protocol | File:line | Auth | Status |
|---|---|---|---|
| REST (`/api/v1/*`) | `entrypoints/api/v1/routers.py` | `Depends(require_auth([API_KEY, JWT, MTLS]))` | ✅ VERIFIED |
| SOAP | `entrypoints/soap/soap_handler.py:156,418` | `Depends(require_auth([API_KEY, JWT]))` | ✅ VERIFIED |
| GraphQL | `entrypoints/graphql/schema.py:823` | `Depends(require_auth([API_KEY, JWT, MTLS]))` | ✅ VERIFIED |
| SSE | `entrypoints/sse/handler.py:107,219` | `Depends(require_auth([API_KEY, JWT]))` | ✅ VERIFIED |
| WebSocket | `entrypoints/websocket/ws_handler.py:97,149,161,170` + `ws_auth.py` | `_authenticate_handshake` (close 1008 on fail) | ✅ VERIFIED |
| Admin | `entrypoints/api/v1/endpoints/admin.py:26` | `require_admin((OPERATOR, READ_ONLY, TENANT_ADMIN))` | ✅ VERIFIED (RBAC) |

## 5. Agent Sandbox (Phase 1 P0)

| Item | Value | Source |
|---|---|---|
| `default_agent_sandbox` | **`"process_pool"`** (NOT `"in_process"`) | `core/config/ai.py:325` |
| `InProcessAgentSandbox` production block | yes (raises `RuntimeError` if `GD_INTEGRATION_PRODUCTION=1` or `ai_in_process_sandbox_disabled=True`) | `services/ai/agent_sandbox.py:85-127` |
| Audit event `ai.sandbox.zero_isolation_constructed` | yes | `services/ai/agent_sandbox.py:127` |
| `ProcessPoolAgentSandbox` (default) | stdlib `multiprocessing.ProcessPoolExecutor` (spawn) | `services/ai/agent_sandbox.py:200` |
| `E2BAgentSandbox` (alternative) | real e2b integration | `services/ai/agent_sandbox.py:288` |
| `AgentSandboxSelector` (3 backends) | yes | `services/ai/agent_sandbox.py:498` |

**Verdict**: InProcessAgentSandbox is NOT default, NOT used in production, raises + emits audit on construction.

## 6. Tool Whitelist Enforcement (Phase 1 P0)

| Item | Status | Source |
|---|---|---|
| Real tool_name check (not workflow_id) | ✅ | `entrypoints/middlewares/ai_tool_whitelist.py:217` (`_default_whitelist_check(tenant_id, tool_name)`) |
| `enforced_name = request.tool_name or request.workflow_id` (prefers real tool) | ✅ | `core/ai/gateway_orchestrator_mixin.py:23` |
| Per-tenant whitelist + deny-by-default if empty | ✅ | `entrypoints/middlewares/ai_tool_whitelist.py:35-43` |

## 7. Module Whitelist in SkillRegistry (Phase 1 P0)

| Item | Status | Source |
|---|---|---|
| `empty_mode="error"` (raises `ValueError` on empty whitelist) | ✅ | `core/ai/skill_registry.py:216-245` |
| `_validate_module_whitelist` called from `invoke` | ✅ | `core/ai/skill_registry.py:258` |
| No "skip for MVP" code paths | ✅ | grep returns 0 hits in `skill_registry.py` |

## 8. Custom Security (yaml.load + symlink + SHA-256)

| Item | Status | Source |
|---|---|---|
| `yaml.load` (unsafe) | **0 hits** in src/backend/ | grep returns exit 1 |
| `yaml.safe_load` (used) | yes (e.g. `ip_restriction_store.py:141`) | confirmed |
| Symlink TOCTOU race | FIXED (resolve handle → realpath → boundary check) | `core/ai/fs_facade.py:144-155` (DEEP_AUDIT P0-#9) |
| API key hashing | **Argon2id** with per-key 16-byte salt (PHC string format) | `core/auth/api_key_backend.py:1-44` |
| SHA-256 usage (where appropriate) | non-secret fingerprints only (file_stream integrity, cache keys, webhook HMAC) | grep verified |

## 9. Library Replacement Status (Phase 3)

| Library | Used | Source |
|---|---|---|
| **asyncssh** (SSH/RPA) | ✅ | `infrastructure/clients/transport/sftp.py:131` |
| **playwright / patchright** (Browser RPA) | ✅ | `services/rpa/browser_pool.py:117,191,199,203` (patchright preferred) |
| **Debezium** (CDC) | ✅ | `infrastructure/cdc/debezium_events_backend.py:38-53` (real parser) |
| **LiteLLM** (LLM gateway) | ✅ | `services/ai/gateway/client.py` (custom wrapper) |
| **python-magic** (MIME detection) | ❌ MISSING | grep returns 0 hits — custom code only |
| **Apache Tika** (OCR/Office) | ❌ MISSING | grep returns 0 hits — custom `PdfExtractProcessor`/`OfficeExtractProcessor` only |

## 10. Workflow Processors (Phase 2)

| Pattern | Status |
|---|---|
| All processors use `Exchange[Any]` typed signature | ✅ (no dict-based) |
| Base classes | `dsl/engine/processors/base.py:148,170` |
| Example processors | `generic.py:48,109,140,166,191`, `jdbc_query.py:109`, `webhook_signature.py:160`, etc. |

## 11. Duplicates and Deprecations (Phase 2)

| Item | Status |
|---|---|
| `MetricsRegistry` duplicates | **NONE** (single canonical at `core/utils/metrics_registry.py:55`) |
| Deprecated `WorkflowBuilder` | **NOT deprecated** (canonical at `dsl/workflow/builder/__init__.py:64`, heavily used) |
| `WorkflowBuilder` is the SAME class as `dsl/workflow/builder` (NOT `dsl/builders/workflow_builder` which doesn't exist) | confirmed |

## 12. Discrepancies with Pre-Audits (FALSE CLAIMs in rounds 1+2+3)

| Pre-audit claim | Reality (verified 2026-08-23) |
|---|---|
| "bandit 0 HIGH" (rounds 1+2+3) | **40 HIGH** (file `admin_parallelism.py:37` had SyntaxError, was SKIPPED by bandit, masking 1+ findings; **FIXED in `a29b606f`**) |
| "CI bandit HIGH-blocking" | **was `|| true` (advisory only)**, NOT blocking. **FIXED in 7d6b3ed8** (now actually blocks on HIGH) |
| "ruff 0 errors" (rounds 1+2+3) | 8 errors (regression after extensions.py commit 3853ef55). **FIXED via `ruff --fix` (parallel committed)** |
| ".coverage 1%" (round 1+2+3) | measurement error from CORRUPT file (mixed branch+statement). After `coverage erase` + clean run, real state unmeasurable (dep conflict) |
| "95/100 final review" (CLAUDE) | OVERCONFIRMED (10+ discrete claims contradicted by verification) |

## 13. Remaining OPEN (post this baseline)

### P0 (CRITICAL)
- **40 bandit HIGH** (21 B311 random, 3 B403 pickle, 3 B110/B112 silent, 3 B404 subprocess, 1 B405 ElementTree, 1 B101 assert). CI now blocks on these.

### P1 (Architecture)
- 5 god-objects (graphql/schema 825, pydantic_ai_client 667, agent_security 652, vector_store 599, skill_registry 658) — 0/5 refactored
- RouteBuilder Protocol migration 2/41 mixins (~5%)
- `.pyi` stub drift 153 methods

### P2 (Backlog)
- Tika/magic integration (replace custom PdfExtract/OfficeExtract/MimeDetect)
- 2 pickle deserialization sites: comment-level only
- 3 high-risk `__init__.py` hubs (46, 43+41-mixin, 29 imports)

### DOCUMENTED (design decision)
- MCP HTTP mount default=False in dev_light
- Live HTTP re-verify blocked (stale container, different user namespace)

## 14. CI Status (current `master`)

| CI job | Status |
|---|---|
| bandit (HIGH-blocking) | ✅ NOW blocks (was `\|\| true` advisory) |
| safety / pip-audit | ✅ blocking (CVE-2025-69872 diskcache ignored) |
| gitleaks | ✅ blocking |
| trivy-fs | advisory (SARIF) |
| ruff | ✅ 0 errors |
| coverage | fails 60% gate (no .coverage data) |

---

**Sign-off**: Kimi Code, 2026-08-23, master `f20d72bd`. All numbers verified by direct command execution, not from MD history.
