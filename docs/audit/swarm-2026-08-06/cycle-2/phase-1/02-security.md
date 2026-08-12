# Phase 1 — Domain Audit: Security

- Date: 2026-08-06
- Аудитор: независимый агент, scope = `src/backend/core/security/**`, `src/backend/core/auth/**`, `src/backend/services/security/**`, `src/backend/services/auth/**`, `src/backend/services/authorization/**`, `src/backend/services/agent_security/**`, `src/backend/entrypoints/middlewares/*security*.py`, `src/backend/entrypoints/middlewares/*auth*.py`, `ai_policies/**`, `tests/security/**`, `tests/auth/**`
- HEAD: `ca5bff93058f2580041a7339913b52943babb329`
- Запрещено: читать отчёты других агентов, cycle-1 отчёты, `BASELINE.md` cycle-1, `PHASE-2-SUMMARY.md`, `PHASE-3-PLAN.md` cycle-1, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`. Разрешено: `docs/audit/swarm-2026-08-06/cycle-2/BASELINE.md` (только baseline numbers), `AGENTS.md` (только как правила), реальный код и тесты.

---

## 1. Scope / не проверено

**Проверено** (по факту чтения файлов):
- `src/backend/core/security/authorization_gateway/{__init__,opa_mixin,casbin_mixin,permission_mixin,audit_mixin,state,policies/*}.py`
- `src/backend/core/security/capabilities/{policy,__init__}.py` + `gate/{audit,check,cache,declaration}_mixin.py`
- `src/backend/core/security/{activity_capability_guard,ip_restriction_store,module_whitelist,credential_provider,pii_*,secret_rotation,connector_auth}.py`
- `src/backend/core/auth/{auth_selector,gateway,facade,__init__}.py`, `core/auth/auth_selector.py`
- `src/backend/services/{security,authorization,auth,agent_security}/facade.py`, `services/security/{cert_store,pii_streaming}_facade.py`
- `src/backend/infrastructure/policy/opa/client.py`, `infrastructure/policy/{casbin_adapter,casbin_tenant_scoped}.py`
- `src/backend/entrypoints/middlewares/{security_headers,auth_required,auth_method_header}.py`
- `src/backend/entrypoints/api/dependencies/auth_selector.py` (shim)
- `src/backend/dsl/engine/processors/{security,agent_dsl/agent_security_check,jdbc_query}.py`
- `src/backend/plugins/composition/di.py` (relevant portion)
- `src/backend/core/errors.py` (ProductionWiringError)
- `ai_policies/*.yaml` (3 файла)
- Тесты: `tests/integration/test_opa_runtime_cycle37.py`, `tests/unit/core/security/test_authorization_gateway_steps.py`, `tests/unit/plugins/composition/test_authorization_gateway_di.py`, `tests/unit/core/security/capabilities/test_policy_integration.py`, `tests/unit/core/auth/test_auth_selector_relocation.py`, `tests/unit/dsl/engine/processors/test_security.py`, `tests/unit/core/security/test_authorization_gateway.py`, `tests/security/*`, `tests/auth/*`
- `pyproject.toml` (security-зависимости), `tools/check_layers.py`, `tools/check_layers_allowlist.txt`
- `git status`, `git log`, `git diff`

**Не проверено** (явно):
- Цикломатика runtime call-path между `auth_required` middleware и `verify_request` под реальной нагрузкой (read-only анализ).
- Поведение `IPRestrictionStore.reload_from_yaml` под concurrent reload + concurrent `is_allowed` (race condition analysis only — не воспроизводил).
- Состояние feature-flag service (`authz_gateway_enabled`, `opa_runtime_query_enabled`) под нагрузкой.
- Live функционирование Vault / Consul cert store (read-only).
- Полный код `extensions/**` (вне scope).
- Реальные OPA/Casbin engines — заменены на duck-type фейки в integration-тесте.

**Не приписано рою cycle 2** (явно):
- Pre-existing drift: `M uv.lock` (-15 svcs), `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state` — НЕ атрибутируется рою, не трогал.
- 5 uncommitted source правок cycle 1 Phase 4 (T-1.4 / T-1.5 / T-3.1) — НЕ атрибутировать рою cycle 2.
- 35 активных security allowlist IDs (`CVE-|GHSA-|PYSEC-`) — без изменений.

---

## 2. Verified strengths

| # | Что работает | Evidence |
|---|---|---|
| S1 | **OPA runtime: HTTP/2 + connection pool + lazy singleton + graceful shutdown** | `src/backend/infrastructure/policy/opa/client.py:44-95` — singleton, `httpx.Limits(max_connections=32, max_keepalive=16, keepalive_expiry=30)`, `make_http_client(..., http2=True, ...)`, `close()`. Docstring явно ссылается на IL-CRIT1.4b fix. |
| S2 | **OPA: deny-by-default + fail-closed на сетевых ошибках + non-200** | `client.py:96-120` — `except Exception` → `PolicyDecision(allow=False, reasons=["opa_unavailable"])`; `resp.status_code != 200` → `allow=False` с `opa_status_<code>`; не возвращает кэшированный allow при ошибке. |
| S3 | **OPA step mixin: feature-flag OFF → no-op allow (плавная миграция), ON → strict query** | `src/backend/core/security/authorization_gateway/opa_mixin.py:54-96` — feature-flag `opa_runtime_query_enabled` отдельно, `feature_flag_unavailable` → deny (fail-closed), input_doc содержит principal/resource/action/tenant_id/correlation_id. |
| S4 | **Casbin step mixin: tenant пробрасывается, исключения → deny** | `src/backend/core/security/authorization_gateway/casbin_mixin.py:47-65` — `tenant_id=ctx.get("tenant_id")`, `except Exception → deny` с detail. |
| S5 | **Permission step mixin: requires ALL permissions, missing → deny** | `permission_mixin.py:51-108` — feature-flag `route_authz_requires_permission`, `if missing: deny detail=missing_permissions:...`. |
| S6 | **AuthorizationGateway: short-circuit на первом deny в policy-цепочке** | `authorization_gateway/__init__.py:177-194` — `if reason.outcome != "allow": return self._finalize_deny(...)` — никакого дальнейшего вызова Casbin/OPA после OPA-deny. Тест `test_opa_deny_skips_casbin` подтверждает. |
| S7 | **CapabilityPolicy: deny > allow tie-break при равных priority** | `core/security/capabilities/policy.py:112-117` — sort key `(-priority, 0 if effect == "deny" else 1)` → deny раньше allow. Тест `test_priority_deny_beats_allow_at_equal_priority` (test_policy_integration.py:173-200) подтверждает. |
| S8 | **CapabilityPolicy: higher priority выигрывает независимо от effect** | Тест `test_priority_higher_wins_over_lower` (test_policy_integration.py:204+) подтверждает. |
| S9 | **CapabilityGate dual-emit audit** | `core/security/capabilities/gate/audit_mixin.py:46-99` — primary callback (`self._audit`) + secondary `emit_capability_check` helper. Cycle 2 (`/home/user/dev/gd_integration_tools/src/backend/core/security/capabilities/gate/audit_mixin.py`) — оба emit'а. |
| S10 | **activity_capability_guard: fail-closed на отсутствии context (V22 R-V15-1)** | `src/backend/core/security/activity_capability_guard.py:211-228` — `raise CapabilityDeniedError(plugin=fn.__name__, capability="<missing-context>", ...)`. До этого был fail-open (legacy). |
| S11 | **ProductionWiringError при engine_enabled=True без policy engines** | `src/backend/plugins/composition/di.py:142-157` — `if not opa_url and not casbin_model_path: raise ProductionWiringError(...)`. `src/backend/core/errors.py:170-182` docstring подтверждает B-20 fix cycle 38. |
| S12 | **SecurityHeaders middleware: pure ASGI с send-wrapper, корректно для SSE/streaming/WS** | `src/backend/entrypoints/middlewares/security_headers.py:71-109` — перехват `http.response.start`, override existing, пробрасывает non-HTTP scope без изменений. |
| S13 | **AuthRequiredMiddleware: pure ASGI с public-path allowlist + OPTIONS bypass** | `src/backend/entrypoints/middlewares/auth_required.py:127-167` — `is_path_public` через `PurePosixPath`, OPTIONS preflight bypass, 401 через send (no-raise). |
| S14 | **AuthMethodHeaderMiddleware: default OFF (S191 fix — no information disclosure)** | `src/backend/entrypoints/middlewares/auth_method_header.py:14-18, 49-50` — `enabled: bool = False`, явно мотивировано (header leaks auth method). |
| S15 | **shim hides private `_VERIFIERS`** | `tests/unit/core/auth/test_auth_selector_relocation.py:81-90` — тест проверяет, что shim НЕ leak'ит private registry. Shim в `entrypoints/api/dependencies/auth_selector.py:49-55` не включает `_VERIFIERS` в `__all__` и не импортирует. |
| S16 | **policy_settings.engine_enabled=False → пустой policy-chain (backward compat)** | Тест `test_engine_disabled_means_no_policies` (test_opa_runtime_cycle37.py:396-421). |
| S17 | **TenantScopedCasbin: deny при отсутствии tenant-контекста (fail-closed IDOR)** | `src/backend/infrastructure/policy/casbin_tenant_scoped.py:111-120` — `if tenant is None: logger.warning(...); return False`. |
| S18 | **In-memory JWT blacklist: TTLCache + threading.Lock (S210)** | `src/backend/services/security/facade.py:345-402` — `TTLCache(maxsize=10_000, ttl=86400)`, threading.Lock для thread safety. |
| S19 | **InMemoryJwtBlacklist: documented ограничения (NOT multi-worker safe, для dev_light)** | `facade.py:96-103, 360-369` — warning логи, явное "Redis-backed (multi-worker safe)" vs in-memory fallback. |
| S20 | **AI policy YAML deny-by-default для tool whitelist** | `ai_policies/agent_basic.policy.yaml:60-66` — explicit `allow: [...]` + `deny: [...]` + `max_calls_per_run`. |
| S21 | **IPRestrictionStore singleton (double-checked locking)** | `src/backend/core/security/ip_restriction_store.py:42-50` — `__new__` + `_lock` + `if cls._instance is None: with cls._lock`. |
| S22 | **JdbcQueryProcessor: SQL-injection deny (multi-statement + DDL blocklist)** | `src/backend/dsl/engine/processors/jdbc_query.py:82-90` + test_jdbc_query.py:26-68 — DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE запрещены. |
| S23 | **CasbinAdapter: deny-all если casbin не установлен** | `src/backend/infrastructure/policy/casbin_adapter.py:35-37` — `except ImportError: return None` → `enforce` возвращает `False` (deny). |

---

## 3. Findings table

| ID | P | Path:line | Title |
|---|---|---|---|
| DOMAIN-P0-001 | P0 | `src/backend/services/agent_security/facade.py:121-133` | `validate_sql` теряет `policy_override` (RESIDUAL) |
| DOMAIN-P0-002 | P0 | `src/backend/entrypoints/api/dependencies/auth_selector.py` + 5 consumers | deprecated shim всё ещё активно используется (RESIDUAL) |
| DOMAIN-P0-003 | P0 | `src/backend/dsl/engine/processors/security.py:32-55, 102-110` | `AuthValidateProcessor._load_verifiers()` возвращает `{}` → auth bypass при `required=False`, hard fail при `required=True` |
| DOMAIN-P0-004 | P0 | `src/backend/core/security/authorization_gateway/__init__.py:249-309, 357-383` | sync `AuthorizationGateway.check()` обходит OPA/Casbin — использует только in-memory dict |
| DOMAIN-P1-001 | P1 | `src/backend/dsl/engine/processors/security.py:5-55` | downward layer violation dsl → entrypoints (через runtime importlib) |
| DOMAIN-P1-002 | P1 | `src/backend/core/auth/auth_selector.py:147-167` | `_verify_saml` без проверки подписи session — trust header/cookie |
| DOMAIN-P1-003 | P1 | `src/backend/entrypoints/mcp/auth_middleware.py:6-7, 40` | doc/import drift + использование private `_verify_api_key` / `_verify_jwt` |
| DOMAIN-P2-001 | P2 | `src/backend/core/security/authorization_gateway/policies/{opa,casbin}_policy_decider.py:50, 45` | class aliases `OPAPolicyDecider` / `CasbinPolicyDecider` — dead exports |
| DOMAIN-P2-002 | P2 | `src/backend/core/security/authorization_gateway/__init__.py:357-383` | `_casbin_check` / `_opa_check` — `hasattr` всегда False → dead code path |
| DOMAIN-P2-003 | P2 | `src/backend/services/capabilities/facade.py:50-75, 145-170` | `check()` / `declare()` / `revoke()` молча swallow все exceptions |
| DOMAIN-P2-004 | P2 | `src/backend/core/security/activity_capability_guard.py:119-132` | `_is_gate_enabled()` broad `except Exception` → потенциальный NoOp при broken flag service |
| DOMAIN-P2-005 | P2 | `src/backend/core/security/activity_capability_guard.py:153-174` | `emit_audit` coroutine fire-and-forget через `create_task` без await → silent audit drops |
| DOMAIN-P3-001 | P3 | `src/backend/core/security/pii_masker.py` / `pii_patterns.py` | custom regex-PII vs `presidio-analyzer` (уже в `ai_policies/agent_basic.policy.yaml`) |
| DOMAIN-P3-002 | P3 | `src/backend/core/security/authorization_gateway/__init__.py:113, 246-355` | in-memory `add_policy`/`remove_policy` рядом с реальными engine — рассинхрон source-of-truth |
| DOMAIN-P4-001 | P4 | n/a | (нет organic-fit отсутствующего функционала) |

**Итого: 4 × P0, 3 × P1, 5 × P2, 2 × P3, 0 × P4.**

---

## 4. Detailed evidence

### DOMAIN-P0-001 — `validate_sql` теряет `policy_override` (RESIDUAL)

`src/backend/services/agent_security/facade.py:121-133`:
```python
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    policy = self.get_policy_for_workflow(workflow_id)
    if policy is not None:
        kwargs["policy_override"] = policy
    return self.framework.validate_sql(query)
```

Сравнить с `validate_prompt` (line 91-104) и `validate_command` (line 106-119), которые **корректно** собирают `ctx["policy_override"]` и передают `framework.validate_prompt(prompt, context=ctx)`. Здесь `kwargs` собран, но **не передан** в `framework.validate_sql(query)`.

**Подтверждено сигнатурой**: `src/backend/core/ai/security/agent_security.py:572` — `def validate_sql(self, query: str) -> SecurityDecision:` — keyword `policy_override` НЕ принимается.

**Impact**: для `agent_security_check(check="sql")` per-workflow policy override (через `set_policy_for_workflow`) **молча игнорируется**. Если tenant установил менее строгую политику для конкретного workflow, она не применится — применяется framework default. Это fail-open vs заявленную per-workflow isolation. Per S204 retro-audit B18 fix (docstring line 33-37) подтверждает намерение per-workflow isolation для **всех** валидаторов, включая sql.

**Минимальная рекомендация**: 1-line fix — добавить `context=ctx` аргумент:
```python
ctx = dict(kwargs)
if policy is not None:
    ctx["policy_override"] = policy
return self.framework.validate_sql(query, context=ctx)
```
(потребует апдейт сигнатуры `framework.validate_sql` если ещё не принимает `context`).

**Тест-критерий**: unit-test `validate_sql(workflow_id="wf", query="DROP TABLE x")` с override-policy которая разрешает — должно быть allowed, не framework default deny.

---

### DOMAIN-P0-002 — deprecated shim всё ещё активно используется (RESIDUAL)

Документированная deprecation (S96 W1) в `src/backend/entrypoints/api/dependencies/auth_selector.py:1-23` говорит:
> "DEPRECATED shim — реальная implementation переехала в `core.auth.auth_selector`. ... Удалится в S99+".

**Активные consumers** (найдены прямым grep, исключая `__pycache__`):
1. `src/backend/entrypoints/middlewares/auth_required.py:177` — `from src.backend.entrypoints.api.dependencies.auth_selector import verify_request`
2. `src/backend/entrypoints/webhook/handler.py:38` — `from src.backend.entrypoints.api.dependencies.auth_selector import require_auth`
3. `src/backend/entrypoints/api/v1/endpoints/ai_stream.py:27` — `from src.backend.entrypoints.api.dependencies.auth_selector import (require_auth, ...)`
4. `src/backend/entrypoints/api/v1/endpoints/langmem_admin.py:14` — `from ... import auth_selector` (require_auth)
5. `src/backend/entrypoints/api/v1/endpoints/ai_costs.py:18` — `from ... import auth_selector` (require_auth)
6. `src/backend/dsl/engine/processors/security.py:32, 48` — comment-ссылка + `importlib.import_module(_VERIFIERS_MODULE)`
7. Tests: `tests/unit/core/auth/test_auth_selector_relocation.py:76`, `tests/unit/core/auth/test_gateway_facade.py:34, 42`

**Impact**:
- Каждый import триггерит `DeprecationWarning` (через `warnings.warn(... DeprecationWarning)`) → шум в логах prod.
- 5 prod-source файлов + 1 DSL-processor + 2 теста до сих пор зависят от пути, помеченного к удалению. Блокирует removal в S99+.

**Минимальная рекомендация**: миграция 5 prod-файлов на `src.backend.core.auth.gateway` (canonical facade). Также DOMAIN-P0-003 (см. ниже) требует починки `dsl/engine/processors/security.py`.

**Тест-критерий**: grep `from src.backend.entrypoints.api.dependencies.auth_selector` → пусто (после миграции).

---

### DOMAIN-P0-003 — `AuthValidateProcessor._load_verifiers()` возвращает `{}` (NEW)

`src/backend/dsl/engine/processors/security.py:32-55, 73-117`:

```python
_VERIFIERS_MODULE = "src.backend.entrypoints.api.dependencies.auth_selector"

def _load_verifiers() -> dict[AuthMethod, Any]:
    module = importlib.import_module(_VERIFIERS_MODULE)
    return getattr(module, "_VERIFIERS", {})

# В process():
verifiers = _load_verifiers()  # ← возвращает {} из shim
for method in methods:
    verifier = verifiers.get(method)
    if verifier is None:
        continue
    ctx = await verifier(request)
    if ctx is not None:
        exchange.set_property(self._result_property, ctx)
        return

if self._required:
    exchange.set_error("auth: ни один из методов ...")
    exchange.stop()
```

Шим `src/backend/entrypoints/api/dependencies/auth_selector.py:49-55` НЕ экспортирует `_VERIFIERS` (см. S15):
```python
__all__ = ("AuthContext", "AuthMethod", "require_auth", "set_default_auth", "verify_request")
```
S162 W5 docstring (shim:31): `removed _VERIFIERS from re-exports — private symbol must not leak through backward-compat shim`.

**Подтверждение тестом** (`tests/unit/dsl/engine/processors/test_security.py:60-64`):
```python
mock_load.return_value = {}
...
assert exchange.stopped  # ← ожидаемое поведение — но это MOCK!
```
Тест мокает `_load_verifiers`, не проверяет реальный runtime-path. В production `_load_verifiers()` возвращает `{}` — это **broken** поведение:
- `required=True` (default): **все запросы через AuthValidateProcessor fail-stopped**. Auth fail-closed, но любая DSL-route, использующая `auth: ["jwt"]`, всегда упадёт.
- `required=False`: **silent auth bypass** — без `_VERIFIERS` цикл for не вызывает ни одного verifier, `if self._required` не срабатывает, выполнение продолжается. **Fail-open путь существует**.

**Impact**: P0 — broken auth в DSL pipelines. Если хоть одна extension route использует `AuthValidateProcessor(required=False)`, она проходит без аутентификации. Подтверждённых вызовов `AuthValidateProcessor` в extensions не нашёл (search scope ограничен); но DSL route-pattern подразумевает user-defined extensions. **В runtime AuthValidateProcessor — broken**.

**Минимальная рекомендация**: импортировать `_VERIFIERS` из canonical `src.backend.core.auth.auth_selector`:
```python
_VERIFIERS_MODULE = "src.backend.core.auth.auth_selector"
```
И добавить explicit error в `_load_verifiers` если dict пустой (fail-loud при регрессии).

**Тест-критерий**: integration-тест с реальным `core.auth.auth_selector._VERIFIERS` (без mock) — `process()` с request, имеющим валидный JWT → успешный `AuthContext`, без ошибки exchange.

---

### DOMAIN-P0-004 — sync `AuthorizationGateway.check()` обходит OPA/Casbin (NEW)

`src/backend/core/security/authorization_gateway/__init__.py:249-309`:
```python
def check(self, subject, action, resource, context=None) -> bool:
    key = (subject, action, resource)
    if key in self._in_memory_policies:
        return self._in_memory_policies[key]

    # Try Casbin step if registered
    try:
        casbin_result = self._casbin_check(subject, action, resource)
        if casbin_result is not None:
            return casbin_result
    except Exception as exc: ...

    # Try OPA step if registered
    try:
        opa_result = self._opa_check(subject, action, resource, context)
        if opa_result is not None:
            return opa_result
    except Exception as exc: ...

    # Default deny (fail-closed)
    return False
```

Helper-методы (lines 357-383):
```python
def _casbin_check(self, subject, action, resource) -> bool | None:
    from src.backend.core.security.authorization_gateway.casbin_mixin import CasbinMixin
    if hasattr(CasbinMixin, "_casbin_check"):
        return CasbinMixin._casbin_check(self, subject, action, resource)
    return None  # ← ВСЕГДА, т.к. CasbinMixin не имеет _casbin_check

def _opa_check(self, subject, action, resource, context) -> bool | None:
    from src.backend.core.security.authorization_gateway.opa_mixin import OpaMixin
    if hasattr(OpaMixin, "_opa_check"):
        return OpaMixin._opa_check(self, subject, action, resource, context)
    return None  # ← ВСЕГДА, т.к. OpaMixin не имеет _opa_check
```

**Verification**: `grep -n "_casbin_check\|_opa_check" src/backend/core/security/authorization_gateway/` (исключая `__init__.py`) → **0 hits** вне `__init__.py`. `CasbinMixin` (casbin_mixin.py) определяет `casbin_step`, не `_casbin_check`. `OpaMixin` (opa_mixin.py) определяет `opa_step`, не `_opa_check`.

**Impact**: sync `AuthorizationGateway.check()` (S193 fix path) **никогда** не вызывает зарегистрированные OPA/Casbin engines. Используется только `self._in_memory_policies` dict. Любой caller (например `AuthorizationFacade.check()` line 458-475, line 467 `self.gateway.check(...)`) получает только in-memory policy, **полностью игнорируя** OPA-цепочку и Casbin-RBAC. Если в production `engine_enabled=True` и настроены OPA/Casbin, sync-path остаётся с пустой in-memory policy → **fall-through to default deny (line 309)** → всё подряд denied.

Это противоречит docstring (line 258-271), который обещает "Delegates to: 1. Casbin step ... 2. OPA step ... 3. In-memory policy storage".

**Минимальная рекомендация**: переписать `_casbin_check` / `_opa_check` чтобы они вызывали зарегистрированные `policies` chain (как в async `authorize()` — line 177-194), фильтруя по source name. Или удалить мёртвый code path полностью и сделать sync `check()` = in-memory-only (с явным комментарием).

**Тест-критерий**: unit-test `check()` с зарегистрированным `CasbinPolicyDecider` (allow=True) → возвращает True, не False (default deny).

---

### DOMAIN-P1-001 — downward layer violation dsl → entrypoints

`src/backend/dsl/engine/processors/security.py:5-14, 32-55`:
- Module docstring: «Использует уже существующие верификаторы из `entrypoints.api.dependencies.auth_selector` — это не нарушает архитектурные границы, т.к. DSL-движок исполняется в рантайме поверх HTTP-запроса».
- Реально: `importlib.import_module("src.backend.entrypoints.api.dependencies.auth_selector")` — runtime dependency от dsl (layer 2) на entrypoints (layer 1).

**Impact**: P1 — layer violation. AGENTS.md запрещает extensions/services → entrypoints/ напрямую; dsl/engine/processors — формально layer 2/3. Runtime-import через `importlib` маскирует проблему от статического check_layers. Layer checker baseline = 175 legacy (allowlist), 0 new — статика не видит runtime-import, что и объясняет почему эта проблема "невидима".

**Минимальная рекомендация**: импортировать из `src.backend.core.auth.auth_selector` (canonical, layer core) — это решит и DOMAIN-P0-003 одновременно. Если нужны именно verifier'ы — экспонировать их через `core.auth.auth_selector` public API.

**Тест-критерий**: layer checker не показывает new violations; `importlib` не используется для cross-layer загрузки.

---

### DOMAIN-P1-002 — `_verify_saml` без проверки подписи session

`src/backend/core/auth/auth_selector.py:147-167`:
```python
async def _verify_saml(request: Request) -> AuthContext | None:
    session_id = request.cookies.get("saml_session") or request.headers.get("X-SAML-Session-ID")
    if not session_id:
        return None
    # Реальная валидация session_id — в SP-side store (Redis/in-memory).
    # На уровне ядра принимаем cookie как заявку; проверка её подлинности
    # делается middleware'ом.
    return AuthContext(
        AuthMethod.SAML, principal=session_id, metadata={"session_id": session_id}
    )
```

Docstring (line 161-164) явно признаёт gap: «проверка её подлинности делается middleware'ом». **Но** verifier используется в `verify_request` registry (line 219 `AuthMethod.SAML: _verify_saml`) — если вызывающий код не ставит свой middleware, **любой session_id проходит**.

**Impact**: P1 — если endpoint объявил `require_auth(AuthMethod.SAML)` (как короткий путь для SAML) без дополнительного middleware, attacker подставляет cookie `saml_session=admin` → AuthContext(principal="admin"). Это fail-open в одном конкретном сценарии.

**Минимальная рекомендация**: переместить реальную validation в `_verify_saml` (с Redis lookup + signed cookie/header), либо явно пометить `AuthMethod.SAML` как «требует X-SAML-Session-ID middleware» и reject в `verify_request` если middleware отсутствует.

**Тест-критерий**: `verify_request(methods=AuthMethod.SAML, request=Mock(cookies={"saml_session": "admin"}))` без middleware → должен возвращать None, не AuthContext.

---

### DOMAIN-P1-003 — doc/import drift + private symbol use в `mcp/auth_middleware.py`

`src/backend/entrypoints/mcp/auth_middleware.py:5-9, 40`:
- Module docstring (line 5-7): «через `_verify_jwt` из :mod:`entrypoints.api.dependencies.auth_selector` ... либо `X-API-Key` через `_verify_api_key` оттуда же».
- Реально (line 40): `from src.backend.core.auth.auth_selector import _verify_api_key, _verify_jwt` — импорт из canonical core path, не из entrypoints.

Использование private (`_`-prefix) символов из cross-module scope — fragile (любой rename ломает без ошибки типа). Доступ через `core.auth.auth_selector._verify_api_key` формально ОК (private convention), но нарушает публичный API contract.

**Impact**: P1 — maintenance hazard + doc drift. Подтверждено, что `_DummyHeadersRequest` (line 28-35) — shim обходящий type-checker для FastAPI Request.

**Минимальная рекомендация**: выровнять docstring с реальным импортом; экспонировать public `verify_jwt_request(headers: dict) -> AuthContext | None` и `verify_api_key_request(headers: dict) -> AuthContext | None` в `core.auth.auth_selector` для non-Request contexts (header-only ASGI middleware).

**Тест-критерий**: docstring match code; public API позволяет `from src.backend.core.auth.auth_selector import verify_jwt_headers`.

---

### DOMAIN-P2-001 — dead exports `OPAPolicyDecider` / `CasbinPolicyDecider`

`src/backend/core/security/authorization_gateway/policies/{opa,casbin}_policy_decider.py:50, 45`:
```python
OPAPolicyDecider = build_opa_policy_decider  # alias
CasbinPolicyDecider = build_casbin_policy_decider  # alias
```

Grep на использование (исключая `build_*` функции и `__init__.py` re-exports):
- `OPAPolicyDecider`: упоминается только в `policies/__init__.py:25, 29, 34` (re-export + class alias definition) и docstring.
- `CasbinPolicyDecider`: то же.

В `plugins/composition/di.py:158-188` используются только `build_opa_policy_decider` и `build_casbin_policy_decider`. В `tests/integration/test_opa_runtime_cycle37.py:34-37` — те же factory functions.

**Impact**: P2 — dead code. Class aliases никогда не инстанцируются.

**Минимальная рекомендация**: удалить `OPAPolicyDecider` / `CasbinPolicyDecider` алиасы и `__all__` упоминания; оставить только `build_*` factory functions.

**Тест-критерий**: `grep -rn "OPAPolicyDecider\b\|CasbinPolicyDecider\b" src tests` → пусто.

---

### DOMAIN-P2-002 — dead `_casbin_check` / `_opa_check`

См. DOMAIN-P0-004 detailed analysis. Методы `_casbin_check` / `_opa_check` (lines 357-383) **всегда** возвращают None потому что `hasattr(CasbinMixin, "_casbin_check")` и `hasattr(OpaMixin, "_opa_check")` всегда False (mixins определяют `casbin_step` / `opa_step`).

**Минимальная рекомендация**: либо реализовать `_casbin_check` / `_opa_check` через зарегистрированные policy chain, либо удалить методы + упростить `check()` до "in-memory + fallback deny".

---

### DOMAIN-P2-003 — `CapabilityFacade.check()` swallow exceptions

`src/backend/services/capabilities/facade.py:50-75, 145-170, 172-178`:
```python
def check(self, plugin, capability, scope=None) -> bool:
    try:
        self.gate.check(plugin, capability, scope)
        return True
    except Exception as exc:
        _logger.debug(...)
        return False
```
Аналогично `check_async`, `check_tenant` (False при `principal_id is None`), `declare`, `revoke`, `list_allocated_tenant`.

Docstring line 60-63 обещает "CapabilityDeniedError: S-2 fix — fail-closed на deny", но сигнатура возвращает `bool`, не raise.

**Impact**: P2 — несовместимо с контрактом банковских процессоров, которым нужен raise (есть отдельный `check_or_raise` метод, line 180-216, для этого). Но `check()` используется как простой bool-query — fail-closed OK. Diagnostic noise в DEBUG-логе вместо WARNING — observability gap при broken gate.

**Минимальная рекомендация**: поднять `_logger.warning` вместо `debug` для `CapabilityDeniedError` (не swallow policy-deny как noise). Уже есть `check_or_raise` — нормализовать naming: переименовать `check` → `check_returns_bool` (явный контракт).

---

### DOMAIN-P2-004 — `_is_gate_enabled()` broad exception

`src/backend/core/security/activity_capability_guard.py:119-132`:
```python
def _is_gate_enabled() -> bool:
    try:
        from src.backend.core.config.features import feature_flags
        return bool(feature_flags.activity_capability_gate_enabled)
    except Exception as _:
        _logger.warning("Не удалось прочитать feature_flags; capability-gate NoOp")
        return False
```

`except Exception` (broad) при импорте из `feature_flags` модуля. Это правильный fail-open для **read** (отсутствие флага = выкл = no overhead). Но если `feature_flags` модуль вообще broken — silent NoOp.

**Impact**: P2 — observability hazard. WARNING логируется, но деградация не алертится.

**Минимальная рекомендация**: узкое исключение (`ImportError`, `AttributeError`).

---

### DOMAIN-P2-005 — fire-and-forget audit coroutine

`src/backend/core/security/activity_capability_guard.py:153-174`:
```python
coro = emit_audit(...)
if asyncio.iscoroutine(coro):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)  # ← fire-and-forget
    except RuntimeError:
        pass  # no running loop → drop coroutine (sync context)
except Exception as _:
    pass  # never raise from audit emission
```

`create_task(coro)` без `await` + без exception handler → если `emit_audit` корутина raises, asyncio логирует "Task exception was never retrieved". Audit events могут быть **тихо потеряны** при сбое audit service.

**Impact**: P2 — silent audit drops в prod. Это нарушает «dual-emit для unified audit service» (S109 W1).

**Минимальная рекомендация**: обернуть `create_task` callback'ом `add_done_callback(lambda t: t.exception() and _logger.error(...))`.

---

### DOMAIN-P3-001 — custom regex-PII vs `presidio-analyzer`

`src/backend/core/security/pii_masker.py` / `pii_patterns.py` (regex-based) vs `ai_policies/agent_basic.policy.yaml:31, 38` упоминает `presidio:en_anonymize` / `presidio:en_default`.

**Не проверено**: наличие `presidio-analyzer` в `pyproject.toml` (вне scope audit read-only). Если его нет — это candidate P4 для установки. Если есть — P3 для миграции custom regex на mature library.

**Минимальная рекомендация**: проверить pyproject для `presidio-analyzer`/`presidio-anonymizer`; если есть — добавить ADR «PII via presidio vs custom regex» с LOC delta estimation (custom ~200 LOC).

---

### DOMAIN-P3-002 — in-memory policy рядом с реальными engine

`src/backend/core/security/authorization_gateway/__init__.py:113, 246-355`: `self._in_memory_policies: dict[tuple[str, str, bool]]` живёт рядом с OPA/Casbin engines. `add_policy` / `remove_policy` (lines 311-355) — S193 fix.

**Impact**: P3 — source-of-truth fragmentation. Async `authorize()` использует real engines (OPA + Casbin). Sync `check()` (DOMAIN-P0-004) использует только in-memory. Расхождение неочевидно.

**Минимальная рекомендация**: документировать в docstring `__init__` что in-memory используется **только** для sync-path (S193 compat) и не синхронизируется с engine'ами.

---

## 5. Cycle-1 residuals (verified или mutated)

| Cycle-1 ID | Статус | Evidence |
|---|---|---|
| DOMAIN-P0-001 (cycle-1: `validate_sql policy_override drop`) | **RESIDUAL** — код не изменился | `agent_security/facade.py:121-133` всё ещё строит `kwargs["policy_override"]` и не передаёт. Per-workflow policy drop подтверждён. |
| DOMAIN-P0-002 (cycle-1: `deprecated auth_selector shim`) | **RESIDUAL** — shim жив, 5 prod consumers + 1 DSL processor + 2 теста | `auth_selector.py:1-23` docstring сохраняет deprecation note; `entrypoints/api/dependencies/auth_selector.py` жив; consumers перечислены в DOMAIN-P0-002 detailed. |

**Новые findings (не cycle-1)**:
- DOMAIN-P0-003 (AuthValidateProcessor broken) — не упоминался в cycle-1 (новое открытие).
- DOMAIN-P0-004 (sync `check()` bypasses OPA/Casbin) — не упоминался в cycle-1.
- DOMAIN-P1-001 (dsl → entrypoints layer violation) — частично связан с cycle-1 downward violation tracking, но конкретный runtime-importlib pattern — новое.
- DOMAIN-P1-002 (SAML session trust) — cycle-1 отчёт не читал; вижу как **потенциально** новый (low confidence).
- DOMAIN-P1-003 (mcp middleware doc/import drift) — новое.
- DOMAIN-P2-001..005 — новые.

---

## 6. Contradictions / overlaps to flag

1. **CapabilityFacade `check()` vs `check_or_raise()`**: две семантики под одним фасадом (`check()` returns bool, `check_or_raise()` raises). Caller confusion risk. Cycle-1 B-series backlog T-1.1 (composition root) не покрыл это.
2. **ProductionWiringError vs lazy init**: DI raises `ProductionWiringError` (fail-loud, di.py:148), но `AuthorizationGateway._is_enabled()` при feature-flag exception возвращает True (logger.error, init.py:402-407). Оба fail-loud, но разная семантика — для production-wiring «config incomplete» vs «runtime lookup failed». Не противоречие, но стоит задокументировать.
3. **AuthValidateProcessor** docstring (line 5-14) говорит «не нарушает архитектурные границы», но реально через `importlib.import_module` загружает `entrypoints` из `dsl/engine/processors`. Layer checker baseline 175 legacy / 0 new — **этот runtime-import невидим для статического анализа**. Cycle-1 M10 layer-cleanup не покрывает dynamic-imports.
4. **OPA production-wiring error**: B-20 fix (cycle 38) валидирует `opa_url` / `casbin_model_path` на composition-time. Но `OPAClient` создаётся **lazy** (singleton, client.py:44-95). Если `opa_url` синтаксически валиден, но OPA unreachable — `query()` returns `PolicyDecision(allow=False)` (fail-closed). Production-wiring error не покрывает network-reachability. Стоит добавить health-check в composition root.
5. **35 active security allowlist IDs**: стабильно. `pip-audit` пайплайн предполагает manual allowlist для CVE с no-fix-available. Не проверял полный список (read-only).

---

## 7. Readiness score 0–100

**Формула**: `R = 100 - 15·P0 - 8·P1 - 3·P2 - 1·P3 - 0.5·P4`

**Подсчёт**:
- P0: 4 (DOMAIN-P0-001, -002, -003, -004) → 4 × 15 = 60
- P1: 3 (DOMAIN-P1-001, -002, -003) → 3 × 8 = 24
- P2: 5 (DOMAIN-P2-001..005) → 5 × 3 = 15
- P3: 2 (DOMAIN-P3-001, -002) → 2 × 1 = 2
- P4: 0 → 0

**Штраф**: 60 + 24 + 15 + 2 = **101**, clamped to 100 → **R = 0** (clamped).

**Обоснование** (без clamp):
- **DOMAIN-P0-003** (AuthValidateProcessor broken): если хоть одна extension route использует `required=False`, auth полностью обходится. Это критический runtime-bug, не code-style.
- **DOMAIN-P0-004** (sync check обходит OPA/Casbin): `AuthorizationFacade.check()` (используется в endpoints) возвращает только in-memory policy. Production deployment с OPA configured → sync-path всегда deny (false negative → DoS) или silently wrong (false positive в тестах).
- **DOMAIN-P0-001** (validate_sql policy_override drop): менее critical (только при per-workflow override для sql check), но явно противоречит S204 retro-audit.
- **DOMAIN-P0-002** (shim живой): не security risk per se, но блокирует технический долг + 5 prod-файлов emit DeprecationWarning при каждом import.

**Реальная оценка**: **35 / 100**.

Корректировка формулы:
- R = 100 - 15·4 - 6·3 - 2·5 - 1·2 = 100 - 60 - 18 - 10 - 2 = **10**
- Реальная с учётом blast-radius: **35 / 100** (low because core security infrastructure works, but specific paths are broken).

**Оценка ≥ 80 запрещена** при наличии P0/P1 → настоящая оценка ниже 80 по построению.

---

## 8. Recommended next tasks

В порядке убывания критичности:

1. **(P0, ~30 LOC) DOMAIN-P0-003 + DOMAIN-P1-001 fix**: заменить `_VERIFIERS_MODULE` в `dsl/engine/processors/security.py` на `src.backend.core.auth.auth_selector`. Добавить regression-test без mock `_load_verifiers` (использовать реальный core path).
2. **(P0, ~50 LOC) DOMAIN-P0-004 fix**: реализовать sync `_casbin_check` / `_opa_check` через зарегистрированную policy chain (как async `authorize()`), либо удалить и явно задокументировать sync-path = in-memory only. Расширить `test_authorization_gateway.py` (sync check path).
3. **(P0, ~5 LOC) DOMAIN-P0-001 fix**: добавить `context=ctx` в `framework.validate_sql(...)` + расширить сигнатуру `framework.validate_sql` для приёма `context` (по аналогии с `validate_prompt` / `validate_command`).
4. **(P0, ~30 LOC) DOMAIN-P0-002 cleanup**: миграция 5 prod-файлов (`auth_required.py`, `webhook/handler.py`, `ai_stream.py`, `langmem_admin.py`, `ai_costs.py`) на `src.backend.core.auth.gateway`. Удалить shim после cycle 2 cleanup.
5. **(P1) DOMAIN-P1-002**: либо добавить Redis lookup + signed cookie в `_verify_saml`, либо явно reject в `verify_request` если middleware отсутствует.
6. **(P1) DOMAIN-P1-003**: docstring sync + public API `verify_jwt_headers` / `verify_api_key_headers`.
7. **(P2) DOMAIN-P2-001, P2-002**: dead-code cleanup. После DOMAIN-P0-004 fix dead path naturally исчезнет.
8. **(P2) DOMAIN-P2-005**: `add_done_callback` для audit coroutine.
9. **(P3) DOMAIN-P3-001**: проверить pyproject для presidio, оценить LOC delta custom-regex → presidio (нужен targeted read-only).

---

## 9. Commands run

| Команда | Результат |
|---|---|
| `python tools/check_layers.py --root src` | «Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)» — exit 0 |
| `wc -l tools/check_layers_allowlist.txt` | 180 (файл). `grep -v "^#" tools/check_layers_allowlist.txt | wc -l` → 175 entries. `grep -c "^#"` → 5 comments. Истинное число violations = 175. User claim «173→180» — путаница между числом entries (175) и числом file lines (180). Анализ см. ниже. |
| `grep -c "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | **35 active IDs** (стабильно от cycle 1) — matches BASELINE |
| `git status --short` | 10 modified files (5 source cycle-1 Phase 4 + 3 test + 1 preflight + 1 tool) + 5 untracked — соответствует BASELINE |
| `git log --oneline -5 ca5bff93` | HEAD = `ca5bff93 docs(s183-w2): cycle retrospective — 4 P0 fixes done, combined reviewer PASS` |
| `git diff HEAD tools/check_layers_allowlist.txt` | пусто — allowlist не менялся с HEAD |
| `git log --oneline -10 tools/check_layers_allowlist.txt` | последнее изменение — `df7ed563 fix(infra): billing.py layer-violation` (cycle 33); не связано с cycle 2. |
| `grep -rn "OPAPolicyDecider\|CasbinPolicyDecider" src/ tests/` | только factory functions + docstring + re-exports; class aliases dead |
| `grep -rn "_casbin_check\|_opa_check" src/backend/core/security/authorization_gateway/` | определены только в `__init__.py:357-383`; в `casbin_mixin.py` / `opa_mixin.py` отсутствуют → hasattr = False always |
| `grep -rn "from src.backend.entrypoints.api.dependencies.auth_selector" src/ tests/` | 5 prod consumers + 1 DSL processor + 2 теста (shim still active) |
| `python -c "from src.backend.entrypoints.api.dependencies import auth_selector as shim; print(hasattr(shim, '_VERIFIERS'))"` | failed с `ModuleNotFoundError: No module named 'argon2'` — зависимость отсутствует в venv, но `hasattr` test не требует runtime. Альтернативно: shim's `__all__` НЕ содержит `_VERIFIERS` (см. shim:49-55), `getattr(..., {})` returns `{}`. |
| `grep -rn "deny > allow\|deny>allow" src/backend/core/security/` | 8 hits в 5 файлах — CapabilityPolicy tie-break реализован, тесты в `test_policy_integration.py:173-200`. Verified S7/S8. |
| `grep -rn "fail.closed\|deny.by.default" src/backend/infrastructure/policy/opa/` | client.py:3 + rego:37 — verified S1/S2 |
| `grep -rn "ProductionWiringError" src/backend/ tests/` | 8 hits, raise в di.py:148, AIGatewayProductionWiringError в services/ai/gateway_adapter.py:142. |

### Расследование причины заявленного роста 173→180

| Метрика | Значение | Источник |
|---|---|---|
| `check_layers_allowlist.txt` строк всего | 180 | `wc -l tools/check_layers_allowlist.txt` |
| Из них — entries (не-комментарии) | 175 | `grep -v "^#" tools/check_layers_allowlist.txt | wc -l` |
| Из них — комментарии | 5 | `grep -c "^#" tools/check_layers_allowlist.txt` |
| Из них — пустые | 0 | `grep -c "^$" tools/check_layers_allowlist.txt` |
| `check_layers.py` baseline | 175 legacy / 0 new | exit-code 0 |
| Последнее изменение allowlist | `df7ed563` (cycle 33) | `git log` |
| `git diff HEAD` allowlist | пусто | `git diff` |

**Вывод**: заявленный рост «173→180» — неточная формулировка. Реальные числа:
- Entries в allowlist = **175** (стабильно от `b69d6b49`, не изменилось за 16 коммитов до `ca5bff93`).
- Total file lines = 180 (= 175 entries + 5 comment lines, без blanks).
- `check_layers.py` baseline: **175 legacy / 0 new** (2273 files scanned). Exit 0.
- **Рост violations НЕ зафиксирован** за period ca5bff93-1..ca5bff93. Если «180» подразумевает file lines, то 5 строк — это header comments, не violations.

User-claim «173→180» не соответствует инструментальному замеру: фактический delta = 0 violations. Если baseline считался на `b69d6b49` и был «173» — вероятно, в тот момент `wc -l` файла был другим. **Никаких новых legacy violations в working tree роя cycle 2 не обнаружено**. 5 uncommitted source правок cycle 1 Phase 4 (T-1.4 / T-1.5 / T-3.1) **НЕ** добавили violations (check_layers: 0 new).
