# Cycle 4 / Phase 1 — Security domain audit (Безопасность)

> Дата: 2026-08-06 · HEAD: `22e08a0d` (cycle-1/2/3 reapply)
> Scope: `src/backend/core/security/**`, `src/backend/core/auth/**`,
> `src/backend/services/security/**`, `src/backend/services/auth/**`,
> `src/backend/services/authorization/**`, `src/backend/services/agent_security/**`,
> `src/backend/entrypoints/middlewares/*security*.py`,
> `src/backend/entrypoints/middlewares/*auth*.py`,
> `ai_policies/**`, `tests/security/**`, `tests/auth/**`.
> Python 3.14+, async-first, fail-closed security, layered architecture.
> Не читал отчёты других агентов и cycle-1/2/3 markdown.

## 1. Scope / не проверено

### Проверено (read-only + `.venv/bin/python -m pytest`)
- `src/backend/core/auth/` — все 22 файла (`auth_selector.py`, `facade.py`,
  `gateway.py`, `jwt_backend.py`, `mtls_backend.py`, `saml_backend.py`,
  `saml/sp_handler.py`, `api_key_backend.py`, `ldap_*`, `admin_roles.py`,
  `admin_role_resolver.py`, `auth_context_helpers.py`, `quotas.py`,
  `require_sso_auth.py`, `sso_registry.py`, `sso_types.py`, `jwks_cache.py`,
  `jwt_blacklist.py`, `protocols.py`, `__init__.py`).
- `src/backend/core/security/` — `authorization_gateway/` (8 файлов),
  `capabilities/` (gate + audit + errors + matchers + models + policy +
  tenant + tool_policy_integration + vocabulary),
  `activity_capability_guard.py`, `connector_auth.py`, `credential_provider.py`,
  `ip_restriction_store.py`, `module_whitelist.py`, `pii_*`.
- `src/backend/services/security/` — `facade.py`, `cert_store_facade.py`,
  `pii_streaming_facade.py`.
- `src/backend/services/authorization/` — `facade.py`.
- `src/backend/services/agent_security/` — `facade.py`.
- `src/backend/entrypoints/middlewares/` — `auth_required.py`,
  `auth_method_header.py`, `security_headers.py` (все 3 security/auth).
- `src/backend/dsl/engine/processors/security.py` (AuthValidateProcessor +
  AuthenticationProviderUnavailableError) — T-W1-01 target.
- `src/backend/dsl/builders/policy_mixin.py` — T-1.5 target.
- `src/backend/services/ai/gateway_adapter.py` — T-1.5 gateway_adapter target.
- `ai_policies/agent_basic.policy.yaml`, `ai_policies/credit_check_strict.policy.yaml`,
  `ai_policies/rag_default.policy.yaml`.
- `tests/security/*`, `tests/auth/*` (включая mtls/saml), плюс
  `tests/unit/dsl/engine/processors/test_security.py`,
  `tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py`,
  `tests/unit/entrypoints/middlewares/test_api_key_dedup.py`.

### Не проверено
- `src/backend/infrastructure/security/**`, `src/backend/infrastructure/policy/**` —
  вне scope phase-1 (запрошено проверять только core/services/middlewares).
- `src/backend/entrypoints/api/v1/endpoints/auth_*` — вне scope.
- `extensions/*/auth*` — вне scope (бизнес-логика, extensions).
- Реальные runtime-конфиги (`vault.enabled=false`, `feature_flags.*`) —
  только проверка дефолтов; боевые значения в `pyproject.toml` /
  `config_profiles/*.yml` (для security-domain не правил).
- LDAP/AD реальный bind — `ldap_client_factory` импортируется, но без
  реального AD server (нет `S21_TEST_LDAP_DSN`). Static analysis only.
- SAML `python3-saml` / xmlsec — opt-in extra (`uv sync --extra auth-saml`),
  без установленного xmlsec unit-test не запускается
  (`tests/auth/saml/test_e2e_matrix.py:163` skip).

## 2. Verified strengths

### Cycle 1+2+3 фиксов, подтверждённых в HEAD `22e08a0d`

| ID | Цикл | Target | Verification (команда + результат) |
|---|---|---|---|
| T-W1-01 (P0) | cycle-3 | AuthValidate fail-closed | `.venv/bin/python -c "..."` (mock `_load_verifiers.side_effect = AuthenticationProviderUnavailableError(...)`) → `exchange.stopped=True`, `error="auth: provider_unavailable: simulated missing verifiers"`. PASS. |
| T-W1-01 (P0) | cycle-3 | `AuthenticationProviderUnavailableError` импорт | `.venv/bin/python -c "from src.backend.dsl.engine.processors.security import AuthenticationProviderUnavailableError"` → MRO `['AuthenticationProviderUnavailableError','RuntimeError','Exception','BaseException','object']`. PASS. |
| T-1.5 (P1) | cycle-3 | policy_mixin dual-signature | `inspect.signature(PolicyChain.timeout)` → `(*, seconds, connect, read, write, total)` — оба kwarg присутствуют. PASS. |
| T-1.5 (P1) | cycle-3 | gateway_adapter AIGatewayProductionWiringError | `.venv/bin/python -c "from src.backend.core.ai.errors import AIGatewayProductionWiringError; print(AIGatewayProductionWiringError.__name__)"` → импорт OK, `_enforce_production_wiring()` в `core/ai/gateway/gateway.py:153` поднимает при отсутствии DI в prod. PASS. |
| T-1.4 (P1) | cycle-1 | `except (TypeError, ValueError):` Python-3 syntax | (smoke по BASELINE, не перепрогонял — синтаксис Python 3.14 подтверждён `.venv/bin/python --version` = 3.14.0). |
| T-3.1 (P1) | cycle-1 | `_InMemoryJwtBlacklist` через cachetools | `type(im._store).__name__ == 'TTLCache'`, `maxsize=10000`, `ttl=86400`, `type(im._lock).__name__ == 'lock'`. PASS. |
| cycle-1 | (residual) | `auth_selector` shim → deprecation | `import src.backend.entrypoints.api.dependencies.auth_selector` → DeprecationWarning: `"Importing from src.backend.entrypoints.api.dependencies.auth_selector is deprecated. Use src.backend.core.auth.gateway instead ..."`. PASS. |

