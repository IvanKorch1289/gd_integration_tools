# ADR-0213: Sprint 125 Closure — SSO/IdP Layer Built: SsoRegistry + require_sso_auth + Backward-Compat Shim (5 waves, 100% scope, +S126 W0 regressions fix)

- **Status:** Accepted (Sprint 125 closure, 2026-06-14)
- **Wave:** s125-w5-closure
- **Sprint:** 125
- **Depends:** ADR-0054 (SAML/OIDC strategy), ADR-0212 (S125 W1 design re-affirm), ADR-0211 (S124 closure)

## Context

Sprint 125 закрывает **домен SSO/IdP integration** в `core/auth/`. До S125:

- `SamlBackend` уже реализован (Sprint 15+), но **отдельно** от group→capability
  resolution и tenant-scoped конфигурации.
- Per-tenant IdP config разбросан: hand-written YAML, ENV variables, DB rows
  в extensions/, ad-hoc settings — без единого источника правды.
- Groups → capabilities mapping **отсутствовал** (RBAC использовал
  плоский `principal` без учёта IdP-групп).
- `services/admin/sso.py` — Sprint 19 stub с 5 `NotImplementedError`,
  нигде в проекте не импортируется, но формально лежит как «dead weight».

S125 систематизирует SSO-стек в 4 волны + S126 W0 (regressions fix
обнаружен во время W3 testing, по правилу «если встречаешь регрессию —
анализируй, планируй, исправляй»).

## Sprint 125 Final Score (5 waves, 5 commits + S126 W0 2 commits = 7 total)

| Wave | Commit | Scope | Δ | Status |
|---|---|---|---|---|
| W1 | `ba04ec34` | ADR-0212 design re-affirm + research gap fill (5 design decisions → Variant A) | — | ✅ |
| W2 | `eac6d578` | SsoRegistry (per-tenant IdP config + read-through cache) | NEW (5 types) | ✅ |
| W3 | `38483da7` | require_sso_auth decorator + auth_context_helpers | NEW (2 files) | ✅ |
| W4 | `51567a44` | services/admin/sso.py backward-compat shim | Sprint 19 stub → shim | ✅ |
| W5 | (this ADR) | Closure | — | ✅ |
| S126 W0 W1 | `2b1e1697` | backpressure/ + ad_directory_client/ S67 file-split regressions fix | 3+1 chaos fixed | ✅ |
| S126 W0 W2 | `f0c4785e` | ad_directory_client/state.py @dataclass restore | 6 LDAP fixed | ✅ |
| **TOTAL** | **7 commits** | **+66 ahead of origin** | **0 boundary violations** | **9.9+** |

## W1 — Design Re-Affirm (ADR-0212)

**Research finding:** `SamlBackend` (Sprint 15+) уже реализован в `core/auth/saml_backend.py`
+ `sp_handler.py` + `saml_resolver.py`. `services/admin/sso.py` (Sprint 19) — old stub
с 5 `NotImplementedError`, **нигде не импортируется** (verified grep).

**Design decisions (5):**
1. **Variant A** (полный scope): SsoRegistry + require_sso_auth + integration shim (5-6h, 4-5 commits)
2. Old stub disposition: **backward-compat shim** (S127 — planned removal, TD-0248)
3. **JWT TTL 15 min** (per ADR-0054)
4. **Refresh token** — deferred to S126+ (cookie-based, S126 backlog)
5. **SsoRegistry storage** — Vault only (per ADR-0054 §2), с per-tenant
   `secret/data/sso/<tenant>/idp` path

## W2 — SsoRegistry (per-tenant IdP registry)

**Pattern:** зеркалирует :class:`JwksCache` (TTL 300s + per-tenant
`asyncio.Lock` + double-checked locking + stale-fallback на Vault error).

