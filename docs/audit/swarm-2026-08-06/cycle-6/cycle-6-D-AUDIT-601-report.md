# Cycle 6 / D-AUDIT-601 — SAML impersonation fix (SECURITY-P0-001)

**Date:** 2026-08-07
**Cycle:** 6 — focused implementation phase
**Task ID:** T-C6-01-SAML-IMP
**Plan ref:** cycle-4 phase-1/02-security.md `SECURITY-P0-001`
**Docstring marker:** `cycle-6/D-AUDIT-601`

---

## 1. Подход

Cycle-4 audit (см. `cycle-4/phase-1/02-security.md` § SECURITY-P0-001) обнаружил
fail-OPEN CVE в `core/auth/auth_selector.py:_verify_saml` (lines 147-167):
любой cookie `saml_session=<anything>` или header `X-SAML-Session-ID=<anything>`
принимался как валидный principal, что давало **impersonation через подделку
cookie** через `AuthRequiredMiddleware`.

В соответствии с заданием выбран **option (b)** — fail-CLOSED через явный
`logger.error` + `raise NotImplementedError("SAML verification not yet wired;
use JWT instead")`. Pattern согласован с cycle-5 T-C5-02 (D-AUDIT-502
SECURITY-P0-002 fix), где `validate_sql` также переведён в
explicit-fail-closed при policy_override. Минимальные изменения: 1 файл
modified, 3 файла added, +23/-7 LOC.

---

## 2. Reproduction (до fix'а)

```python
$ .venv/bin/python -c "
import asyncio
from unittest.mock import AsyncMock
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware

async def fake_receive():
    return {'type':'http.request','body':b'','more_body':False}
async def fake_send(msg): pass

async def main():
    scope = {'type':'http','method':'GET','path':'/api/v1/protected',
             'headers':[(b'cookie', b'saml_session=ATTACKER_FAKE_SESSION_ID')], 'state':{}}
    mw = AuthRequiredMiddleware(app=AsyncMock())
    await mw(scope, fake_receive(), fake_send)
    auth = scope.get('state', {}).get('auth')
    print('auth principal:', getattr(auth, 'principal', None) if auth else None)
    print('auth method:', getattr(auth, 'method', None) if auth else None)
asyncio.run(main())
"
# → auth principal: ATTACKER_FAKE_SESSION_ID
# → auth method: AuthMethod.SAML
# CVE-IMPERSONATION CONFIRMED
```

---

## 3. Fix

`src/backend/core/auth/auth_selector.py` lines 147-167 → fail-CLOSED:

```python
async def _verify_saml(request: Request) -> AuthContext | None:
    """Проверка SAML session (V15 S6) — FAIL-CLOSED.

    ...
    cycle-6/D-AUDIT-601 (SECURITY-P0-001): ранее эта функция принимала
    ЛЮБОЕ значение ``saml_session`` cookie / ``X-SAML-Session-ID``
    header как валидный principal — CVE-уровень impersonation через
    подделку cookie (``auth_selector.py:147-167``). Теперь — fail-CLOSED:
    явный ``logger.error`` + ``NotImplementedError`` (``verify_request``
    оборачивает verifier в ``try/except`` и при исключении движется к
    следующему методу, либо возвращает ``None`` если SAML единственный;
    middleware/``require_auth`` трактует это как 401). Production usage:
    extensions должны настраивать ``SamlBackend`` напрямую через
    ``core/auth/saml_backend.py`` + ``AuthRequiredMiddleware`` с custom
    verifier или переходить на ``AuthMethod.JWT`` до полной реализации
    SP-side session store (cycle-6/D-AUDIT-601 follow-up).
    """
    session_id = request.cookies.get("saml_session") or request.headers.get(
        "X-SAML-Session-ID"
    )
    if not session_id:
        return None
    # cycle-6/D-AUDIT-601: SAML verification not yet wired in
    # core/auth/auth_selector.py — reject unvalidated session_id
    # to prevent impersonation (CVE).
    logger.error(
        "SAML verification not wired in core auth_selector "
        "(cycle-6/D-AUDIT-601 SECURITY-P0-001); rejecting unvalidated "
        "session_id to prevent impersonation. Use JWT or wire "
        "SamlBackend via core/auth/saml_backend.py."
    )
    raise NotImplementedError("SAML verification not yet wired; use JWT instead")
```

### Flow после fix'а

1. Anon client → `Cookie: saml_session=ATTACKER` → `AuthRequiredMiddleware`.
2. Middleware вызывает `verify_request(request, methods=[..., SAML, ...])`.
3. `verify_request` перебирает verifiers; для SAML вызывает `_verify_saml`.
4. `_verify_saml` логирует `logger.error("SAML verification not wired...")` +
   raises `NotImplementedError("SAML verification not yet wired; use JWT instead")`.
5. `verify_request` ловит exception в `try/except` (line 258-260) → logs warning
   "verify_request: AuthMethod.SAML raised: ..." → move-on (для комбинированных
   methods) или return None (если SAML — единственный accepted method).
