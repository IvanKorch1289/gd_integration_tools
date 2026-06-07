# ADR-0085 — User Auth: LDAP as Primary, Password Deprecated

**Status:** Accepted
**Date:** 2026-06-07
**Authors:** K3
**Sources:** S58 W6 (User service → auth integration), v22 final report, K1 S6 W1 (AdDirectoryClient)
**Supersedes:** N/A (new ADR; resolves "password vs LDAP" open question)

---

## Context

Pre-S58 (K1 S6 W1, 2024) в проекте появился `AdDirectoryClient` (тонкий async-фасад над `ldap3`) с методами `validate_credentials`, `find_user`, `get_user_groups`. Использовался в паре с `SamlBackend` для SSO: после SAMLResponse получали principal (NameID/email), AD клиент resolve'ил группы и attribute'ы для RBAC.

Pre-S58 UserService использовал **только password-based auth** (`User.verify_password()` + argon2 хеш). Проблемы:
* не масштабируется на SSO-only deployments (где LDAP primary);
* password хранение → blast radius при DB breach;
* в roadmap (S59+) LDAP — primary auth (per K1 плану); password устарел.

User запросил (S58 W6): расширить User service для поддержки LDAP auth с auto-provisioning, дать фронту toggle для enable/disable LDAP, пометить password как deprecated (но НЕ удалять — может пригодиться в будущем).

## Decision

**1. Unified login через POST /auth/login (single endpoint, method dispatch).**

Front выбирает auth method в body:
```json
{"method": "ldap", "username": "alice@example.com", "password": "..."}
{"method": "password", "username": "alice", "password": "..."}
```

Endpoint dispatch'ит в `UserService.login_with_method(method, ...)` → `_login_password()` или `_login_ldap()`.

**2. LDAP config — single global (env vars / settings.yaml), per-design S58 W6.**

Не per-tenant: в проекте один prod LDAP сервер, multi-tenant LDAP — separate feature (S59+). Конфиг в `LdapSettings` (Pydantic, env prefix `LDAP_`).

**3. Auto-provisioning local User при первом успешном LDAP bind.**

При успешном `validate_credentials(ad_user.dn, password)`:
* `find_user(username)` → если local User есть → sync attrs (email, first_name, last_name);
* если нет → создаём локальный User (без password — LDAP-only).

Username extraction priority: `sAMAccountName` → `userPrincipalName` (strip domain) → `cn` → first CN из DN.

**4. Front toggle — GET /auth/methods (без auth, вызывается до login).**

Response: `{methods: ["password", "ldap"], ldap_enabled: bool, default_method: "ldap"}`.

Source: `feature_flags.saml_ad_login_enabled` (Sprint 6, default OFF) AND `LdapSettings.is_configured()`.

**5. Password auth — DEPRECATED, но РАБОТАЕТ.**

`UserService.login()` (legacy) → `DeprecationWarning` при вызове. `User.set_password()` остаётся (для admin-флоу). Будет удалён когда фронт полностью перейдёт на LDAP (S59+).

## Архитектура

```
┌─────────────┐
│   Front     │  GET /auth/methods → "ldap" enabled
│  (Streamlit)│
└──────┬──────┘
       │ POST /auth/login {method: "ldap", username, password}
       ▼
┌──────────────────────────────────────┐
│ POST /auth/login (auth_login.py)     │
│   ↓                                  │
│ UserService.login_with_method(...)   │
│   ├─→ _login_password() [DEPRECATED] │
│   └─→ _login_ldap()                  │
│         ├─ get_ad_client() factory   │
│         │   ├─ feature flag check    │
│         │   ├─ ldap_settings check   │
│         │   └─ AdDirectoryClient     │
│         │       ├─ find_user()       │
│         │       └─ validate_creds()  │
│         └─ _provision_ldap_user()    │
│             ├─ get_by_username()     │
│             └─ add() if not exists   │
│                                      │
│ On success: jwt_backend_joserfc.encode │
└──────────────────────────────────────┘
```

## Файлы (S58 W6)

| Файл | LOC | Назначение |
|---|---|---|
| `src/backend/core/config/services/ldap.py` | 110 | `LdapSettings` (Pydantic) + singleton `ldap_settings` |
| `src/backend/core/auth/ldap_client_factory.py` | 130 | `get_ad_client()` factory + singleton cache |
| `extensions/core_entities/users/services/users.py` | +250 | `login_with_method`, `_login_ldap`, `_provision_ldap_user`, deprecation warnings |
| `src/backend/entrypoints/api/v1/endpoints/auth_login.py` | 175 | `POST /auth/login` endpoint |
| `src/backend/entrypoints/api/v1/endpoints/auth_methods.py` | 130 | `GET /auth/methods` endpoint (front toggle) |
| `src/backend/entrypoints/api/v1/routers.py` | +12 | Router registration |
| `docs/adr/0085-user-auth-ldap-integration.md` | (this) | ADR |