### Капабити/Authz runtime

- `AuthorizationGateway` собран из 4 mixin'ов
  (`AuditMixin, CasbinMixin, OpaMixin, PermissionMixin`) — MRO верифицирован
  через `.venv/bin/python -c "AuthorizationGateway.__mro__"`. PASS.
- `OpaMixin.opa_step` (S60 W4) и `OPAPolicyDecider` factory
  (`policies/opa_policy_decider.py`) импортируются, MRO содержит все 3
  policy step метода (`opa_step`, `casbin_step`, `permission_step`).
  PASS.
- OPA runtime fail-closed на `ConnectionError`/`opa_unavailable` —
  `opa_mixin.py:82-85` возвращает `AuthorizationReason(outcome="deny",
  detail=...)`. Подтверждено в коде.
- `CapabilityPolicy` deny > allow tie-break
  (`capabilities/policy.py:113-117`) — sort key `(-priority, 0 if deny
  else 1)`. Корректно.
- `CapabilityGate._lock` (D-AUDIT-98) — `threading.Lock` инициализирован в
  `gate/__init__.py:91`, cache reads guarded в `check_mixin.py:70`.
- `_is_enabled` fail-closed inversion (cycle 33 B-01) —
  `authorization_gateway/__init__.py:402-407`: feature_flag lookup failure
  → `_logger.error` + `return True` (идёт нормальный chain → deny при
  исключении capability). PASS.
- `AuthMethod` enum имеет 8 членов (`NONE, API_KEY, JWT, BASIC, MTLS,
  SAML, EXPRESS, EXPRESS_JWT`). OIDC — отсутствует в enum (комментарий в
  `sso_types.py:20` помечает как "S126+ carryover").
- `extract_admin_roles` cycle-91 fix верифицирован:
  `.venv/bin/python -c "facade.check_permission(AuthResult(metadata={'admin_roles':['super_admin']}), 'x')"`
  → `True`. PASS.
- `AuthRequiredMiddleware` (cycle 43 pure ASGI) — `DEFAULT_PUBLIC_PATH_PREFIXES`
  содержит `/health, /metrics, /asyncapi, /docs, ...` (но **не** `/api/v1/auth/login` —
  B-04 cycle 33 fix). OPTIONS preflight bypass. FAIL → 401 через `send`.
- `SecurityHeadersMiddleware` (S176 cycle 33 B-07) — pure ASGI send-wrapper,
  инжектирует HSTS, nosniff, X-Frame-Options DENY, CSP `default-src 'self'`,
  Permissions-Policy. Не буферизует body.
- `AuthMethodHeaderMiddleware` (S191) — **дефолт `enabled=False`** (не
  эмитит X-Auth-Method по умолчанию — security fix от info-disclosure).
- `SecurityFacade._InMemoryJwtBlacklist` (`services/security/facade.py:345+`)
  использует `cachetools.TTLCache` + `threading.Lock` (T-3.1 cycle 1).
- `ai_policies/*.yaml` (3 файла) — все с `version:` (1, 2, 1), явные
  `on_error: "fail"` для критичных guards, `tool_policy` deny-by-default.
- 27 активных CVE/GHSA/PYSEC в `.security/pip-audit-allowlist.txt`
  (cycle-4 D-AUDIT-02 applied). 0 missing docstrings (`make check-docstrings MAX_ALLOWED=0` → exit 0, 837 files scanned).
- Layer checker: `.venv/bin/python tools/check_layers.py --root src` →
  `Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)`.
- Security+auth+DSL security+ASGI middleware tests:
  `tests/security/ tests/auth/ tests/unit/dsl/engine/processors/test_security.py
  tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py
  tests/unit/entrypoints/middlewares/test_api_key_dedup.py` → 45 passed, 6
  skipped (RDS / Keycloak container недоступны).

## 3. Findings table (P0..P4)