6. Middleware получает `None` → sends 401 JSON через `send`-wrapper (cycle 43
   pure ASGI, no-raise).

---

## 4. Verification (после fix'а)

```python
$ .venv/bin/python -c "
import asyncio
from unittest.mock import AsyncMock
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware

async def fake_receive():
    return {'type':'http.request','body':b'','more_body':False}
async def fake_send(msg): pass

async def main():
    # Test 1: fake SAML cookie
    scope = {'type':'http','method':'GET','path':'/api/v1/protected',
             'headers':[(b'cookie', b'saml_session=ATTACKER')], 'state':{}}
    mw = AuthRequiredMiddleware(app=AsyncMock())
    await mw(scope, fake_receive(), fake_send)
    auth = scope.get('state', {}).get('auth')
    print('Test 1 (fake cookie):  ', getattr(auth, 'principal', None) if auth else None)

    # Test 2: fake X-SAML-Session-ID header
    scope2 = {'type':'http','method':'GET','path':'/api/v1/protected',
              'headers':[(b'x-saml-session-id', b'ATTACKER_HEADER')], 'state':{}}
    await mw(scope2, fake_receive(), fake_send)
    auth2 = scope2.get('state', {}).get('auth')
    print('Test 2 (fake header):  ', getattr(auth2, 'principal', None) if auth2 else None)

    # Test 3: no credentials
    scope3 = {'type':'http','method':'GET','path':'/api/v1/protected',
              'headers':[], 'state':{}}
    await mw(scope3, fake_receive(), fake_send)
    auth3 = scope3.get('state', {}).get('auth')
    print('Test 3 (no creds):     ', getattr(auth3, 'principal', None) if auth3 else None)
asyncio.run(main())
"
# Test 1 (fake cookie):  None  ← REJECTED
# Test 2 (fake header):  None  ← REJECTED
# Test 3 (no creds):     None  ← unchanged behavior
```

---

## 5. Diff stat

```
src/backend/core/auth/auth_selector.py | 30 +++++++++++++++++++++++-------
1 file changed, 23 insertions(+), 7 deletions(-)

NEW: tests/unit/core/auth/test_auth_selector_saml_fail_closed.py    (7 tests)
NEW: tests/unit/services/auth/__init__.py
NEW: tests/unit/services/auth/test_auth_required_saml_impersonation_blocked.py  (4 tests)
NEW: docs/audit/swarm-2026-08-06/cycle-6/cycle-6-D-AUDIT-601-report.md  (this file)
```

**Scope:** 1 modified + 4 added files. 0 deletes. 0 layer violations.
0 docstring missing. uv.lock НЕ тронут. s3.py / blue_green.sh /
gateway_adapter.py:128-129 НЕ тронуты.

---

## 6. Тестовый output (.venv/bin/python)

```
$ .venv/bin/python -m pytest \
    tests/unit/core/auth/test_auth_selector_saml_fail_closed.py \
    tests/unit/services/auth/test_auth_required_saml_impersonation_blocked.py \
    --no-header --tb=no -p no:warnings

tests/unit/core/auth/test_auth_selector_saml_fail_closed.py .......      [ 63%]
tests/unit/services/auth/test_auth_required_saml_impersonation_blocked.py . [ 72%]
...                                                                      [100%]
============================== 11 passed in 0.58s ==============================
```

### Regression suite (auth + security + middleware)

```
$ .venv/bin/python -m pytest \
    tests/unit/core/auth/ \
    tests/unit/services/security/ \
    tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py \
    tests/unit/entrypoints/middlewares/test_api_key_dedup.py \
    tests/unit/services/auth/ \
    --no-header --tb=line -p no:warnings

========================= 1 failed, 316 passed in 6.92s =========================
FAILED tests/unit/core/auth/test_core_logging_codemod.py::test_auth_module_uses_core_logger[src/backend/core/auth/mtls_backend.py]
```

**1 failure** — pre-existing в `mtls_backend.py` codemod (НЕ от cycle-6:
`git stash` + `pytest` до моих правок воспроизводит ту же ошибку).
Pre-existing residual per cycle-5 final report и cycle-4 audit (BASELINE).

**316 passed** — все остальные auth/security/middleware тесты зелёные, включая:
- `tests/unit/core/auth/test_auth_selector_relocation.py` (6 passed)
- `tests/unit/core/auth/test_saml_backend.py` (8 passed)
- `tests/unit/core/auth/saml/test_sp_initiated.py` (6 passed)
- `tests/unit/services/security/` (8 passed)
- `tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py` (~15 passed)

---

## 7. Gates