**Total: ~800 LOC, no production code removed (password deprecation only).**

## Альтернативы Evaluated

| Подход | Trade-offs | Decision |
|--------|-----------|----------|
| **Two endpoints (POST /auth/login/password + POST /auth/login/ldap)** | Cleaner separation, но front должен знать какой endpoint вызывать → не масштабируется на новые methods (OAuth, WebAuthn) | ❌ Rejected (doesn't scale) |
| **Front reads config + decides method server-side** | Single endpoint, но сервер не знает какой method пробует front → server picks wrong fallback | ❌ Rejected (less explicit) |
| **Single endpoint with method in body (chosen)** | Explicit, scalable (новые methods добавляются как новые enum values), front имеет полный контроль | ✅ **Selected** |
| **Drop-in замена password на LDAP (force migration)** | Слишком агрессивно: ломает существующие deployments, нет rollback path | ❌ Rejected (too risky) |
| **Remove password полностью** | User сказал "не убирай авторизацию по LDAP, в будущем может пригодиться" → password остаётся как fallback | ❌ Rejected (user instruction) |
| **Auto-provisioning (chosen) vs require pre-provisioning** | Auto-provision = меньше admin overhead, LDAP-provisioned users сразу работают; trade-off: менее строгий access control (любой с LDAP credentials = local user) | ✅ **Selected** (admin can disable user локально если нужно) |

## Open Items / S59+

- **Multi-tenant LDAP** (per-tenant `AdServerConfig`): если разные тенанты используют разные AD — выделить `LdapSettings` → `TenantLdapConfig` per tenant.
- **OAuth2/OIDC auth method**: добавить `method: "oidc"` в `AuthMethodLiteral` + соответствующий `_login_oidc()`. Pattern одинаковый.
- **WebAuthn/passkeys**: FIDO2 auth для passwordless experience (вместо LDAP).
- **Password removal** (когда фронт готов): удалить `UserService.login()` (legacy), `User.set_password()` (если не нужен admin-флоу). DEPRECATED label даёт ~6-12 months migration window.
- **Group sync**: при LDAP login — pull `memberOf` → map к local roles (admin / user). НЕ реализовано в S58 W6 (только provisioning).
- **Audit trail**: continuum version row (S58 W1) уже работает на User — каждый `update()` (sync attrs) → version row. Полный audit chain для security review.
- **Rate limiting**: login endpoint не имеет rate limit в S58 W6 → brute-force risk. Open для S59+ (Redis-based limiter).
- **CSRF / CORS** на POST /auth/login: настраивается в middleware, не endpoint-specific.

## Relation to Other ADRs

- **ADR-0057** (Pure ASGI Middleware Chain): login endpoint — в v1 router, не в middleware (нет pre/post processing кроме JWT issuance)
- **ADR-0061** (allowlist): `feature_flags.saml_ad_login_enabled` — глобальный allowlist для LDAP endpoint (off by default)
- **K1 S6 W1** (AdDirectoryClient): thin async wrapper — переиспользован в `get_ad_client()` factory
- **S58 W1** (Versioning DSL): User model уже versioned — каждый `update()` (auto-provisioned sync attrs) → version row
- **S58 W2** (typer+rich): НЕ применён к `auth_login` (это FastAPI endpoint, не CLI tool)
- **S58 W3** (ADR-0083, ADR-0084): этот ADR (0085) — продолжение S58 design discussion

## Verification

```bash
# 1. LDAP settings load
python -c "
from src.backend.core.config.services.ldap import ldap_settings
print('configured:', ldap_settings.is_configured())
"

# 2. AD factory respects feature flag
python -c "
from src.backend.core.auth.ldap_client_factory import get_ad_client
client = get_ad_client(feature_flag_enabled=False)
assert client is None, 'must be None when feature flag is False'
print('OK: factory respects feature flag')
"

# 3. Endpoints registered
python -c "
from src.backend.entrypoints.api.v1.routers import get_v1_routers
r = get_v1_routers()
routes = [route.path for route in r.routes]
assert '/auth/login' in routes or any('/auth/login' in p for p in routes), 'login endpoint missing'
assert any('/auth/methods' in p for p in routes), 'methods endpoint missing'
print('OK: endpoints registered')
"
```
