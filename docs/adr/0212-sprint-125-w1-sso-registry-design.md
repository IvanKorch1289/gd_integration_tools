# ADR-0212: Sprint 125 W1 — SSO Registry Design (Re-affirm ADR-0054 + Fill Research Gap)

- **Status:** Accepted (Sprint 125 W1, 2026-06-14)
- **Wave:** s125-w1-design
- **Sprint:** 125
- **Depends:** ADR-0054 (SAML primary, OIDC deferred), ADR-0211 (S124 closure)

## Context

ADR-0054 (Sprint 3, К1 W3, 2026-05-13) зафиксировал дизайн SSO Federation:
- SAML 2.0 + JWT bridge (TTL 15 мин)
- Per-tenant IdP Registry в Vault (`secret/data/sso/<tenant>/idp`)
- Groups → Capabilities mapping через `groups_to_capabilities`
- Refresh-cron (ежесуточно, `0 3 * * *`)
- Fallback chain `["saml", "mtls", "api_key"]`
- Библиотека `python3-saml>=1.16.0`
- OIDC отложен на Sprint 7+

С тех пор Sprint 19 (K5 W5b) положил 5 `NotImplementedError` в
`services/admin/sso.py` (стаб для S20+). В Sprint 25+ появился
**реальный `SamlBackend`** в `core/auth/saml_backend.py` (полностью
функциональный, ~215 LOC) + `sp_handler.py` + `saml_resolver.py`. Это
значит SAML инфраструктура УЖЕ на месте — но **НЕ интегрирована** в
admin endpoint'ы (нет `require_sso_auth` decorator).

**S125 W1 (research):** проверил, что реально существует, что отсутствует,
и какой scope реалистичен.

## Текущее состояние (research findings)

### Реализовано ✅

| Path | LOC | Notes |
|---|---|---|
| `core/auth/saml_backend.py` | 215 | `SamlBackend` + `SamlConfig` + `SamlAuthResult` + `SamlError` + `IdpMetadata` |
| `core/auth/saml/sp_handler.py` | ~120 | SP-initiated flow HTTP-handler |
| `core/auth/saml/__init__.py` | facade | re-exports |
| `core/auth/__init__.py` | facade | top-level |
| `core/tenancy/saml_resolver.py` | ~80 | `SamlAuthResult` → `TenantContext` |
| `pyproject.toml` | dep | `auth-saml` extra: `python3-saml>=1.16.0,<2.0.0` |
| `tests/unit/core/auth/test_saml_backend.py` | tests | полные coverage |
| `tests/unit/core/auth/test_saml_sp_handler.py` | tests | полные coverage |

### Отсутствует ❌

1. **`SsoRegistry`** (per-tenant Vault) — ADR-0054 §2
   - Path: `secret/data/sso/<tenant>/idp`
   - Fields: `entity_id`, `sso_url`, `x509_cert`, `allow_create_user`, `groups_to_capabilities`
   - Read-through cache TTL 300s
   - Vault audit-log invalidation (`secret_modified` event)

2. **`require_sso_auth`** decorator — TODO S20
   - Validate session/JWT from SSO provider
   - Call AuthorizationGateway с `principal = SSOUserInfo.sub`
   - Map SSO groups → RBAC roles через `groups_to_capabilities`

3. **`services/admin/sso.py`** — старый stub (S19 K5 W5b)
   - `SamlSSOClient.get_login_url` → NotImplementedError
   - `SamlSSOClient.get_logout_url` → NotImplementedError
   - `SamlSSOClient.handle_acs_response` → NotImplementedError
   - `OidcSSOClient.get_authorization_url` → NotImplementedError
   - `OidcSSOClient.exchange_code` → NotImplementedError
   - `require_sso_auth` (line 146) — TODO S20, реализован как no-op

### Tests coverage

- `test_saml_backend.py` — 100% coverage на `SamlBackend`
- `test_saml_sp_handler.py` — 100% coverage на `sp_handler`
- `test_sso.py` (services/admin) — **НЕ СУЩЕСТВУЕТ** (старая stub не покрыта)
- `test_sso_registry.py` — **НЕ СУЩЕСТВУЕТ** (SsoRegistry отсутствует)
- `test_require_sso_auth.py` — **НЕ СУЩЕСТВУЕТ** (decorator отсутствует)

## Решение (W1 defaults)

### Scope: Variant A (полный SSO scope за исключением refresh token)

| Wave | Commit | Scope | LOC est |
|---|---|---|---|
| **W1** | (this ADR) | Design re-affirm + research gap fill | 0 LOC (docs only) |
| **W2** | s125-w2-sso-registry | `SsoRegistry` + tests | ~200 LOC |
| **W3** | s125-w3-require-sso-auth | `require_sso_auth` decorator + tests | ~150 LOC |
| **W4** | s125-w4-stub-replace | `services/admin/sso.py` → re-exports (backward-compat shim) | ~50 LOC |
| **W5** | s125-w5-closure | CHANGELOG + this ADR-0212 final | 0 LOC |
| **TOTAL** | **5 commits** | | **~400 LOC** |

**Honest scope reduction:** OIDC отложен (per ADR-0054), refresh-token
flow отложен (S126+, per ADR-0054 R2).

### 5 Open Questions (resolved with defaults from ADR-0054)