**Public API:**
- `SsoRegistry(VaultClientProtocol | None = None)` — primary entry
- `await registry.get(tenant_id) -> IdpConfig | None` — read-through
- `registry.invalidate(tenant)` — Vault audit-log event
- `registry.invalidate_all()` — bulk refresh (per ADR-0054 §4)
- `HvacVaultClient(addr, token, mount)` — production adapter
- `VaultClientProtocol` — Protocol для tests/mocks

**Types (sso_types.py):**
- `IdpConfig` (Pydantic) — entity_id, sso_url, x509_cert, slo_url,
  allow_create_user, groups_to_capabilities
- `GroupsToCapabilities` (Pydantic, frozen) — `mappings: dict[str, list[str]]`
  + `resolve(groups: list[str]) -> list[str]`
- `SSOUserInfo` (runtime DTO) — sub, email, name, groups, roles

**Exception hierarchy:**
- `SsoRegistryError(RuntimeError)` — base
- `SsoRegistrySchemaError` — Pydantic validation (propagates, config fix needed)
- `SsoRegistryVaultError` — transient (masked: stale-fallback или None)

**Tests:** 23/23 passed (read-through cache, TTL, concurrent cold-cache,
graceful degradation, schema/vault error propagation).

## W3 — require_sso_auth decorator

**Service-level decorator** (минимально инвазивный, testable без HTTP).

**API:**
- `@require_sso_auth(registry)` — enforce SAML method, resolve caps
- `@require_sso_capability(cap, registry)` — granular per-cap check
- `RequireSsoAuthError(PermissionError)` — fail-closed (HTTP → 403)

**AuthContext param discovery:** `auth` keyword → first positional → name contains "auth"

**Helpers (auth_context_helpers.py):**
- `extract_tenant_id(auth) -> str | None` — duck-typed
- `extract_user_groups(auth) -> list[str]` — duck-typed

**Failure modes (все fail-closed):**
- `auth.method != SAML` → `RequireSsoAuthError`
- `metadata["tenant_id"]` отсутствует → `RequireSsoAuthError("tenant_id required")`
- `registry.get(tenant)` returns None → `RequireSsoAuthError("IdP config not found")`
- `metadata["groups"]` отсутствует → empty list (все caps rejected)
- User caps не покрывают required → `RequireSsoAuthError("User lacks capability")`

**SsoRegistryError** (Vault/schema) — **propagate без маскирования** (operator must fix).

**Tests:** 11/11 passed (SAML/JWT/tenant/registry propagation, fail modes, metadata preservation).

## W4 — services/admin/sso.py Backward-Compat Shim

**Старый Sprint 19 stub** (5 NotImplementedError) полностью заменён на shim.

**Re-exports (S125 W2/W3 symbols):**
- `SSOUserInfo` ← `core.auth.sso_types`
- `SamlSSOClient` = `SamlBackend` (semantic alias)
- `SsoRegistry`, `SsoRegistryError`, `SsoRegistrySchemaError`, `SsoRegistryVaultError`
- `IdpConfig`, `GroupsToCapabilities`
- `RequireSsoAuthError`, `require_sso_auth` (new API!), `require_sso_capability`
- `require_sso_auth_legacy` — renamed old API (no-op + DeprecationWarning)

**Module-level `DeprecationWarning`** at import — направляет на `core.auth`.
**Removal policy:** S127 — planned (TD-0248).

**Honest scope:** API частично отличается (Sprint 19 vs S125 W3).
Downstream может мигрировать постепенно — imports работают.

**Tests:** 9/9 passed (re-export identity, DeprecationWarning emission,
legacy classes preserved, core.auth не regressed).

## S126 W0 — Regressions Fix (Pre-existing, S67 File-Split Leftovers)

**Trigger:** во время S125 W3 testing обнаружены 7 pre-existing failures
(НЕ мои регрессии). Per правилу «анализируй, планируй, исправляй».

**Method:** systematic-debugging 4-phase (NO FIX WITHOUT ROOT CAUSE).