| Gate | Status | Detail |
|---|---|---|
| Layer checker | **PASS** | `.venv/bin/python tools/check_layers.py --root src` → `Нарушений: 0 новых (файлов: 2278; baseline: 175 legacy)` |
| Docstring gate | **PASS** | `make check-docstrings MAX_ALLOWED=0` → `Total: 0 missing docstrings in 0 files` |
| Security allowlist | **PASS** | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` → `27` (≤27) |
| uv.lock churn | **PASS** | `git diff uv.lock` → `-16/+1` (PRE-EXISTING concurrent work, не от cycle-6) |
| s3.py untouched | **PASS** | `git status --short -- src/backend/infrastructure/storage/s3.py` → пусто |
| blue_green untouched | **PASS** | `git status --short -- tools/blue_green.sh tests/unit/tools/test_blue_green_switch.py` → пусто |
| gateway_adapter:128-129 untouched | **PASS** | `git status --short -- src/backend/services/ai/gateway_adapter.py` → пусто |
| preflight | **PRE-EXISTING FAIL** | `working tree 40 entries (pre-existing concurrent work: providers/ai.py, admin_cron.py, agent_memory.py и др. modified + cycle-4/cycle-5 docs untracked)` + `uv.lock churn 45 lines (pre-existing -16/+1 от concurrent work)`. **Heads-up**: не от cycle-6 правок. |

### preflight exit code

`bash tools/cycle-1-preflight.sh` exit = **1** (PRE-EXISTING state).

Из 5 проверок preflight:
- ✅ layer checker — 0 new, 175 legacy
- ✅ allowlist active IDs — 27
- ✅ docstring gate — 0 missing
- ❌ working tree — 40 entries (PRE-EXISTING concurrent work)
- ❌ uv.lock churn — 45 lines (PRE-EXISTING concurrent work, `-16/+1`)
- ✅ s3.py untouched — не modified

**Подтверждение pre-existing**: `git stash` (с моими правками) + re-run preflight
на чистом HEAD = те же 2 FAIL (working tree 19 entries, uv.lock -16/+1).

---

## 8. Что НЕ затронуто (per task constraints)

- ❌ `uv.lock` — не тронут (churn -16/+1 pre-existing)
- ❌ `.security/pip-audit-allowlist.txt` — не тронут (27 active CVE)
- ❌ `src/backend/infrastructure/storage/s3.py` — не тронут
- ❌ `tools/blue_green.sh` — не тронут
- ❌ `tests/unit/tools/test_blue_green_switch.py` — не тронут
- ❌ `src/backend/services/ai/gateway_adapter.py:128-129` — не тронут
  (residual `except Exception: pass` сохранён per task instruction)
- ❌ cycle 1+2+3+4+5 правки — не переписаны:
  - T-1.1 composition root — untouched
  - T-1.5 policy_mixin dual signature — untouched
  - T-1.5 gateway_adapter AIGatewayProductionWiringError — untouched
  - T-W1-01 AuthValidate fail-closed — untouched
  - T-W1-01 AuthenticationProviderUnavailableError — untouched
  - T-3.1 _InMemoryJwtBlacklist TTLCache — untouched
  - T-C5-02 validate_sql NotImplementedError — untouched
    (`services/agent_security/facade.py:121+`)
  - cycle-1 auth_selector shim → deprecation — untouched
    (`entrypoints/api/dependencies/auth_selector.py`)
- ❌ Pre-existing `except Exception` без concrete handling — НЕ удалены
  (residual в `gateway_adapter.py:128-129` per task instruction; cycle-5 DLQ
  pattern в `_dlq_helper.py` сохранён).

---

## 9. Honest verdict

Минимальный fix (1 файл modified + 3 файла added, +23/-7 LOC) закрывает
**CVE-уровневую fail-OPEN уязвимость** SAML impersonation. Pattern согласован
с cycle-5 (T-C5-02 SECURITY-P0-002 `validate_sql` → explicit NotImplementedError)
и минимизирует blast radius:

1. SAML-routes в extensions получат 401 (deny) — fail-CLOSED.
2. JWT-routes и другие verifier'ы продолжают работать (verify_request
   catch'ит NotImplementedError в try/except и move-on).
3. Production observability: `logger.error` эмитит structured marker
   `cycle-6/D-AUDIT-601 SECURITY-P0-001` для SOC dashboard.
4. Follow-up задокументирован в docstring: extensions должны либо перейти
   на `AuthMethod.JWT`, либо wire `SamlBackend` напрямую через
   `core/auth/saml_backend.py` + `AuthRequiredMiddleware` с custom verifier
   до полной реализации SP-side session store.

**Не достигнуто** (organic, вне scope atomic-fix):
- Полная реализация SP-side session store (Redis/in-memory) с TTL +
  per-request revocation (cycle-4 P4-002).
- `AuthMethod.OIDC` (cycle-4 P4-001, separate organic feature).

**Score impact**: cycle-4 readiness 02-security = 0/100. С закрытием ещё
2 P0 (SECURITY-P0-001 здесь + SECURITY-P0-002 в cycle-5) score uplift
сохраняется cap'ом (P0 в security остаётся: SECURITY-P0-003 defusedxml,
SECURITY-P1-001 AIGatewayProductionWiringError dead path, SECURITY-P1-002
sync _casbin_check dead path). Score остаётся ≤ 79 до закрытия всех P0.

---

*Cycle-6 D-AUDIT-601 report. HEAD: `4b5831e4` (cycle-5 final) + cycle-6
minimal diff. 11 new tests, 1 file modified, 0 layer/docstring/allowlist/
uv.lock violations introduced.*