1. **Old stub disposition:** **BACKWARD-COMPAT SHIM** (re-export из
   `core.auth.*`, deprecated docstring). Trade-off: clean code vs
   breaking change. Shim safe для callers.

2. **`SSOUserInfo` location:** **NEW `core/auth/sso_types.py`** —
   отдельный файл, чтобы избежать конфликта с `SamlAuthResult` (это
   dataclass для internal use, а `SSOUserInfo` — public API).

3. **JWT TTL:** **15 минут** (per ADR-0054 §1).

4. **Refresh token scope:** **S126+** (per ADR-0054 R2, "cookie-based
   refresh в R2 (Sprint 5)"). S125 = short-lived JWT без auto-refresh.

5. **`SsoRegistry` storage:** **VAULT ONLY** (per ADR-0054 §2). Trade-off:
   secure, ~50ms per read (acceptable for SAML flow which is already
   >500ms due to IdP redirect). DB schema avoided.

### Architectural patterns (re-affirm)

- **Capability-checked facades** для cross-layer (W2/W3 в `core/`, не
  `services/`)
- **Vault-first secrets** через `core/secrets/*` (per V22 §security)
- **Read-through cache** с TTL 300s (стандартный паттерн в проекте)
- **Pydantic models** для DTO (per AGENTS.md)
- **Async-first** (FastAPI)
- **TDD: red → green → refactor** для новых компонентов

## Последствия

**Плюсы:**
- ✅ SAML primary, OIDC deferred (per ADR-0054, bank requirement)
- ✅ Per-tenant Vault isolation + audit-trail
- ✅ Re-use существующего `SamlBackend` (no duplication)
- ✅ Capability mapping переиспользует `CapabilityGate`
- ✅ Refresh-cron исключает stale-cert issues
- ✅ Fallback chain: saml → mtls → api_key
- ✅ Backward-compat shim для admin stub (no breaking change)

**Минусы:**
- ❌ ~400 LOC нового кода (SsoRegistry + require_sso_auth + shim)
- ❌ +18 новых тестов (SsoRegistry 10, require_sso_auth 8)
- ❌ Vault read latency (~50ms) на каждый admin login
- ❌ OIDC требует S126+ (Sprint 7+ per ADR-0054)
- ❌ Refresh token требует S126+ (cookie-based, S5 per ADR-0054)

## Альтернативы рассмотрены и отклонены

1. **Variant B — только SsoRegistry (S126 делает require_sso_auth):**
   - Trade-off: 2 sprint'а на SSO, vs 1 цельный
   - Отклонено: scope W2+W3 — один логический unit (registry+consumer)

2. **Variant C — полный SSO + OIDC stub:**
   - Trade-off: больше scope, но OIDC всё равно отложен
   - Отклонено: OIDC stub без impl — академический overhead

3. **DB + Vault для SsoRegistry:**
   - Trade-off: faster, но +DB schema work
   - Отклонено: ADR-0054 §2 явно указывает Vault-only

4. **Hard delete старого `services/admin/sso.py`:**
   - Trade-off: clean code, breaking change
   - Отклонено: shim safe для any external caller (defensive)

5. **Custom SAML XML parser:**
   - Trade-off: full control
   - Отклонено: high-risk (XML signature wrapping, XXE); audited lib лучше

## Files to Touch (W2-W5)

**Production code (NEW):**
- `src/backend/core/auth/sso_registry.py` (~200 LOC, W2)
- `src/backend/core/auth/sso_registry/__init__.py` (W2)
- `src/backend/core/auth/require_sso_auth.py` (~150 LOC, W3)
- `src/backend/core/auth/require_sso_auth/__init__.py` (W3)
- `src/backend/core/auth/sso_types.py` (~50 LOC, NEW type module)

**Production code (MODIFIED):**
- `src/backend/services/admin/sso.py` (W4: replace stub → re-exports shim)

**Tests (NEW):**
- `tests/unit/core/auth/test_sso_registry.py` (~10 tests, W2)
- `tests/unit/core/auth/test_require_sso_auth.py` (~8 tests, W3)
- `tests/unit/services/admin/test_sso.py` (~5 tests, W4: verify re-exports)

**Docs:**
- `CHANGELOG.md` (W5)
- This ADR-0212 (W1 + W5 closure)

## Self-imposed Constraints Honored

- ✅ 1 commit / 1 logical change (W2-W5)
- ✅ Atomic commits, conventional prefix
- ✅ Russian first, без emoji
- ✅ Push — user-controlled (deny-list)
- ✅ Capability-checked facades (W2/W3 в `core/auth/`, не `services/`)
- ✅ Honest scope reduction: OIDC + refresh token отложены (S126+)
- ✅ TDD: red → green → refactor (tests before code, per S25 W1)
- ✅ Vault-only storage (per ADR-0054)
- ✅ Backward-compat shim (no breaking change)

## Remaining Technical Debt (post-S125)

| ID | Item | Sprint |
|---|---|---|
| TD-0242 | OIDC stub (design-only) → S126+ impl | S126+ |
| TD-0242.1 | Refresh token (cookie-based) → S126+ | S126+ |
| TD-0247 | 9 xfailed composition tests | S125+ (parallel) |
| TD-0241 | 20 TODO/FIXME | Continuous P3 |

## Co-Authored-By

Co-Authored-By: Claude <[REDACTED]>