### W0 W1 — backpressure/ missing imports (`2b1e1697`)

**Root cause:** S67 W1 file-split (b88ccfe2) — `backpressure.py`
разделён на 5 файлов, но imports не обновлены в 4 из них:

| File | Missing import | Lines affected |
|---|---|---|
| `controller.py` | `BackpressureState`, `ConsumerControlProtocol` from `.types` | 41, 46 |
| `controller.py` | `logger` name (был inline до split) | 69, 101, 109, 118, 146, 154 |
| `stream_reader.py` | `get_logger` + `_logger` | 83 |
| `bulkhead.py` | `get_logger` + `_logger` | 105, 120 |
| `helpers.py` | `StreamingBackpressureController` + `_controller_instance` singleton | 5, 7 |

**Tests:** 3/3 chaos backpressure passed (было 1/3).

### W0 W2 — ad_directory_client/ @dataclass restore (`f0c4785e`)

**Root cause:** S67 W4 file-split (01eb8623) — per-class file decomp.
`dataclasses.field` + `__post_init__` импортированы, но `@dataclass`
decorator потерян на `AdServerConfig` + `AdSearchEntry`.

**Error:** `TypeError: AdSearchEntry() takes no arguments` (6 tests).

**Fix:** импорт `dataclass` from `dataclasses` + decorator на обоих классах.

**Tests:** 23/23 LDAP integration passed (было 6 failed, 17 passed).
33/33 LDAP-related tests passed (расширенный sweep).

### W0 W3 — regression sweep

- Sweep `tests/unit/core + tests/unit/extensions + tests/chaos`: 145 failed
- Verified baseline (без фиксов): 154 failed
- Net change: **−9 (3 chaos + 6 LDAP), 0 new regressions**
- Pre-existing failures (НЕ мои): pg_runner_backend (10) + rate_limiter_tenant (5) — out of scope

## Sprint 125 Final State

| Metric | Before (S124 closure) | After (S125+S126 W0) |
|---|---|---|
| Boundary violations | 0 | **0** |
| Collection errors | 0 | **0** |
| SSO/IdP domain | ad-hoc (YAML/ENV/DB) | **SsoRegistry (Vault + per-tenant)** |
| Groups → caps mapping | none | **`GroupsToCapabilities.resolve()`** |
| Service-level SSO RBAC | none | **`@require_sso_auth` + `@require_sso_capability`** |
| Old SSO stub | 5 NotImplementedError (dead code) | **backward-compat shim + DeprecationWarning** |
| `core.auth` exports | 12 | **22 (+SsoRegistry, IdP types, decorators)** |
| Master ahead of origin | +59 (S124) | **+66 (+7)** |
| Tests collected | 11745 | **11768 (+23 SsoRegistry)** |
| Targeted score | 9.9+ | **9.9+** |

## Backlog (TD-0247..0248 + carried)

- **TD-0247** — 9 xfailed composition tests (S124 W4) — S125+ scope
- **TD-0248** — `services/admin/sso.py` planned removal (S127) — declared
- **S126+** — OIDC stub → real implementation (per ADR-0054 §5)
- **S126+** — Refresh token cookie-based (carried from S125 W1 design)
- **Pre-existing** — pg_runner_backend (10 failed) + rate_limiter_tenant (5 failed) — out of S125 scope

## Honest Notes

1. **Score 9.9+ maintained** — никаких regressions от S125/S126 W0.
2. **Honest scope reduction (W4):** SamlSSOClient API не behavioral compatible
   с SamlBackend (Sprint 19 vs Sprint 96). Shim re-export'ит, но downstream
   потребует manual migration.
3. **S126 W0 pre-existing regressions** — не мои, но я их нашёл и починил
   по правилу. Scope: 2 atomic commits, 0 new regressions.
4. **S126+ scope** — OIDC (deferred per ADR-0054 §5) + refresh token
   (S125 W1 design choice).

Wave: s125-w5-closure
