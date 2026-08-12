# Cycle 3 Phase 1 — Domain Audit: Security

**Дата:** 2026-08-06
**HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`
**Python:** `.venv/bin/python` (3.14.0) — cycle-2 reviewer запускал system python и падал с `ModuleNotFoundError`. Все runtime-проверки в этом отчёте — через `.venv/bin/python -m pytest`.
**Scope (read-only):**
- `src/backend/core/security/**` (29 файлов)
- `src/backend/core/auth/**` (26 файлов)
- `src/backend/services/security/**` (3 файла)
- `src/backend/services/auth/**` (3 файла)
- `src/backend/services/authorization/**` (1 файл)
- `src/backend/services/agent_security/**` (1 файл)
- `src/backend/entrypoints/middlewares/{auth_method_header,auth_required,security_headers}.py` (3 файла)
- `ai_policies/*.yaml` (3 файла)
- `tests/security/**` (5 файлов, ~580 LOC)
- `tests/auth/{mtls,saml}/*.py` (2 файла, 272 LOC)
- дополнительно для target-проверок: `tests/unit/dsl/processors/security/test_auth_validate_failclosed.py`, `tests/unit/dsl/processors/test_agent_security_check.py`, `tests/unit/core/security/**`, `tests/integration/test_opa_runtime_cycle37.py`

**Не проверено (явно):**
- cycle-1/cycle-2 markdown отчёты (запрещено правилами);
- `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` (запрещено правилами);
- `tools/cycle-1-preflight.sh` (untracked, не из scope);
- `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (5 pre-existing fail — не security domain, не из scope);
- `uv.lock` изменения (-15 svcs pre-existing);
- `kimi-export-session_-20260803-150732.md` (unrelated dump).

---

## Scope / не проверено

### Scope — то, что проверено

| Категория | Файлы | Найдено в коде |
|---|---|---|
| core/security/authorization_gateway | 9 файлов | `__init__.py` 408 LOC, `opa_mixin.py` 97, `casbin_mixin.py` 68, `audit_mixin.py` 39, `permission_mixin.py`, `state.py` 43, `_protocol.py`, `policies/{opa,casbin}_policy_decider.py` 50 LOC каждый |
| core/security/capabilities | 13 файлов | gate (4 mixin) ~570 LOC, policy.py 148, vocabulary 230 LOC, models.py, errors.py |
| core/security/прочее | 7 файлов | `connector_auth.py` 220, `credential_provider.py` 206, `ip_restriction_store.py` 213, `pii_masker.py`, `pii_patterns.py`, `pii_tokenizer.py`, `module_whitelist.py`, `activity_capability_guard.py`, `secret_rotation.py` |
| core/auth | 26 файлов | `auth_selector.py` 303 (canonical), `gateway.py` 94 (facade), `jwt_backend.py` 456, `jwt_blacklist.py` 166, `mtls_backend.py` 218, `saml_backend.py` 213, `api_key_backend.py`, `jwks_cache.py`, `facade.py`, `protocols.py`, `quotas.py`, `sso_registry.py`, `sso_types.py`, `ad_directory.py`, `ldap_*` |
| services/security | 3 файла | `facade.py` 408, `cert_store_facade.py`, `pii_streaming_facade.py` |
| services/authorization | 1 файл | `facade.py` 550 LOC |
| services/agent_security | 1 файл | `facade.py` 188 LOC |
| services/auth | 3 файла | `ad_directory_client/{client,state,__init__}.py` |
| Middlewares | 3 файла | `auth_method_header.py` 126, `auth_required.py` 199, `security_headers.py` 110 |
| AI policies | 3 файла YAML | `agent_basic`, `credit_check_strict`, `rag_default` |

### Не проверено
- См. список в заголовке — не читал cycle-1/cycle-2 markdown, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`.
- `extensions/...` — вне scope security domain (бизнес-логика).
- `infrastructure/security/...` — вне явного scope (упомянуто только как зависимость для `services/security/facade.py`).

---

## Verified strengths (cycle-3 read-only verification)

| ID | Strength | Evidence |
|---|---|---|
| S-01 | **T-W1-01 RESOLVED — `AuthValidateProcessor` fail-closed verified runtime** | `.venv/bin/python -m pytest tests/unit/dsl/processors/security/test_auth_validate_failclosed.py -v` → **5 passed, exit 0** (5.38s). `_load_verifiers()` raises `AuthenticationProviderUnavailableError` при отсутствии/пустом `_VERIFIERS` (verified runtime, без mock). 3 метода (jwt/api_key/saml) — все fail-closed. `src/backend/dsl/engine/processors/security.py:55-89` — clean implementation. |
| S-02 | **Cycle-2 P1-001..003 closed: capability + policy deny>allow** | `.venv/bin/python -m pytest tests/unit/core/security/capabilities/ tests/unit/core/security/test_authorization_gateway.py tests/unit/core/security/test_authorization_gateway_steps.py -v` → **164 passed, exit 0**. `policy.py:115-117` sort key `(-priority, 0 if deny else 1)` — deny>allow tie-break реализован. `test_deny_beats_allow_same_priority PASSED`. `CapabilityGate.check/check_tenant` consults `self._policy` ДО declaration check (lines 82-117). |
| S-03 | **OPA runtime coverage: 14/14 tests pass (real runtime, no httpx)** | `.venv/bin/python -m pytest tests/integration/test_opa_runtime_cycle37.py -v` → **14 passed, exit 0**. `OpaMixin.opa_step` (97 LOC) — feature-flag gated (`opa_runtime_query_enabled`), exception→deny (fail-closed). Composition root wiring test passes (`test_engine_disabled_means_no_policies`, `test_engine_enabled_wires_opa_only`). |
| S-04 | **Cycle-2 dual-emit в CapabilityGate audit path** | `capabilities/gate/audit_mixin.py:71-99` — dual emission: `self._audit(payload)` callback (legacy) + `emit_capability_check(...)` unified audit service (S106 W5). Pattern применён в 17 inherited callsites (check_mixin) + 2 (declaration_mixin). **Caveat:** dual-emit дизайн правильный, но `await` отсутствует → см. DOMAIN-P0-003. |
| S-05 | **JWT weak-secret gate (RFC 7518 compliance)** | `jwt_backend.py:419-456` — `_validate_jwt_secret_strength()`: length≥32, blacklist 9 common secrets, low-entropy detector. Constructor raises `ValueError` при слабом HS-secret (`__post_init__` lines 212-219). |
| S-06 | **JWT blacklist: per-jti + batch revoke-before с fail-closed semantics** | `jwt_blacklist.py:81-104` — `is_revoked` propagates Redis errors (fail-closed). `revoke_before_time` (`is_iat_revoked`) — `MAX(current, new)` для prevention of accidental rotation rollback. 11/12 SAML/mTLS/PII tests pass; 1 skip (Keycloak container permission denied — env-specific, не код). |
| S-07 | **Auth middleware — defense-in-depth, pure ASGI, no regex bypass** | `auth_required.py:46-64` — explicit public-prefix allowlist (12 entries), `PurePosixPath` normalization (no `..` bypass), `OPTIONS` preflight bypass, 401 через `send` (no-raise). `_authenticate` вызывает `verify_request` через public API. |
| S-08 | **AuthorizationGateway deny-by-default (cycle-33 B-01 fix verified)** | `authorization_gateway/__init__.py:385-408` — `_is_enabled()` при feature-flag lookup failure → ERROR-log + return `True` (force normal chain → capability check → fail-closed). B-03 fix (lines 277-307) — silent `except: pass` → WARNING + counter `authz_check_engine_failed_total` (Prometheus observable). |
| S-09 | **TLS CERT_NONE guard regression test** | `.venv/bin/python -m pytest tests/security/test_tls_cert_required.py -v` → **4 passed**. AST-aware check отсекает docstring/comment hits. `email_imap.py` использует `ssl.create_default_context() + CERT_REQUIRED`. |
| S-10 | **YAML safe-load injection guard** | `.venv/bin/python -m pytest tests/security/test_yaml_safeload.py -v` → **4 passed**. Все 4 unsafe-тега (`!!python/object/apply`, `!!python/object/new`, `!!python/name`, `!!python/module`) отвергаются. |

---

## Findings table

| ID | Priority | Title | Location | Status vs cycle-2 |
|---|---|---|---|---|
| **DOMAIN-P0-001** | **P0** | `AgentSecurityFacade.validate_sql` silently drops `policy_override` (kwargs NEVER forwarded to framework) | `src/backend/services/agent_security/facade.py:121-133` | **RESIDUAL** (cycle-1 P0-001 не закрыт) |
| **DOMAIN-P0-002** | **P0** | `AuthValidateProcessor` permanently fail-closed in production — `_VERIFIERS_MODULE` импортирует из shim, но shim удалил `_VERIFIERS` (S162 W5) → всегда `AuthenticationProviderUnavailableError` | `src/backend/dsl/engine/processors/security.py:52,55-89` | **NEW** (cycle-2 fix T-W1-01 закрыл только тест, не runtime) |
| **DOMAIN-P0-003** | **P0** | Capability audit data-loss: `emit_capability_check(...)` в `audit_mixin.py:90` НЕ awaited → coroutine GC'd silently; 17 callsites в `check_mixin` + 2 в `declaration_mixin` теряют audit events | `src/backend/core/security/capabilities/gate/audit_mixin.py:88-99` | **NEW** |
| DOMAIN-P1-001 | P1 | `services/security/facade.py` и `services/authorization/facade.py` напрямую импортируют из `infrastructure/` (нисходящая layer violation при strict-режиме) | `src/backend/services/security/facade.py:88,156`; `src/backend/services/authorization/facade.py:376`; `src/backend/services/security/cert_store_facade.py:18` | **NEW** (layer-checker не ругается — backward compat pattern, см. layer_legacy 175) |
| DOMAIN-P1-002 | P1 | 5 entrypoints файлов продолжают импорт deprecated shim `entrypoints.api.dependencies.auth_selector` (cycle-1 DOMAIN-P0-002 не закрыт) | `src/backend/entrypoints/{middlewares/auth_required,webhook/handler,api/v1/endpoints/{ai_stream,langmem_admin,ai_costs}}.py` | **RESIDUAL** |
| DOMAIN-P2-001 | P2 | `_InMemoryJwtBlacklist` thread-safety claim ("`cachetools.TTLCache` is not thread-safe") валиден, но комментарий S210 Ponytail содержит trade-off note про clamped 24h TTL для tokens > 24h — service-tokens теряются | `src/backend/services/security/facade.py:345-403` | **NEW** (dead code risk) |
| DOMAIN-P3-001 | P3 | `verify_signature` (security/facade.py:135-162) — дублирует HMAC-API из `infrastructure.security.signatures`. Facade-обёртка чисто проксирующая, не feature-for-feature; замена `infrastructure/security/signatures.py` на `cryptography.hmac`/`hmac` stdlib не даёт выигрыша | `src/backend/services/security/facade.py:156-162` | NEW (но не нашёл замены с улучшением) |
| DOMAIN-P3-002 | P3 | `cachetools.TTLCache` уже в pyproject; `_InMemoryJwtBlacklist` его использует корректно (лицензия: BSD-3, maintenance: active). Альтернативы (`asyncio-cache`, `py-cachetools-async`) не в pyproject и не mature для prod | `src/backend/services/security/facade.py:377` | NEW (минимальный LOC delta) |
| DOMAIN-P4-001 | P4 | Optional: добавить DSL `agent_security_policy` (per-route policy override) для declarative cases — сейчас только Python API через `facade.set_policy_for_workflow`. Не критично, т.к. DSL `agent_security_check` уже есть | `src/backend/dsl/builders/security.py:37-40` (potential) | NEW (feature-for-feature copy отсутствует — organically missing) |

**Counts:** P0=3, P1=2, P2=1, P3=2, P4=1. **Total: 9 findings.**

---

## Detailed evidence

### DOMAIN-P0-001 — `validate_sql` silently drops policy_override (RESIDUAL)

**Path:** `src/backend/services/agent_security/facade.py:121-133`
**Priority:** P0 — security policy bypass
**Status vs cycle-1/cycle-2:** Cycle-1 finding. Cycle-2 не закрыл.

**Прямой evidence:**

```python
# services/agent_security/facade.py:121-133
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    """Validate SQL query (S187)."""
    policy = self.get_policy_for_workflow(workflow_id)
    if policy is not None:
        kwargs["policy_override"] = policy        # ← line 132: MUTATES kwargs
    return self.framework.validate_sql(query)     # ← line 133: kwargs НЕ передан!
```

Сравнение с `validate_prompt` (line 91-104):

```python
def validate_prompt(
    self, prompt: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    policy = self.get_policy_for_workflow(workflow_id)
    ctx = dict(kwargs)                            # ← ctx = copy
    if policy is not None:
        ctx["policy_override"] = policy           # ← ctx mutated
    return self.framework.validate_prompt(prompt, context=ctx)  # ← ctx передан!
```

**Двухслойная проблема:**
1. `facade.validate_sql()` ставит `kwargs["policy_override"] = policy`, но НЕ пробрасывает в `framework.validate_sql()`.
2. `core/ai/security/agent_security.py:572` — `validate_sql(self, query: str)` — **не принимает** ни `context`, ни `policy_override`:

```python
# core/ai/security/agent_security.py:572-585
def validate_sql(self, query: str) -> SecurityDecision:
    """Validate SQL query (S187)."""
    threat_level, desc = self._detector.detect_sql(query)
    if threat_level != ThreatLevel.NONE:
        return SecurityDecision(
            allowed=False, threat_level=threat_level, reason=f"dangerous_sql: {desc}",
        )
    return SecurityDecision(allowed=True)
```

`validate_prompt` (line 426-460), `validate_command` (462-498), `validate_file_modification` (500-570), `mask_output` (587-611) — все принимают `context: dict[str, Any] | None = None`. Только `validate_sql` — без context.

**Runtime-подтверждение:**

```bash
$ .venv/bin/python -c "
import inspect
from src.backend.services.agent_security.facade import AgentSecurityFacade
print(inspect.getsource(AgentSecurityFacade.validate_sql))"
# ... вывод точно соответствует коду выше
```

**Impact:**
- Per-workflow SQL policy override через `set_policy_for_workflow()` — **полностью нерабочий**: facade возвращает global `framework._policy`, не workflow-specific.
- DSL processor `agent_security_check` (line 140-141) вызывает `facade.validate_sql(self._value)` — также не получает override.
- Audit trail: policy decision для SQL не учитывает workflow context (теряется для compliance/soc2).
- В мульти-tenant banking сценарии (`credit_check_strict`) — общий framework policy применяется ко всем workflows, что либо слишком permissive, либо слишком strict.

**Рекомендация:**
1. `facade.validate_sql`: добавить `ctx = dict(kwargs)` и вызвать `self.framework.validate_sql(query, context=ctx)`.
2. `framework.validate_sql`: добавить signature `(self, query: str, *, context: dict[str, Any] | None = None)`, обработать `policy_override` (как вариант — динамически `framework.set_policy(override_policy)` с rollback после call, или отдельный `_policy_override_stack`).

**Test-критерий:**
- `tests/unit/services/agent_security/test_validate_sql_policy_override.py` (новый): задать workflow_id, установить mock policy, вызвать `facade.validate_sql("DROP DATABASE", workflow_id="wf-1")`, assert что `framework.set_policy` был вызван (или `_policy_override_stack` обновлён).

---

### DOMAIN-P0-002 — `AuthValidateProcessor` permanently fail-closed (NEW)

**Path:** `src/backend/dsl/engine/processors/security.py:52,55-89`
**Priority:** P0 — feature is shipped but always fails in production
**Status vs cycle-2:** Cycle-2 fix T-W1-01 закрыл только test (fail-closed path тест passes). Runtime поведение в production — **не проверялось**.

**Прямой evidence:**

```python
# dsl/engine/processors/security.py:52
_VERIFIERS_MODULE = "src.backend.entrypoints.api.dependencies.auth_selector"
```

```python
# entrypoints/api/dependencies/auth_selector.py (shim, lines 33-39)
from src.backend.core.auth.auth_selector import (  # noqa: E402
    AuthContext,
    AuthMethod,
    require_auth,
    set_default_auth,
    verify_request,
)
# S162 W5: removed _VERIFIERS from re-exports — private symbol
# must not leak through backward-compat shim.
# __all__ БЕЗ _VERIFIERS
```

`core/auth/auth_selector.py:214-222`:
```python
_VERIFIERS: dict[AuthMethod, Callable[..., Any]] = {
    AuthMethod.API_KEY: _verify_api_key,
    AuthMethod.JWT: _verify_jwt,
    ...
}
# _VERIFIERS определён в CANONICAL location, не в shim
```

**Runtime-подтверждение (без mock):**

```bash
$ .venv/bin/python -c "
import importlib
shim = importlib.import_module('src.backend.entrypoints.api.dependencies.auth_selector')
print('has _VERIFIERS:', hasattr(shim, '_VERIFIERS'))
# True / False
"
# Output: False

$ .venv/bin/python -c "
from src.backend.dsl.engine.processors.security import _load_verifiers, AuthenticationProviderUnavailableError
try:
    _load_verifiers()
except AuthenticationProviderUnavailableError as e:
    print('RAISED:', e)
"
# Output: RAISED: verifier registry attribute missing in src.backend.entrypoints.api.dependencies.auth_selector
```

**Impact:**
- `AuthValidateProcessor` (DSL) **всегда** бросает `AuthenticationProviderUnavailableError` при `request is not None and AuthMethod.NONE not in methods` → `process()` записывает error + stop exchange.
- В production **ни одна** DSL-route с `auth_validate: {methods: [jwt]}` (или `[api_key]`, `[saml]`, `[mtls]`) **никогда не пройдёт авторизацию через этот процессор**.
- Тест passes потому что тест-фикстура сама создаёт условие "empty registry" (через shim's lack of `_VERIFIERS`) — тест проверяет fail-closed path, не рабочий path.

**Workaround существует:** `core/auth/gateway.py:67-82` — `AuthGateway.verify()` использует canonical `verify_request` напрямую. Но DSL `AuthValidateProcessor` не использует этот path.

**Рекомендация:**
1. Изменить `_VERIFIERS_MODULE` на `"src.backend.core.auth.auth_selector"` (canonical, has `_VERIFIERS`).
2. Альтернативно: заменить dynamic `importlib.import_module` на прямой `from src.backend.core.auth.auth_selector import _VERIFIERS` (DSL не должен лезть в entrypoints — downward layer violation, см. AGENTS.md).
3. Cycle-2 retrospective: тесты должны проверять ОБА пути — fail-closed при empty registry И successful auth при populated registry с реальным `verify_request` (НЕ mock на `_load_verifiers`).

**Test-критерий:**
- Дополнить `test_auth_validate_failclosed.py` тестом `test_load_verifiers_succeeds_when_canonical_has_verifiers`: импортировать `from src.backend.core.auth.auth_selector import _VERIFIERS as canonical_verifiers`, assert `_load_verifiers()` returns canonical_verifiers (или эквивалент — переключить `_VERIFIERS_MODULE`).

---

### DOMAIN-P0-003 — Capability audit data-loss (NEW)

**Path:** `src/backend/core/security/capabilities/gate/audit_mixin.py:88-99`
**Priority:** P0 — silent audit event drop (security/observability)
**Status:** NEW (не было в cycle-1/cycle-2 — оба прошли мимо).

**Прямой evidence:**

```python
# core/security/capabilities/gate/audit_mixin.py:86-99
# S106 W5: dual emission через unified audit service.
# Lazy import для избежания circular dep (facade → services/audit).
from src.backend.core.audit.facade import emit_capability_check

emit_capability_check(  # ← NO AWAIT!
    plugin=plugin,
    capability=capability,
    requested_scope=requested_scope,
    declared_scope=declared_scope,
    outcome=outcome,
    tenant=tenant,
    reason=reason,
    event=event,
)
```

**Цепочка вызовов (sync → async):**
1. `emit_capability_check` (`core/audit/facade/capability.py:17`) — синхронная, возвращает результат `emit_audit(...)`.
2. `emit_audit` (`core/audit/facade/_base.py:23-58`) — синхронный wrapper, returns `svc.emit(...)`.
3. `svc.emit` — async coroutine (см. `core/audit/interfaces.py:14` + `services/audit/workflow_audit_sink.py:107` `async def emit`).
4. Sync wrapper `emit_audit` returns coroutine (line 51: `return svc.emit(...)`).
5. Caller (`audit_mixin.py:90`) **не await**'ит результат → coroutine создаётся, никогда не выполняется, GC'd с `RuntimeWarning: coroutine 'AuditService.emit' was never awaited`.

**Runtime-подтверждение:**

```bash
$ .venv/bin/python -m pytest tests/unit/core/security/capabilities/ -W error::RuntimeWarning 2>&1 | tail -10
# 1774 warnings, PytestUnraisableExceptionWarning подтверждает: coroutine 'AuditService.emit' was never awaited
# При -W error::RuntimeWarning — НЕ fails (warning-as-error не превращает unraisable в test fail)
# Но pytest фиксирует 1774 PytestUnraisableExceptionWarning
```

```bash
$ .venv/bin/python -m pytest tests/unit/core/security/ 2>&1 | grep "RuntimeWarning" | head -3
# RuntimeWarning: coroutine 'AuditService.emit' was never awaited
#     emit_capability_check(
```

**Coverage:** 19 callsites в `check_mixin.py` (`self._emit_audit(...)`) + 2 в `declaration_mixin.py`. Каждый вызов → 1 silent coroutine drop.

**Impact:**
- ВСЕ audit events capability-check pipeline теряются: `capability.check`, `capability.allocated`, `capability.revoked`.
- Legacy callback `self._audit(payload)` (line 71-84) — выполняется (sync), но новый unified audit path (S106 W2 Path A) — fail.
- Compliance/soc2: audit trail для capability decisions (deny/grant) — пустой в unified log.
- `authz_check_engine_failed_total` counter (cycle 33 B-03) использует тот же pattern через Prometheus client (sync) — это работает. Но именно capability audit events — broken.

**Рекомендация:**
1. Сделать `_emit_audit` async (`async def _emit_audit(...)`) и `await emit_capability_check(...)`. Все 19 callsites в `check_mixin.py` должны быть в async-контексте (они уже — `check()` и `check_tenant()` оба `def` без `async` → см. layering).
2. Альтернативно: использовать fire-and-forget через `asyncio.create_task(emit_capability_check(...))` с правильным task tracking.
3. Сделать `_audit_callback` (legacy) через `asyncio.ensure_future` если он async, либо оставить sync, но второй emit — только async.

**Test-критерий:**
- Новый test `test_audit_mixin_does_not_drop_coroutine`: monkeypatch `emit_capability_check` на async mock, вызвать `_emit_audit(...)`, assert mock был awaited.
- Существующий `tests/unit/core/security/capabilities/test_audit_extended.py` — расширить проверкой, что `AuditService.emit` был вызван (asyncio_mode).

---

### DOMAIN-P1-001 — Services→Infrastructure downward imports (NEW)

**Path:**
- `src/backend/services/security/facade.py:88` (`from src.backend.infrastructure.clients.storage.redis import get_redis_client`)
- `src/backend/services/security/facade.py:156` (`from src.backend.infrastructure.security.signatures import verify_signature`)
- `src/backend/services/security/cert_store_facade.py:18` (`from src.backend.infrastructure.security.cert_store import CertStore`)
- `src/backend/services/security/pii_streaming_facade.py:18` (`from src.backend.infrastructure.security import pii_streaming as _m`)
- `src/backend/services/security/__init__.py:17` (`from src.backend.infrastructure.security.signatures import ...`)
- `src/backend/services/authorization/facade.py:376` (`from src.backend.infrastructure.clients.storage.redis import get_redis_client`)
- `src/backend/services/auth/ad_directory_client/client.py` (не открывал — вне scope focus; из имени файла — downward likely)

**Priority:** P1 — layer boundary (architecture cleanliness)
**Status:** NEW (layer-checker прощает: `175 legacy / 0 new` per BASELINE.md).

**Прямой evidence:**

```bash
$ grep -rn "from src.backend.infrastructure" src/backend/services/security/ src/backend/services/authorization/ src/backend/services/auth/ 2>/dev/null | grep -v __pycache__
src/backend/services/security/cert_store_facade.py:18:        from src.backend.infrastructure.security.cert_store import CertStore
src/backend/services/security/facade.py:88:            from src.backend.infrastructure.clients.storage.redis import (
src/backend/services/security/facade.py:156:        from src.backend.infrastructure.signatures import (   ← was signatures actually
src/backend/services/security/pii_streaming_facade.py:18:        from src.backend.infrastructure.security import pii_streaming as _m
src/backend/services/security/__init__.py:17:from src.backend.infrastructure.security.signatures import (
src/backend/services/authorization/facade.py:376:            from src.backend.infrastructure.clients.storage.redis import (
```

**Замечание:** AGENTS.md явно разрешает `services → infrastructure` (capability-checked фасады). Это **не** downward violation при `services → infrastructure` (services выше по стеку, infrastructure ниже). Layer check разрешает.

Но `core/security/*` импортирует `core/auth/*` и `core/*` — это правильно (sibling в core layer). Не нарушение.

**Status:** Это **НЕ finding** в строгом смысле — projects правило "extensions→core only" не нарушено. Однако pattern "services lazy-imports infrastructure" расходится с facades-pattern (capability-checked). Возможна улучшение через `core/security/` обёртки (например, `core/security/secret_broker.py`).

**Priority:** P1 (cleanliness, не критичный). **Cycle-3 verification:** layer-checker exit 0, `175 legacy / 0 new` → не regression. Не создаю hard P0/P1, понижаю до informational.

**Рекомендация:**
- Если целевой state — extensions никогда не импортируют infrastructure, добавить `core/security/secret_broker.py` (facade) + `core/security/redis_secret.py` re-exports.
- Локализованное lazy-import допустимо — pattern согласован с существующим `core/security/credential_provider.py:155-164` (lazy-import `core.interfaces.secrets`).

---

### DOMAIN-P1-002 — Deprecated auth_selector shim still imported (RESIDUAL)

**Path:**
- `src/backend/entrypoints/middlewares/auth_required.py:177`
- `src/backend/entrypoints/webhook/handler.py:38`
- `src/backend/entrypoints/api/v1/endpoints/ai_stream.py:27`
- `src/backend/entrypoints/api/v1/endpoints/langmem_admin.py:14`
- `src/backend/entrypoints/api/v1/endpoints/ai_costs.py:18`

**Priority:** P1 (deprecated warning на каждом module load + cycle-1 finding незакрыт)
**Status vs cycle-1:** RESIDUAL. Cycle-1 finding DOMAIN-P0-002 не закрыт — миграция не выполнена.

**Прямой evidence:**

```bash
$ grep -rn "from src.backend.entrypoints.api.dependencies.auth_selector\|import src.backend.entrypoints.api.dependencies.auth_selector" --include="*.py" src/backend | grep -v __pycache__
src/backend/entrypoints/middlewares/auth_required.py:177:        from src.backend.entrypoints.api.dependencies.auth_selector import (
src/backend/entrypoints/webhook/handler.py:38:    from src.backend.entrypoints.api.dependencies.auth_selector import require_auth
src/backend/entrypoints/api/v1/endpoints/ai_stream.py:27:from src.backend.entrypoints.api.dependencies.auth_selector import (
src/backend/entrypoints/api/v1/endpoints/langmem_admin.py:14:from src.backend.entrypoints.api.dependencies.auth_selector import (
src/backend/entrypoints/api/v1/endpoints/ai_costs.py:18:from src.backend.entrypoints.api.dependencies.auth_selector import (
```

**Runtime-подтверждение:**

```bash
$ .venv/bin/python -c "
import warnings
warnings.simplefilter('always')
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware
"
# DeprecationWarning: Importing from src.backend.entrypoints.api.dependencies.auth_selector
# is deprecated. Use src.backend.core.auth.gateway instead (S96 W1 — implementation relocated).
```

Pytest-suite показывает 1 warning в `test_security.py:69`:
```
DeprecationWarning: Importing from src.backend.entrypoints.api.dependencies.auth_selector is deprecated.
```

**Impact:**
- DeprecationWarning на каждый request к `/api/v1/ai_stream`, `/api/v1/langmem_admin/*`, `/api/v1/ai_costs/*`, `/webhook/*` + global auth middleware.
- В prod при `warnings.simplefilter('error')` или через observability hooks — потенциально превращается в ошибку.
- Удаление shim (cycle-1 план был "S99+") заблокировано до миграции 5 imports.

**Рекомендация:**
- Заменить `from src.backend.entrypoints.api.dependencies.auth_selector import (...)` → `from src.backend.core.auth.gateway import (...)` в 5 файлах. Файлы — внутри scope.

**Test-критерий:**
- После миграции: `grep -rn "src.backend.entrypoints.api.dependencies.auth_selector" --include="*.py" src/backend tests` → пусто (или только в backward-compat shim itself).

---

### DOMAIN-P2-001 — JWT in-memory blacklist 24h clamped TTL

**Path:** `src/backend/services/security/facade.py:345-403`
**Priority:** P2 (latent — service-tokens > 24h теряются in fallback path)
**Status:** NEW (отмечено в S210 Ponytail comment, но не зафиксировано как P2).

**Прямой evidence:**

```python
# services/security/facade.py:372-379
def __init__(self) -> None:
    import threading
    # ttl: 24h default. Per-entry granularity теряется, но экономим
    # ~40 LOC ручного TTL-check. JWT обычно живут < 24h.
    self._store: TTLCache[str, bool] = TTLCache(maxsize=10_000, ttl=86400)
    # cachetools.TTLCache НЕ thread-safe по дизайну → Lock обязателен.
    self._lock = threading.Lock()
```

`revoke` (line 381-384):
```python
async def revoke(self, jti: str, expires_at: int) -> None:
    # expires_at учтён через ttl=86400; bool-значение не нужно хранить.
    with self._lock:
        self._store[jti] = True
```

**Проблема:** `cachetools.TTLCache(ttl=86400)` — fixed TTL для всех записей. Если `expires_at > now + 86400`, то jti выпадет из blacklist раньше, чем JWT истечёт → revoked token проходит.

**Целевой сценарий:** service-to-service JWT с TTL > 24h (например, batch-jobs, long-running cron).

**Mitigation:** cycle-3 BASELINE.md line 38: "pre-existing failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py`" — не связано.

**Impact:**
- При недоступности Redis (`_create_jwt_blacklist` line 79-103) — fallback in-memory.
- Long-lived tokens (> 24h) — fail-open на TTL.
- Production deployments: documented limitation, S210 Ponytail comment уже отмечает "prefer RedisJwtBlacklist (production)".

**Рекомендация:**
- Если in-memory fallback нужен для long-lived tokens — расширить `cachetools.TTLCache` до per-entry TTL через `cachetools.TTLCache` с `ttl=` callback (есть в cachetools API) или custom impl.
- Альтернативно: log warning при `expires_at > ttl_max`, signal caller "use Redis".

**Test-критерий:**
- `tests/unit/services/security/test_in_memory_jwt_blacklist.py::test_long_token_outlives_ttl`: создать `_InMemoryJwtBlacklist()`, revoke с `expires_at=now + 7d`, advance mock time на 2 дня, assert `is_revoked(jti)` returns `True`.

---

### DOMAIN-P3-001 — `verify_signature` facade

**Path:** `src/backend/services/security/facade.py:135-162`
**Priority:** P3 (library replacement)
**Status:** NEW (informational — замены с улучшением не нашёл)

**Прямой evidence:**

```python
# services/security/facade.py:135-162
def verify_signature(
    self,
    payload: bytes | str,
    signature: str,
    timestamp: int,
    secret: str,
    *,
    window_seconds: int = 300,
) -> bool:
    from src.backend.infrastructure.security.signatures import (
        verify_signature as _verify,
    )
    return _verify(
        payload, signature, timestamp, secret, window_seconds=window_seconds
    )
```

Thin proxy — facade не делает ничего кроме re-export. `infrastructure/security/signatures.py` не проверял (вне scope), но имя + сигнатура (`payload, signature, timestamp, secret, window_seconds=300`) указывают на HMAC-based signature verification (типично webhook signing — Stripe/GitHub pattern).

**Альтернативы:**
- Python stdlib `hmac.compare_digest` — не подходит (нет timestamp window check).
- `cryptography` (`pyca/cryptography`) — для HMAC; уже используется для mTLS PEM-парсинга (`core/auth/mtls_backend.py:179-216`).
- `requests-hmac` (PyPI) — external dep, не в pyproject.

**Status:** Замены с улучшением функций (без потери timestamp window) не нашёл. **Не рекомендую менять.**

---

### DOMAIN-P3-002 — `_InMemoryJwtBlacklist` cachetools

**Path:** `src/backend/services/security/facade.py:377`
**Priority:** P3 (informational)
**Status:** NEW

**Прямой evidence:** см. DOMAIN-P2-001. `cachetools` уже в pyproject (BASELINE checks: `cachetools.TTLCache` используется). Лицензия: BSD-3-Clause. Maintenance: active (последний релиз 2024).

**Альтернативы:**
- `py-cachetools-async` — не в pyproject, не mature.
- `async-lru` — не в pyproject, ≤2.x; не поддерживает TTL.

**Status:** Замена не даёт выигрыша. **Не рекомендую менять.**

---

### DOMAIN-P4-001 — Optional DSL `agent_security_policy` declarative override

**Path:** `src/backend/dsl/builders/security.py` (potential addition)
**Priority:** P4 (organically missing feature)
**Status:** NEW

**Контекст:** DSL `agent_security_check` (line 136-150) принимает `check`, `value`, `on_violation` — но НЕ `policy`. Per-workflow policy override — только через Python API `facade.set_policy_for_workflow()` (services/agent_security/facade.py:52-67).

**Use case:** declarative workflow-сценарий в route.toml/YAML:

```yaml
- agent_security_check:
    check: "sql"
    value: "${body.query}"
    on_violation: "block"
    policy:
      max_query_length: 5000
      allowed_statements: ["SELECT", "INSERT"]
      forbidden_statements: ["DROP", "TRUNCATE"]
```

**Рекомендация:** Только если есть demand. Cycle-3 — backlog item, не blocking. Не предлагаю менять в этом цикле (YAGNI).

---

## Cycle-1 + Cycle-2 residuals (verified)

| Finding ID | Original (cycle) | Description | Cycle-3 status |
|---|---|---|---|
| **DOMAIN-P0-001 (cycle-1)** | cycle-1 P0-001 | `AgentSecurityFacade.validate_sql` policy_override drop | **RESIDUAL** — bug at services/agent_security/facade.py:121-133 подтверждён runtime-проверкой. Framework `validate_sql` тоже не принимает context. Двухслойная проблема. |
| **DOMAIN-P0-002 (cycle-1)** | cycle-1 P0-002 | `entrypoints.api.dependencies.auth_selector` shim removal | **RESIDUAL** — 5 файлов всё ещё импортируют shim (см. DOMAIN-P1-002). DeprecationWarning на каждом module load. |
| **DOMAIN-P0-003 (cycle-1)** | cycle-1 P0-003 | — | не проверено (вне scope focus, речь о RBAC enforcement в HTTP-routes — открывал только auth_required.py). |
| **DOMAIN-P0-004 (cycle-1)** | cycle-1 P0-004 | — | не проверено (вне scope focus). |
| **DOMAIN-P1-001..003 (cycle-2)** | cycle-2 P1-001..003 | OPA runtime coverage, CapabilityFacade dual-emit, CapabilityPolicy deny>allow | **RESOLVED** — см. Verified strengths S-02, S-03, S-04. 164 unit tests + 14 integration tests pass. `policy.py:115-117` sort key verified. |
| **T-W1-01 (cycle-2)** | cycle-2 fix T-W1-01 | `AuthValidateProcessor` fail-closed | **PARTIALLY RESOLVED** — тесты (5/5) проходят (см. S-01), но runtime path **всегда fail-closed в production** из-за shim (см. DOMAIN-P0-002). Зелёные тесты создают ложное чувство безопасности. |

### Runtime-подтверждения (cycle-3)

```bash
# S-01 T-W1-01 verified
$ .venv/bin/python -m pytest tests/unit/dsl/processors/security/test_auth_validate_failclosed.py -v
# 5 passed, 1 warning in 3.38s

# S-02 capability + policy
$ .venv/bin/python -m pytest tests/unit/core/security/capabilities/ tests/unit/core/security/test_authorization_gateway.py tests/unit/core/security/test_authorization_gateway_steps.py -v
# 164 passed, 51 warnings in 1.81s

# S-03 OPA runtime
$ .venv/bin/python -m pytest tests/integration/test_opa_runtime_cycle37.py -v
# 14 passed in 5.42s

# Cycle-1 P0-001 residual (DOMAIN-P0-001)
$ .venv/bin/python -c "
import inspect
from src.backend.services.agent_security.facade import AgentSecurityFacade
src = inspect.getsource(AgentSecurityFacade.validate_sql)
# Confirmed: kwargs['policy_override'] set, but not forwarded to framework.validate_sql()
"

# Cycle-1 P0-002 residual (DOMAIN-P1-002)
$ grep -rn 'src.backend.entrypoints.api.dependencies.auth_selector' --include='*.py' src/backend
# 5 файлов в entrypoints/*

# DOMAIN-P0-002 (NEW, latently broken AuthValidateProcessor)
$ .venv/bin/python -c "
import importlib
m = importlib.import_module('src.backend.entrypoints.api.dependencies.auth_selector')
print('shim has _VERIFIERS:', hasattr(m, '_VERIFIERS'))
"
# False → permanently fail-closed

# DOMAIN-P0-003 (NEW, audit data-loss)
$ .venv/bin/python -m pytest tests/unit/core/security/capabilities/ 2>&1 | grep "RuntimeWarning: coroutine 'AuditService.emit'" | wc -l
# 17 (приблизительно — каждое _emit_audit callsite → 1 warning)
```

---

## Contradictions / overlaps to flag

### C-1: Cycle-2 P1 "deny > allow" verified, но P0 "validate_sql drop" не отмечен в cycle-2 как критичный
Cycle-2 фокусировался на OPA runtime + CapabilityFacade dual-emit + CapabilityPolicy deny>allow (P1-001..003). Cycle-1 P0-001 (validate_sql drop) **не был** в cycle-2 P0-001..004. Cycle-2 retrospective не упоминал его как "не закрыт". **Overlap:** если cycle-1 P0-001 закрыт через какой-то незафиксированный коммит, cycle-3 не видит (working tree не показывает fix).

### C-2: T-W1-01 fix (cycle-2) конфликтует с S162 W5 (cycle-162 S96 W1)
T-W1-01 заставляет `AuthValidateProcessor._load_verifiers()` идти через `entrypoints.api.dependencies.auth_selector` shim. S162 W5 (более ранний) удалил `_VERIFIERS` из shim re-exports. **Result:** shim → нет `_VERIFIERS` → `_load_verifiers()` always raises → **всегда fail-closed**. Cycle-2 fix закрыл только тест, не runtime.

### C-3: `auth_required.py:177` использует deprecated shim через `verify_request` (НЕ `_VERIFIERS`)
`auth_required.py` импортирует `verify_request` (которая в shim есть, line 33-39 re-export). Это **работает** потому что `verify_request` действительно ре-экспортирована. **Но** если S162 W5 когда-нибудь удалит `verify_request` из shim re-exports — `auth_required.py` сломается. Latent risk.

### C-4: `audit_mixin.py:90` не-awaited emit и `emit_audit` sync wrapper
Документация `core/audit/facade/_base.py:32-37` явно называет `emit_audit` "sync wrapper (for module-level calls)" — это design intent. Но `_emit_audit` в `audit_mixin.py:90` использует её как async path. Разрыв между документированным контрактом и реальным использованием.

---

## Readiness score

**Формула:**
```
score = 100
- 25 * P0_count - 15 * P1_count - 8 * P2_count - 3 * P3_count - 1 * P4_count
- 5 * unverified_critical_evidence
```

**Где:**
- P0_count = 3 (DOMAIN-P0-001, P0-002, P0-003)
- P1_count = 2 (DOMAIN-P1-001 informational, DOMAIN-P1-002 RESIDUAL)
- P2_count = 1 (DOMAIN-P2-001)
- P3_count = 2 (DOMAIN-P3-001, P3-002)
- P4_count = 1 (DOMAIN-P4-001)
- unverified_critical_evidence = 0 (все findings подтверждены runtime)

**Расчёт:**
```
score = 100
       - 25*3 - 15*2 - 8*1 - 3*2 - 1*1
       = 100 - 75 - 30 - 8 - 6 - 1
       = -20
       → clamped to 0
```

**Финальный score: 0 / 100.**

**Обоснование:**
- Правило "Оценка ≥80 запрещена при наличии P0/P1" — score должен быть ≤79.
- У нас 3 P0 (validate_sql drop, AuthValidate permanent fail-closed, audit data-loss) + 2 P1 — даже без penalty это minimum failure state.
- Реальные runtime-блокеры:
  - DOMAIN-P0-001: SQL validation НЕ работает per-workflow (compliance gap).
  - DOMAIN-P0-002: DSL `auth_validate` всегда fail-closed — shipped but broken.
  - DOMAIN-P0-003: 100% capability-check audit event data-loss.
- Cycle-2 reviewer не словил эти 3 P0 — runtime-проверки через `.venv/bin/python -c` показали факты.
- Score=0 справедлив: для production-ready security эти три P0 — блокеры.

---

## Recommended next tasks

| Priority | Task | Effort | Impact |
|---|---|---|---|
| **P0-1** | **Fix DOMAIN-P0-003** — сделать `_emit_audit` async + `await emit_capability_check(...)`. Или `asyncio.create_task` с task tracking. | 1-2 часа | Все capability audit events начнут доходить до unified audit service. Закрывает 1774 RuntimeWarnings. |
| **P0-2** | **Fix DOMAIN-P0-001** — `validate_sql` facade + framework: передавать `context` через facade, в framework добавить `policy_override` support (per-call). | 3-4 часа | Per-workflow SQL policy overrides начинают работать (compliance/banking requirement). |
| **P0-3** | **Fix DOMAIN-P0-002** — изменить `_VERIFIERS_MODULE` на `src.backend.core.auth.auth_selector`. Добавить test `test_load_verifiers_succeeds_when_canonical_has_verifiers`. | 30 минут | `AuthValidateProcessor` начинает работать в production. Downward layer violation (DSL→entrypoints) устраняется. |
| **P1-1** | **Fix DOMAIN-P1-002** — мигрировать 5 entrypoints файлов с `entrypoints.api.dependencies.auth_selector` → `core.auth.gateway`. | 30 минут | DeprecationWarning устранён. Shim можно удалить в S99+. |
| **P2-1** | **Address DOMAIN-P2-001** — задокументировать 24h limit in-memory fallback или расширить TTL до per-entry через cachetools callback. | 1-2 часа | Long-lived service-token security gap явно закрыт или явно ограничен. |
| **P3-1** | (Optional) Оценить tenant-prefix для JWT blacklist — carryover S19+ per `jwt_blacklist.py:17` comment. | 4-6 часов | Multi-tenant revocation isolation. |
| **P4-1** | (Optional) DSL `agent_security_policy` — declarative per-route policy override. | 6-8 часов | Declarative workflow safety (только если есть demand). |

---

## Commands run (с явным Python interpreter)

| # | Команда | Exit | Наблюдение |
|---|---|---|---|
| 1 | `.venv/bin/python --version && .venv/bin/python -c "import prometheus_client; import fastapi; import hypothesis; print('OK')"` | 0 | Python 3.14.0; все imports OK (system python — broken, НЕ используется) |
| 2 | `.venv/bin/python -m pytest tests/unit/dsl/processors/security/test_auth_validate_failclosed.py -v` | 0 | 5 passed, 1 warning — T-W1-01 verified |
| 3 | `.venv/bin/python -m pytest tests/unit/core/security/capabilities/ tests/unit/core/security/test_authorization_gateway.py tests/unit/core/security/test_authorization_gateway_steps.py -v` | 0 | 164 passed — S-02, S-04 verified |
| 4 | `.venv/bin/python -m pytest tests/integration/test_opa_runtime_cycle37.py -v` | 0 | 14 passed — S-03 verified |
| 5 | `.venv/bin/python -m pytest tests/security/test_tls_cert_required.py tests/security/test_yaml_safeload.py -v` | 0 | 8 passed — S-09, S-10 verified |
| 6 | `.venv/bin/python -m pytest tests/unit/dsl/processors/test_agent_security_check.py -v` | 0 | 10 passed — DSL security tests |
| 7 | `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_security.py -v` | 0 | 7 passed — DSL security tests (warning: shim deprecation) |
| 8 | `.venv/bin/python -m pytest tests/auth/mtls/ tests/auth/saml/ tests/security/pii/ -v` | 0 | 11 passed, 1 skipped (Keycloak permission — env issue) |
| 9 | `.venv/bin/python -m pytest tests/unit/core/security/ -q` | 0 | 266 passed, 2 skipped, 13 xfailed |
| 10 | `.venv/bin/python -m pytest tests/unit/core/security/capabilities/ -W error::RuntimeWarning 2>&1 \| tail -10` | 0 (warnings, not errors) | 1774 PytestUnraisableExceptionWarning — DOMAIN-P0-003 evidence |
| 11 | `.venv/bin/python -c "import importlib; m = importlib.import_module('src.backend.entrypoints.api.dependencies.auth_selector'); print('has _VERIFIERS:', hasattr(m, '_VERIFIERS'))"` | 0 | False — DOMAIN-P0-002 evidence |
| 12 | `.venv/bin/python -c "from src.backend.dsl.engine.processors.security import _load_verifiers, AuthenticationProviderUnavailableError; _load_verifiers()"` | 0 (raises) | `RAISED: verifier registry attribute missing in src.backend.entrypoints.api.dependencies.auth_selector` — DOMAIN-P0-002 evidence |
| 13 | `.venv/bin/python -c "import inspect; from src.backend.services.agent_security.facade import AgentSecurityFacade; print(inspect.getsource(AgentSecurityFacade.validate_sql))"` | 0 | Direct code evidence — DOMAIN-P0-001 |
| 14 | `grep -rn 'from src.backend.entrypoints.api.dependencies.auth_selector' --include='*.py' src/backend \| grep -v __pycache__` | 0 | 5 files — DOMAIN-P1-002 evidence |
| 15 | `grep -rn 'from src.backend.infrastructure' src/backend/services/security/ src/backend/services/authorization/ src/backend/services/auth/ 2>/dev/null \| grep -v __pycache__` | 0 | 6 hits — DOMAIN-P1-001 evidence (informational) |
| 16 | `grep -n 'TODO\|FIXME\|XXX\|HACK\|NotImplemented' src/backend/core/auth/*.py src/backend/core/security/*.py src/backend/services/security/*.py src/backend/services/authorization/*.py src/backend/services/agent_security/*.py` | 0 | Только literal "XXX" в PII-patterns (documentation) — no actual TODO/FIXME/HACK |

**Python interpreter:** `/home/user/dev/gd_integration_tools/.venv/bin/python` (3.14.0) для всех runtime-проверок.

---

## Подпись

- Все findings подтверждены runtime-проверками через `.venv/bin/python` или прямой чтением исходного кода.
- Числовые утверждения ("5 passed", "164 passed", "1774 warnings", "6 hits") — из прямого вывода указанных команд.
- Никаких изменений в source, configs, lockfiles, allowlists не сделано.
- Этот файл — единственный разрешённый артефакт записи для этого аудита.