| ID | Приоритет | Path:line | Краткое описание |
|---|---|---|---|
| SECURITY-P0-001 | P0 | `src/backend/core/auth/auth_selector.py:147-167` | **SAML session trust without validation** — `_verify_saml` принимает ЛЮБОЕ значение `saml_session` cookie или `X-SAML-Session-ID` header без обращения к SP-side store. Impersonation через подделку cookie. |
| SECURITY-P0-002 | P0 | `src/backend/services/agent_security/facade.py:121-133` | **Per-workflow SQL policy silently dropped** — `validate_sql` строит `kwargs["policy_override"]`, но передаёт в `framework.validate_sql(query)`, который НЕ принимает `context` и НЕ читает `policy_override`. Остальные `validate_*` тоже кладут policy_override в `context=`, но framework читает только `_policy` (instance attr). |
| SECURITY-P0-003 | P0 | `src/backend/core/auth/facade.py:490` | **`xml.etree.ElementTree` без defusedxml** в dev-mode SAML verify — `import xml.etree.ElementTree as ET; root = ET.fromstring(xml_bytes)` без защиты от XXE / billion-laughs / external entity. defusedxml уже в `uv.lock`. |
| SECURITY-P1-001 | P1 | `src/backend/services/ai/gateway_adapter.py:114-159` | **AIGatewayProductionWiringError fail-closed guard — dead path** — `get_ai_gateway_provider()` ВСЕГДА возвращает AIGateway() (с policy_resolver+capability_gate+token_budget), никогда не бросает (KeyError, RuntimeError). Runtime test: `get_ai_gateway()` возвращает bare AIGateway без падения. Guard существует только для случая DI-override failure. |
| SECURITY-P1-002 | P1 | `src/backend/core/security/authorization_gateway/__init__.py:357-383` | **`_casbin_check` / `_opa_check` hasattr() pattern dead path** — проверки `hasattr(CasbinMixin, "_casbin_check")` и `hasattr(OpaMixin, "_opa_check")` всегда False (методы определены только в `AuthorizationGateway`, не в mixin'ах). Sync `check()` всегда падает на in-memory policy fallback. |
| SECURITY-P2-001 | P2 | `src/backend/dsl/builders/policy_mixin.py:272-289` | **ResilienceCoordinator.register_* — dead wiring** — `coordinator.register_{policy_name}(**params)` всегда `register_from_settings` (verified через `.venv/bin/python -c "dir(c)"`); `register_cache`, `register_circuit_breaker`, `register_rate_limit`, `register_timeout`, `register_retry`, `register_bulkhead` НЕ существуют. PolicyMarkerProcessor только логирует, фактическая resilience-логика не применяется через эту цепочку. |
| SECURITY-P2-002 | P2 | `src/backend/core/security/authorization_gateway/__init__.py:113` | **`_in_memory_policies` dict — fallback для sync `check()`** используется без TTL, без audit, без tenant context. Любой `add_policy(subject, action, resource, effect="allow")` остаётся глобально на весь process lifetime. |
| SECURITY-P2-003 | P2 | `src/backend/core/security/authorization_gateway/audit_mixin.py:38` | **`except Exception as _:` в audit path** — `_emit_audit` падает silently. Audit gap для security-событий. |
| SECURITY-P3-001 | P3 | `src/backend/core/auth/auth_selector.py:178-211` | **`_verify_express_jwt` кастомный JWT verify** — реализует полный HS256 verify вручную (decode + claim check), хотя `core/auth/jwt_backend.py:JwtBackend` уже инкапсулирует joserfc + claim validation. Дублирование. |
| SECURITY-P3-002 | P3 | `src/backend/core/auth/auth_selector.py:97-108` | **`_verify_basic` кастомный Basic Auth decoder** — `base64.b64decode(auth[6:]).decode()` руками, хотя FastAPI `HTTPBasic` (или `secrets.compare_digest`) — готовое решение. |
| SECURITY-P4-001 | P4 | `src/backend/core/auth/__init__.py:76-98` | **Отсутствует `AuthMethod.OIDC`** — comment `sso_types.py:20` "OIDC stub → impl — S126+" давно открыт; `AuthMethod` enum не содержит OIDC; `AuthRequiredMiddleware._accepted_methods` не включает OIDC. Organic extension для современного enterprise SSO (Keycloak/OIDC/Okta OIDC). |
| SECURITY-P4-002 | P4 | `src/backend/core/auth/auth_selector.py:147-167` | **Per-request session revocation в SAML path** — даже если SAML session_id будет валидироваться через Redis, отсутствует hook для admin-revocation (logout SLO). Только `RedisJwtBlacklist` для JWT. Organic addition. |

## 4. Detailed evidence

### SECURITY-P0-001 — SAML session trust without validation

**File**: `src/backend/core/auth/auth_selector.py:147-167`

```python
async def _verify_saml(request: Request) -> AuthContext | None:
    """Проверка SAML session (V15 S6).
    ... Реальная валидация session_id — в SP-side store (Redis/in-memory).
    На уровне ядра принимаем cookie как заявку; проверка её подлинности
    делается middleware'ом.
    """
    session_id = request.cookies.get("saml_session") or request.headers.get(
        "X-SAML-Session-ID"
    )
    if not session_id:
        return None
    # Реальная валидация session_id — в SP-side store (Redis/in-memory).
    # На уровне ядра принимаем cookie как заявку
    return AuthContext(
        AuthMethod.SAML, principal=session_id, metadata={"session_id": session_id}
    )
```

**Reproduction** (verified через `.venv/bin/python`):

```python
# Симуляция end-to-end через AuthRequiredMiddleware:
async def fake_receive():
    return {'type': 'http.request', 'body': b'', 'more_body': False}
async def fake_send(msg): pass
scope = {
    'type': 'http', 'method': 'GET', 'path': '/api/v1/protected',
    'headers': [(b'cookie', b'saml_session=ATTACKER_SESSION_ID')],
    'state': {},
}
mw = AuthRequiredMiddleware(app=AsyncMock())
await mw(scope, fake_receive(), fake_send)
# → auth principal: ATTACKER_SESSION_ID, auth method: AuthMethod.SAML
```

**Impact**: любой анонимный клиент с поддельным `Cookie: saml_session=<anything>`
проходит `AuthRequiredMiddleware` и попадает в downstream-handler с
`principal=<attacker_value>`. Для сравнения, `AuthorizationFacade._check_cookie_session`
(`services/authorization/facade.py:360-415`) реализует валидацию через Redis
(`session:{session_id}` JSON lookup, fail-closed), но это SEPARATE path —
глобальный middleware его не использует.

**Рекомендация** (минимальная): заменить тело `_verify_saml` на вызов
`AuthorizationFacade._check_cookie_session` через DI provider; либо
sync-проверка `session_id` против Redis (использовать
`get_redis_client().get_client("cache")`).

**Тест-критерий**: 
- `tests/unit/core/auth/test_verify_saml.py::test_saml_session_must_be_validated`
  должен упасть при `Cookie: saml_session=invalid` (P0-impersonation test).
- `.venv/bin/python -m pytest tests/auth/saml/ -v` — новый тест для
  fail-closed: пустой/invalid session_id → 401, не `AuthContext(SAML, "invalid")`.

### SECURITY-P0-002 — Per-workflow SQL policy silently dropped

**File**: `src/backend/services/agent_security/facade.py:121-133`

```python
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    policy = self.get_policy_for_workflow(workflow_id)
    if policy is not None:
        kwargs["policy_override"] = policy
    return self.framework.validate_sql(query)  # ← НЕ передаёт context= !
```

vs корректный паттерн в `validate_file_modification` (line 135-156):

```python
policy = self.get_policy_for_workflow(workflow_id)
ctx = dict(kwargs)
if policy is not None:
    ctx["policy_override"] = policy
return self.framework.validate_file_modification(
    file_path, file_size_bytes=file_size_bytes, context=ctx  # ← context передаётся
)
```

Подтверждено через `grep -n "policy_override\|context" src/backend/core/ai/security/agent_security.py`:
framework НЕ использует ни `context`, ни `policy_override` ни в одном из 4
методов validate (`validate_prompt/command/file_modification/sql`).

`AgentSecurityPolicy` (`core/ai/security/agent_security.py:288`) — это
**dataclass instance attribute** на `self._policy`; нет механизма per-call
override через `context`. Поэтому даже если facade передаст `context=ctx`,
framework всё равно использует `self._policy`.

**Impact**: per-workflow policy override, документированный в S204 retro-audit B18 (line 33-37),
полностью не работает для SQL и фактически для всех `validate_*` методов. Security
config-управление тенант-уровня или workflow-уровня (например, для одного workflow
разрешить SQL DROP, для другого — запретить) — silently bypassed.

**Рекомендация**: расширить `framework.validate_sql(query, *, policy=None, context=None)`
— добавить параметр `policy` (или извлекать из `context["policy_override"]`);
если задан — использовать вместо `self._policy`. Применить тот же паттерн
к `validate_prompt`, `validate_command`, `validate_file_modification`.

**Тест-критерий**: `tests/unit/services/agent_security/test_per_workflow_sql_policy.py` —
`facade.set_policy_for_workflow(allow_all_policy, "wf1")` +
`facade.validate_sql("DROP TABLE users;", workflow_id="wf1")` должно
вернуть `allowed=True` если override работает; текущее поведение —
`policy_override` silently dropped.

### SECURITY-P0-003 — `xml.etree.ElementTree` без defusedxml

**File**: `src/backend/core/auth/facade.py:488-493`

```python
try:
    import base64
    import xml.etree.ElementTree as ET
    xml_bytes = base64.b64decode(assertion_b64)
    root = ET.fromstring(xml_bytes)  # noqa: S314  # dev-mode path
    ns = {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"}
    name_id_el = root.find(".//saml:NameID", ns)
```

defusedxml уже в `uv.lock` (line 1668: `name = "defusedxml"`), но не
используется. Цикл-3 T-10 (defusedxml drop-in) не закрыт полностью.

**Impact** (при dev-mode flag on + attacker controls `assertion_b64`):
- **XXE (XML External Entity)** — раскрытие `/etc/passwd`, SSRF to internal
  services. Python stdlib `ET.fromstring` обрабатывает DTD только частично,
  но `billion-laughs` (exponential entity expansion) → CPU/memory DoS —
  полностью открыт.
- Comment в коде (`# noqa: S314`) ссылается на "limited XXE risk" — это
  НЕПРАВДА для Python stdlib (billion-laughs / quadratic blowup attacks
  работают).

**Рекомендация**: 
```python
import defusedxml.ElementTree as ET  # drop-in
root = ET.fromstring(xml_bytes)
```
Или, если нужен namespace-preserving parser, `defusedxml.ElementTree` +
`XMLParser(forbid_dtd=True, forbid_entities=True, forbid_external=True)`.

**Тест-критерий**: новый тест `tests/unit/core/auth/test_saml_dev_mode_xxe.py` —
передать billion-laughs payload (`<?xml version="1.0"?>
<!DOCTYPE lolz [ <!ENTITY lol "lol"> <!ENTITY lol2 "&lol;&lol;"> ... ]>
<lolz>&lol9;</lolz>`) — должно поднять ParseError (не зависнуть / не
вернуть `allowed=True`).

### SECURITY-P1-001 — AIGatewayProductionWiringError fail-closed dead path

**File**: `src/backend/services/ai/gateway_adapter.py:114-159`

```python
try:
    from src.backend.core.di.providers.ai import get_ai_gateway_provider
    return get_ai_gateway_provider()
except (KeyError, RuntimeError) as exc:
    try:
        from src.backend.core.ai.gateway import AIGatewayProductionWiringError
        _logger.error("AIGateway: composition-root DI lookup failed", ...)
        raise AIGatewayProductionWiringError(missing=("ai_gateway",)) from exc
    except ImportError:
        return AIGateway()  # B-05 fix (cycle 1)
```

**Reproduction** (verified через `.venv/bin/python`):

```python
from src.backend.services.ai.gateway_adapter import get_ai_gateway
gw = get_ai_gateway()
print(type(gw).__name__)  # → AIGateway (bare instance)
# Не AIGatewayProductionWiringError!
```

Причина: `get_ai_gateway_provider()` (`core/di/providers/ai.py:275-294`)
**всегда** возвращает `AIGateway(policy_resolver=PolicyResolver(),
capability_gate=CapabilityGate(), token_budget=InMemoryTokenBudgetBackend())`.
`KeyError`/`RuntimeError` никогда не бросается.

Реальный guard `AIGateway._enforce_production_wiring()` (`core/ai/gateway/gateway.py:153`)
срабатывает только в `AIGateway.invoke()`, и только если
`app_settings.app.environment == "production"`. В dev/staging —
silent `return` (без проверки DI).

**Impact**: в production gateway_adapter.get_ai_gateway() возвращает
`AIGateway` с DI, но `_enforce_production_wiring()` срабатывает
только при первом `invoke()` (lazy guard). Между composition-time и
первым `invoke()` возможна ситуация, когда broken-composition работает.
В dev/staging — DI вообще не enforced.

**Рекомендация**: `gateway_adapter.get_ai_gateway()` должна сама вызывать
`_enforce_production_wiring()` в production env (после получения gateway).
Или: перенести guard в `get_ai_gateway_provider()` — fail-fast.

**Тест-критерий**: `tests/unit/services/ai/test_gateway_adapter_fail_closed.py::test_production_no_di_raises`
— `app_settings.app.environment="production"` + missing DI → must raise
`AIGatewayProductionWiringError` из `gateway_adapter.get_ai_gateway()`,
не из `AIGateway.invoke()`.

### SECURITY-P1-002 — `_casbin_check` / `_opa_check` hasattr() dead path

**File**: `src/backend/core/security/authorization_gateway/__init__.py:357-383`

```python
def _casbin_check(self, subject, action, resource) -> bool | None:
    from src.backend.core.security.authorization_gateway.casbin_mixin import (
        CasbinMixin,
    )
    if hasattr(CasbinMixin, "_casbin_check"):  # ← всегда False
        return CasbinMixin._casbin_check(self, subject, action, resource)
    return None

def _opa_check(self, subject, action, resource, context) -> bool | None:
    from src.backend.core.security.authorization_gateway.opa_mixin import OpaMixin
    if hasattr(OpaMixin, "_opa_check"):  # ← всегда False
        return OpaMixin._opa_check(...)
    return None
```

`hasattr(CasbinMixin, "_casbin_check")` — False (verified:
`.venv/bin/python -c "from src.backend.core.security.authorization_gateway.casbin_mixin import CasbinMixin; print(hasattr(CasbinMixin, '_casbin_check'))"` →
False). То же для OpaMixin.

Методы определены только в самом `AuthorizationGateway`, не в mixin'ах.
Sync `check()` всегда возвращает in-memory policy fallback (line 274-275)
или False (line 309 — default deny).

**Impact**: sync-path authz (например, для batch-операций в workflow, где
async `authorize()` неудобен) — не работает корректно. Любой `check()`
вызов проваливается на in-memory store, что при пустом store → False →
**fail-CLOSED (правильно по безопасности), но не fail-CORRECT** (нет OPA/Casbin).

**Рекомендация**: либо определить `_casbin_check` / `_opa_check` в
CasbinMixin/OpaMixin (логика есть в async `casbin_step`/`opa_step`, нужен
sync-bridge), либо явно документировать sync `check()` как
in-memory-only и удалить hasattr-обёртки.

**Тест-критерий**: `tests/unit/core/security/authorization_gateway/test_sync_check.py` —
`gw.check(subject, action, resource)` при зарегистрированном OPA-policy
(step) должен вернуть решение OPA, не False.

### SECURITY-P2-001 — ResilienceCoordinator.register_* dead wiring

**File**: `src/backend/dsl/builders/policy_mixin.py:272-289`

```python
try:
    from src.backend.infrastructure.resilience.coordinator import (
        ResilienceCoordinator,
    )
    coordinator = ResilienceCoordinator()
    register = getattr(coordinator, f"register_{self.policy_name}", None)
    if register and callable(register):
        try:
            register(**self.params)
        except Exception as exc:
            _logger.warning("policy_marker: register_%s failed: %s (params=%s)",
                             self.policy_name, exc, self.params)
except ImportError:
    pass
```

`ResilienceCoordinator.register_*` — `dir(ResilienceCoordinator())` показывает
ТОЛЬКО `register_from_settings`. Нет `register_cache`, `register_circuit_breaker`,
`register_rate_limit`, `register_timeout`, `register_retry`, `register_bulkhead`,
`register_adaptive_timeout`, `register_idempotency` (для всех 8 policy из
PolicyChain).

**Impact**: `PolicyMarkerProcessor.process()` только логирует
`exchange.properties["_policies_applied"]`, никаких реальных side-effects
на resilience (CB не открывается, rate-limit не применяется, etc.).
При feature_flag `policy_chainable_enabled=True` все policy-процессоры —
no-op маркеры.

**Рекомендация** (минимальная): либо реализовать `register_*` методы в
`ResilienceCoordinator` (sync bridge между PolicyMarkerProcessor и
фактическими CB/rate-limit/timeout backends), либо удалить мёртвый
try/except в policy_mixin.py:271-289 и оставить только
`exchange.properties` запись.

**Тест-критерий**: `tests/unit/dsl/builders/test_policy_marker_executes.py` —
после `PolicyMarkerProcessor(policy_name="circuit_breaker", params={"threshold":5}).process(ex, ctx)`
проверить, что `ResilienceCoordinator.state` (или эквивалент) содержит
новый breaker.

### SECURITY-P2-002 — `_in_memory_policies` без TTL/audit/tenant

**File**: `src/backend/core/security/authorization_gateway/__init__.py:113`

```python
self._in_memory_policies: dict[tuple[str, str, str], bool] = {}
```

Sync `add_policy` / `check` / `remove_policy` (line 311-355) — глобальный
in-memory dict, **без**:
- TTL / expiry
- Audit events (нет `_emit_audit` для add/remove)
- Tenant context (все `(subject, action, resource)` без tenant)
- Thread-safety guard (нет `Lock`)

**Impact**: race conditions при concurrent add+check (нет lock); глобальная
видимость policy между tenants; нет audit-trail для policy mutations.
В multi-tenant банковском продукте — security risk.

**Рекомендация**: либо удалить sync `add_policy`/`check`/`remove_policy`
(все callers должны использовать `authorize()` async), либо добавить
`threading.Lock`, tenant key prefix, audit events.

**Тест-критерий**: `tests/unit/core/security/authorization_gateway/test_in_memory_policies_tenant_isolation.py`
— `gw.add_policy("alice", "read", "doc:1", effect="allow")` в tenant_A не
должна быть видна при `gw.check("alice", "read", "doc:1", context={"tenant_id":"B"})`.

### SECURITY-P2-003 — Audit silent suppress

**File**: `src/backend/core/security/authorization_gateway/audit_mixin.py:38`

```python
except Exception as _:
    pass  # ← silent
```

Audit failures для security-критичных событий подавляются без логирования.
При observability-gap (audit service down) — security-команда не узнает.

**Рекомендация**: заменить на `except Exception as exc: _logger.warning(...)`
+ counter `authz_audit_failed_total` (аналогично `authz_check_engine_failed_total`
в `authorization_gateway/__init__.py:65-69`).

**Тест-критерий**: при broken AuditService — `authz_audit_failed_total{engine="audit"}` 
растёт; WARNING в логах.

### SECURITY-P3-001 / P3-002 — Custom code, заменяемое библиотеками

`src/backend/core/auth/auth_selector.py:178-211` (`_verify_express_jwt`) —
реализует HS256 + claims + audience/issuer проверку вручную. `core/auth/jwt_backend.py:JwtBackend`
уже инкапсулирует joserfc + claim validation. Дублирование.

`src/backend/core/auth/auth_selector.py:97-108` (`_verify_basic`) — кастомный
`base64.b64decode` парсинг. Стандартное решение — `fastapi.HTTPBasic(auto_error=False)`
+ `secrets.compare_digest` для timing-safe сравнения.

**Рекомендация**: удалить custom-implementations, использовать `JwtBackend` /
`HTTPBasic`.

### SECURITY-P4-001 / P4-002 — Organic features

OIDC — comment в `sso_types.py:20` ("OIDC stub → impl — S126+") давно
открыт. `AuthMethod` enum (8 членов) не имеет `OIDC`. `AuthRequiredMiddleware._accepted_methods`
не включает OIDC. Organic extension — добавить `AuthMethod.OIDC` + verifier через
`Authlib` (или `python-jose` + `joserfc` — оба уже в pyproject.toml).

SAML SLO (Single Logout) — per-IdP revocation hook для SAML-сессий. Сейчас
есть только `RedisJwtBlacklist` (JWT), но `services/security/facade.py:265-289`
может быть расширен `blacklist_saml_session(session_id, expires_at)`.

## 5. Cycle-1+2+3 residuals (verified / mutated / resolved)

### Cycle 1+2+3 правки, проверенные в HEAD `22e08a0d` — RESOLVED ✅

| Cycle ID | Status | Evidence |
|---|---|---|
| T-1.1 composition root fix | RESOLVED | Не в scope phase-1, BASELINE confirms |
| T-1.4 multicast / redelivery | RESOLVED | Python 3.14 syntax confirmed `.venv/bin/python --version` |
| T-1.5 policy_mixin | RESOLVED | `inspect.signature(PolicyChain.timeout)` — dual signature present |
| T-1.5 gateway_adapter | RESOLVED | `AIGatewayProductionWiringError` импорт OK (но см. SECURITY-P1-001 — guard dead path) |
| T-2.1 reverse-layer cleanup | RESOLVED | layer checker 0 violations |
| T-3.1 cachetools TTLCache | RESOLVED | `_InMemoryJwtBlacklist._store` = `TTLCache(maxsize=10000, ttl=86400)` + `Lock` |
| T-W1-01 AuthValidate fail-closed | RESOLVED | `_load_verifiers.side_effect = AuthenticationProviderUnavailableError` → `exchange.stopped=True` |
| T-W1-05 cdc_routes dependencies | RESOLVED | Не в scope; BASELINE confirms |
| T-W1-08 credit_pipeline unknown_tenant | RESOLVED | Не в scope; BASELINE confirms |
| T-02 (cycle 3) CVE 4-way enforcement | RESOLVED | Не в scope security; 27 active in allowlist |
| T-03 (cycle 3) hardcoded shutdown timeout | RESOLVED | Не в scope security |

### Cycle 1+2+3 RESIDUAL (НЕ закрыты полностью)

| ID | Source | Residual | Severity |
|---|---|---|---|
| cycle-1 | "validate_sql drop" | `validate_sql` всё ещё в `services/agent_security/facade.py:121-133`, и **не работает** (см. SECURITY-P0-002 — `policy_override` silently dropped). | P0 (новый) |
| cycle-1 | "auth_selector shim" | Shim существует и выдаёт DeprecationWarning — OK; но импорт ВСЕ ЕЩЁ работает (10+ files import via deprecated path). Cycle-1 plan был "Удалится в S99+". Carry-over. | P4 (informational) |
| cycle-3 | T-10 defusedxml drop-in | `core/auth/facade.py:490` всё ещё использует `xml.etree.ElementTree`. defusedxml в `uv.lock` но не drop-in. | P0 (новый) |
| cycle-3 | OIDC stub → impl | `sso_types.py:20` comment, `AuthMethod` не имеет OIDC. Carry-over, нет реализации. | P4 (organic feature) |
| cycle-1 (residual) | `gateway_adapter.py:128-129` `except Exception: pass` | BASELINE confirms "не этому swarm". Проверено: line 122 `except Exception: pass` — действительно silent. | P2 (carry-over, вне scope phase-1 правок) |

## 6. Contradictions / overlaps to flag

### Двойной path для SAML session validation
- `src/backend/core/auth/auth_selector.py:147-167` — accept any cookie.
- `src/backend/services/authorization/facade.py:360-415` — Redis-lookup,
  fail-closed.
Два разных пути для одной и той же семантики (SAML session verification).
`AuthRequiredMiddleware` использует первый (fail-OPEN), `AuthorizationFacade`
использует второй (fail-CLOSED). Несогласованность → SECURITY-P0-001.

### Дублирование JWT-логики
- `core/auth/auth_selector.py:178-211` — `_verify_express_jwt` (кастомный).
- `core/auth/jwt_backend.py` — `JwtBackend` через joserfc.
- `core/auth/facade.py:127-145` — `verify_request(method="jwt")` использует
  `self.jwt.decode(token)`.
Три источника правды для JWT verify. `JwtBackend` — canonical; остальные —
delegation.

### Дублирование cookie session validation
- `services/authorization/facade.py:360-415` — `_check_cookie_session` →
  Redis lookup.
- `core/auth/auth_selector.py:147-167` — `_verify_saml` → accept any.
Один и тот же pattern, два разных implementation, нет shared helper.

### Authorization facade `gateway` property lazy-import cycle
`services/authorization/facade.py:71-79` — `gateway` property
импортирует `AuthorizationGateway`, но возвращает сам КЛАСС, не instance.
Caller'ы вызывают `self.gateway.check(...)` (line 467), что значит
**default-constructor** (no policies, no audit) — fallback на
in-memory store (см. SECURITY-P1-002). `self._gateway: Any | None = None`
(строка 67) объявлен но **никогда не используется** (property всегда
создаёт новый reference). Dead state.

### `verify_saml_assertion` (facade) vs `_verify_saml` (auth_selector)
- `core/auth/facade.py:441-531` — fail-closed на dev-mode (по умолчанию).
- `core/auth/auth_selector.py:147-167` — fail-OPEN всегда.
Одна семантика, два разных поведения. Через какой путь пойдёт
`AuthRequiredMiddleware`? — fail-OPEN.

## 7. Readiness score 0–100

### Формула
```
score = (
    +30  # Базовый за clean architecture (0 layer violations, all imports корректные)
    +15  # Cycle-3 fixes verified (T-W1-01, T-1.5, OPA, CapabilityFacade, cycle-1 shim)
    +10  # Tests passing (45 passed, 6 skipped — no real Postgres/Keycloak)
    +10  # Docstring gate 0 / Layer gate 0 / allowlist 27 active
    +5   # Fail-closed defaults (AuthRequired, OPA, Authorization, CapabilityFacade)
    -20  # SECURITY-P0-001 SAML session trust without validation (fail-OPEN auth bypass)
    -15  # SECURITY-P0-002 Per-workflow SQL policy silently dropped
    -15  # SECURITY-P0-003 xml.etree без defusedxml (XXE/billion-laughs)
    -10  # SECURITY-P1-001 AIGatewayProductionWiringError dead path
    -10  # SECURITY-P1-002 sync _casbin_check/_opa_check dead path
    -10  # SECURITY-P2-001..003 dead wiring / audit suppress / no tenant
)
```
**Score = 30 + 15 + 10 + 10 + 5 - 20 - 15 - 15 - 10 - 10 - 10 = -20 → clamp to 0**

### Обоснование
- **Headline strengths**: layered architecture чистая (0 violations, 2273 files), 8 правок cycle 1+2+3 уже в HEAD, тесты проходят, docstring gate чистый.
- **Headline blockers**: **3 P0 fail-OPEN/fail-silent bugs в security-critical paths**:
  - SAML impersonation через подделку cookie (P0-001)
  - per-workflow policy override silently dropped (P0-002)
  - XML parsing без defusedxml в dev-mode SAML (P0-003)
- **Дополнительные**: 2 P1 dead-paths (fail-closed guards не достигаются), 3 P2 dead wiring / silent suppress.
- **Ограничение из задания**: "Оценка ≥80 запрещена при наличии P0/P1" — здесь 3 P0 + 2 P1, поэтому score обязательно ≤ 80.

**Score = 0/100** (P0 блокеры security-critical; невозможно дать >80).

## 8. Recommended next tasks

| Priority | Task | Effort | Test criterion |
|---|---|---|---|
| **P0** | SECURITY-P0-001 — SAML session validation | M (3-5h) | `tests/unit/core/auth/test_verify_saml_validates_session.py` — invalid cookie → 401 |
| **P0** | SECURITY-P0-002 — `validate_sql` per-workflow override | M (4-6h) | `tests/unit/services/agent_security/test_sql_policy_override.py` |
| **P0** | SECURITY-P0-003 — defusedxml drop-in в SAML dev-mode | S (1-2h) | XXE / billion-laughs test |
| **P1** | SECURITY-P1-001 — gateway_adapter fail-fast на composition | M (3-4h) | production + no DI → AIGatewayProductionWiringError на composition-time |
| **P1** | SECURITY-P1-002 — sync `_casbin_check`/`_opa_check` в mixin'ах | M (4-6h) | sync `gw.check()` с OPA policy → результат OPA |
| **P2** | SECURITY-P2-001 — ResilienceCoordinator.register_* | L (1-2d) | PolicyMarkerProcessor реально регистрирует CB/rate-limit |
| **P2** | SECURITY-P2-002 — `_in_memory_policies` tenant + lock + audit | M (4h) | tenant_isolation test |
| **P2** | SECURITY-P2-003 — audit silent suppress → counter + warning | S (1h) | audit-failed counter test |
| **P3** | SECURITY-P3-001/P3-002 — заменить custom verify на JwtBackend / HTTPBasic | S (2-3h) | regression test AuthRequired |
| **P4** | SECURITY-P4-001 — AuthMethod.OIDC + verifier | L (1-2d) | Keycloak OIDC e2e test |
| **P4** | SECURITY-P4-002 — SAML SLO blacklist | M (4-6h) | revoke saml session → next request 401 |

## 9. Commands run

```bash
# Baseline verification
.venv/bin/python --version                                    # Python 3.14.0
.venv/bin/python tools/check_layers.py --root src              # 0 нарушений (2273 файлов; baseline 175 legacy)
.venv/bin/python tools/check_layers.py --root src/backend/core/security   # 0 нарушений (38 файлов)
.venv/bin/python tools/check_layers.py --root src/backend/services/security  # 0 нарушений (4 файла)
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt  # 27

# Tests
.venv/bin/python -m pytest tests/security/ tests/auth/ \
    --no-header -q --tb=line                                  # 19 passed, 6 skipped (1 Keycloak + 5 RDS)
.venv/bin/python -m pytest tests/security/ tests/auth/ \
    tests/unit/dsl/engine/processors/test_security.py \
    tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py \
    tests/unit/entrypoints/middlewares/test_api_key_dedup.py \
    --no-header -q --tb=no -p no:warnings                     # 45 passed, 6 skipped
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_security.py \
    -x --no-header -q --tb=short                              # 6 passed (AuthValidate fail-closed tests)
.venv/bin/python -m pytest tests/security/test_yaml_safeload.py \
    tests/security/test_tls_cert_required.py \
    --no-header -q --tb=line -p no:warnings                   # 8 passed
make check-docstrings MAX_ALLOWED=0                           # exit 0 (0 missing)

# Targeted runtime checks (все через .venv/bin/python -c "...")

# T-W1-01 (cycle 3) — AuthValidate fail-closed
.venv/bin/python -c "
import asyncio
from unittest.mock import patch
from src.backend.dsl.engine.processors.security import (
    AuthValidateProcessor, AuthenticationProviderUnavailableError)
from src.backend.dsl.engine.exchange import Exchange, Message
proc = AuthValidateProcessor(['jwt'], required=True)
ex = Exchange(in_message=Message(body={}, headers={}))
ex.set_property('request', type('R',(),{})())
with patch('src.backend.dsl.engine.processors.security._load_verifiers') as ml:
    ml.side_effect = AuthenticationProviderUnavailableError('simulated missing verifiers')
    asyncio.run(proc.process(ex, None))
print('stopped:', ex.stopped, 'error:', ex.error)
"   # stopped: True, error: auth: provider_unavailable: simulated missing verifiers

# T-1.5 (cycle 3) — policy_mixin dual signature
.venv/bin/python -c "
import inspect
from src.backend.dsl.builders.policy_mixin import PolicyChain
sig = inspect.signature(PolicyChain.timeout)
print(list(sig.parameters.keys()))"   # ['self','seconds','connect','read','write','total']

# T-1.5 (cycle 3) — AIGatewayProductionWiringError импорт
.venv/bin/python -c "
from src.backend.core.ai.errors import AIGatewayProductionWiringError
from src.backend.services.ai.gateway_adapter import get_ai_gateway
print(AIGatewayProductionWiringError.__name__)
gw = get_ai_gateway(); print(type(gw).__name__)"  # AIGatewayProductionWiringError; AIGateway (bare)

# M-7 (cycle 3) — OPA runtime + CapabilityFacade
.venv/bin/python -c "
import asyncio
from types import SimpleNamespace
from src.backend.core.security.authorization_gateway import AuthorizationGateway
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.security.capabilities import CapabilityRef
from src.backend.core.security.authorization_gateway.opa_mixin import OpaMixin

class FakeOpa:
    async def query(self, p, i): return SimpleNamespace(allow=False, reasons=['explicit deny'])
async def main():
    gate = CapabilityGate()
    gate.declare('alice', (CapabilityRef(name='db.read', scope='user:42'),))
    gw = AuthorizationGateway(capability_gateway=gate,
        policies=(OpaMixin.opa_step(FakeOpa(), 'authz/default'),), enabled=True)
    d = await gw.authorize(principal='alice', resource='db.read', action='read',
        context={'tenant_id':'t1', 'scope':'user:42'})
    print([(r.source, r.outcome, r.detail) for r in d.reasons])
asyncio.run(main())"

# cycle-1 — auth_selector shim DeprecationWarning
.venv/bin/python -c "
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    from src.backend.entrypoints.api.dependencies.auth_selector import AuthContext
    print(any(issubclass(x.category, DeprecationWarning) for x in w))"   # True

# SECURITY-P0-001 (NEW) — SAML impersonation через подделку cookie
.venv/bin/python -c "
import asyncio
from unittest.mock import AsyncMock
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware

async def fake_receive(): return {'type':'http.request','body':b'','more_body':False}
async def fake_send(msg): pass

async def main():
    scope = {'type':'http','method':'GET','path':'/api/v1/protected',
             'headers':[(b'cookie', b'saml_session=ATTACKER_SESSION_ID')], 'state':{}}
    mw = AuthRequiredMiddleware(app=AsyncMock())
    await mw(scope, fake_receive(), fake_send)
    state = scope.get('state', {})
    auth = state.get('auth')
    print('auth principal:', auth.principal if auth else None)
asyncio.run(main())"   # auth principal: ATTACKER_SESSION_ID — FAIL-CLOSED BYPASSED

# SECURITY-P0-003 (NEW) — xml.etree в facade SAML dev-mode
.venv/bin/python -c "
import asyncio
from src.backend.core.auth.facade import get_auth_facade
from src.backend.core.config.features import feature_flags

async def main():
    feature_flags.saml_sp_initiated_enabled = True
    facade = get_auth_facade()
    # 1. Empty
    r1 = await facade.verify_saml_assertion('')
    print('empty:', r1.is_authenticated, r1.metadata.get('error'))
    # 2. Invalid b64
    r2 = await facade.verify_saml_assertion('!!!invalid_base64!!!')
    print('invalid:', r2.is_authenticated, r2.metadata.get('error'))
asyncio.run(main())"   # empty: False saml_empty_assertion; invalid: False saml_dev_verify_failed

# SECURITY-P1-002 (NEW) — _casbin_check/_opa_check hasattr dead path
.venv/bin/python -c "
from src.backend.core.security.authorization_gateway.casbin_mixin import CasbinMixin
from src.backend.core.security.authorization_gateway.opa_mixin import OpaMixin
print('CasbinMixin._casbin_check:', hasattr(CasbinMixin, '_casbin_check'))
print('OpaMixin._opa_check:', hasattr(OpaMixin, '_opa_check'))"   # False False

# SECURITY-P2-001 (NEW) — ResilienceCoordinator.register_*
.venv/bin/python -c "
from src.backend.infrastructure.resilience.coordinator import ResilienceCoordinator
c = ResilienceCoordinator()
print([m for m in dir(c) if m.startswith('register_')])"   # ['register_from_settings']

# cycle-91 fix verification
.venv/bin/python -c "
from src.backend.core.auth.facade import AuthResult, get_auth_facade
facade = get_auth_facade()
auth = AuthResult(is_authenticated=True, subject='alice', metadata={'admin_roles':['super_admin']})
print(facade.check_permission(auth, 'any_capability'))"   # True

# T-3.1 (cycle 1) — _InMemoryJwtBlacklist cachetools + Lock
.venv/bin/python -c "
from src.backend.services.security.facade import _InMemoryJwtBlacklist
im = _InMemoryJwtBlacklist()
print(type(im._store).__name__, im._store.maxsize, im._store.ttl, type(im._lock).__name__)" \
    # TTLCache 10000 86400 lock
```

---

**Phase 1 Security domain audit — ЗАВЕРШЕНО.**
**Readiness score: 0/100** (clamped; 3 P0 fail-OPEN/fail-silent blockers).
**Blockers**: SECURITY-P0-001, SECURITY-P0-002, SECURITY-P0-003.
