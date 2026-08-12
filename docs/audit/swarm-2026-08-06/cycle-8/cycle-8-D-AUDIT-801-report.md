# cycle-8 / D-AUDIT-801 — T-C8-01-ADMIN-FAILOPEN

**Task:** re-verify AdminService._authorize fail-CLOSED (cycle-4 phase-1/03-services.md SERV-P0-002)
**Status:** ✅ **RESOLVED upstream** — cycle-1 fix already applied (D-AUDIT-A3-01, commit `da9d6173`)
**Cycle-8 diff:** 1 file, +7 LOC (docstring marker only — logic preserved)

---

## Findings

The "silent return True при gateway unavailable" failure mode described in
the task brief (referencing cycle-4 PHASE-2-SUMMARY.md SERV-P0-002 and
cycle-4 phase-1/03-services.md:87,155) was already resolved in cycle 1:

```
$ git show --stat da9d6173 -- src/backend/services/admin/api.py
 commit da9d617320db52d347132561de46d3efe6ce2332
 Author: Kimi Code <kimi@local>
 Date:   Fri Aug 7 09:48:30 2026 +0300

     fix(security): admin AuthZ fail-CLOSED по умолчанию

     D-AUDIT-A3-01 fix (cycle 1, P0): AdminService._authorize silent fail-OPEN —
     если AuthorizationGateway unavailable (composition root не подключён),
     log warning + return (allow action). Это privilege-escalation vector
     при AuthZ outage.

     Фикс в src/backend/services/admin/api.py:
     - fail-CLOSED by default: raise AdminAuthorizationError + emit audit event
       с outcome='denied'.
     - Opt-in fail-OPEN только через ADMIN_AUTHZ_FAIL_OPEN=true env var
       (для dev_light без AuthZ composition root).
     - logger.critical вместо logger.warning для observability.
```

`da9d6173` is an ancestor of current HEAD (`f06d7856`):

```
$ git merge-base --is-ancestor da9d6173 HEAD && echo "da9d6173 IS in HEAD"
da9d6173 IS in HEAD
```

---

## Runtime verification (cycle-8 / D-AUDIT-801)

The "Real evidence" (silent return True) at lines 97-102 was the cycle-4 state.
Current `src/backend/services/admin/api.py:97-129` implements:

```python
authz = self._get_authz()
if authz is None:
    # ... D-AUDIT-A3-01 fix (cycle 1): fail-CLOSED by default для admin actions.
    import os
    fail_open = os.getenv("ADMIN_AUTHZ_FAIL_OPEN", "").lower() in {
        "1", "true", "yes",
    }
    if fail_open:
        logger.warning("AuthZ unavailable for %s@%s/%s — allowing ...", ...)
        return
    logger.critical("AuthZ unavailable for %s@%s/%s — DENYING ...", ...)
    emit_admin_action(
        actor=actor, action=action, resource=resource,
        outcome="denied", details={"reason": "authz_unavailable"},
    )
    raise AdminAuthorizationError(
        f"AuthorizationGateway unavailable for {actor} on {resource}/{action} "
        "(fail-CLOSED; set ADMIN_AUTHZ_FAIL_OPEN=true for dev_light)"
    )
```

**Direct assertion** (gateway=None + `ADMIN_AUTHZ_FAIL_OPEN` unset):

```
$ .venv/bin/python -c "
import asyncio, os
async def main():
    from src.backend.services.admin.api import AdminService, AdminAuthorizationError
    os.environ.pop('ADMIN_AUTHZ_FAIL_OPEN', None)
    svc = AdminService()
    svc._get_authz = lambda: None
    try:
        await svc._authorize(actor='test', resource='admin.feature_flag:write', action='write')
        print('REGRESSION')
    except AdminAuthorizationError as e:
        print(f'OK: gateway=None → AdminAuthorizationError (fail-CLOSED)')
exit(asyncio.run(main()))
"
AuthZ unavailable for test@admin.feature_flag:write/write — DENYING (fail-CLOSED, ADMIN_AUTHZ_FAIL_OPEN not set)
OK: gateway=None → AdminAuthorizationError (fail-CLOSED)
```

Confirmed: `logger.critical` message + `AdminAuthorizationError` raised,
**NOT silent True**.

---

## Tests (10/10 PASS)

```
$ .venv/bin/python -m pytest tests/unit/services/admin/ -v
============================= test session starts ==============================
collected 10 items

tests/unit/services/admin/test_authz_fail_closed.py::TestAdminAuthZFailClosed::test_fail_closed_when_authz_unavailable PASSED [ 10%]
tests/unit/services/admin/test_authz_fail_closed.py::TestAdminAuthZFailClosed::test_fail_open_with_explicit_env_opt_in PASSED [ 20%]
tests/unit/services/admin/test_authz_fail_closed.py::TestAdminAuthZFailClosed::test_fail_open_with_env_value_1 PASSED [ 30%]
tests/unit/services/admin/test_authz_fail_closed.py::TestAdminAuthZFailClosed::test_fail_open_env_false_does_not_activate PASSED [ 40%]
tests/unit/services/admin/test_authz_fail_closed.py::TestAdminAuthZFailClosed::test_authorize_succeeds_when_authz_available PASSED [ 50%]
tests/unit/services/admin/test_sqladmin_setup.py::test_admin_package_importable PASSED [ 60%]
tests/unit/services/admin/test_sqladmin_setup.py::test_sqladmin_setup_module_importable PASSED [ 70%]
tests/unit/services/admin/test_sqladmin_setup.py::test_register_admin_returns_none_when_legacy_fails PASSED [ 80%]
tests/unit/services/admin/test_sqladmin_setup.py::test_register_admin_calls_legacy_setup PASSED [ 90%]
tests/unit/services/admin/test_sqladmin_setup.py::test_register_admin_attaches_extra_views_when_admin_present PASSED [100%]

============================== 10 passed in 0.77s ==============================
```

The 5 `test_authz_fail_closed.py` tests cover:

1. `test_fail_closed_when_authz_unavailable` — gateway=None + no env → `AdminAuthorizationError` ✓
2. `test_fail_open_with_explicit_env_opt_in` — `ADMIN_AUTHZ_FAIL_OPEN=true` → silent allow (dev_light) ✓
3. `test_fail_open_with_env_value_1` — `ADMIN_AUTHZ_FAIL_OPEN=1` → silent allow ✓
4. `test_fail_open_env_false_does_not_activate` — `ADMIN_AUTHZ_FAIL_OPEN=false` → fail-CLOSED ✓
5. `test_authorize_succeeds_when_authz_available` — AuthZ available + allow → happy path ✓

---

## Cycle-8 change (minimal — docstring marker only)

Per task constraint "Cycle 1+2+3+4+5+6+7 правки НЕ переписывать", the cycle-1
logic was preserved verbatim. The only cycle-8 change is a `D-AUDIT-801`
docstring marker added to `_authorize` for audit-trail continuity.

`git diff HEAD~1 src/backend/services/admin/api.py`:

```diff
@@ -90,6 +90,13 @@ class AdminService:
         """
         Check authorization via AuthorizationGateway.

+        D-AUDIT-801 fix (cycle 8): re-verify fail-CLOSED по умолчанию (cycle-1 fix
+        D-AUDIT-A3-01, commit ``da9d6173``). Cycle-4 phase-1/03-services.md
+        SERV-P0-002 silent fail-OPEN vector ЗАКРЫТ: gateway=None →
+        :class:`AdminAuthorizationError` (НЕ silent ``True``). Opt-in fail-OPEN
+        только через ``ADMIN_AUTHZ_FAIL_OPEN=true`` (для dev_light без AuthZ
+        composition root). Тесты: ``tests/unit/services/admin/test_authz_fail_closed.py``.
+
         Raises:
             AdminAuthorizationError: если AuthZ deny (fail-closed).
         """
```

7 lines added, 0 removed. No logic, no signature, no API changes.

---

## Forbidden files — UNTOUCHED

| File | Constraint | Status |
|---|---|---|
| `uv.lock` | no new lines | UNTOUCHED (preflight OK, 0 churn) |
| `.security/pip-audit-allowlist.txt` | count ≤ 27 | UNTOUCHED (preflight OK, 27) |
| `src/backend/infrastructure/storage/s3.py` | do not modify | UNTOUCHED (preflight OK) |
| `tools/blue_green.sh` | do not modify | UNTOUCHED |
| `tests/unit/tools/test_blue_green_switch.py` | do not modify | UNTOUCHED |
| `src/backend/services/ai/gateway_adapter.py:128-129` | pre-existing residual | UNTOUCHED |

---

## Gates

| Gate | Result |
|---|---|
| Layer checker | 175/0 (0 new, 175 legacy) — **OK** |
| Allowlist active IDs | 27 — **OK** |
| Docstring gate (`make check-docstrings MAX_ALLOWED=0`) | 0 missing (840 files scanned) — **OK** |
| `tests/unit/services/admin/` | 10/10 PASS — **OK** |
| `uv.lock` new lines | 0 — **OK** |
| `s3.py` modified | no — **OK** |
| Working tree entries | 49 (pre-existing concurrent agents + my commit) — informational |
| `git diff --stat HEAD` shows my source file | ✓ `src/backend/services/admin/api.py \| 7 ++` |

---

## Commit

```
$ git show --stat HEAD
commit d9485cf89c0ad9a1def74d274c09f61dfc13c702
Author: Kimi Code <kimi@local>
Date:   Fri Aug 7 14:35:27 2026 +0300

    fix(cycle-8): D-AUDIT-801 — re-verify AdminService._authorize fail-CLOSED (docstring marker)
    [...]

 src/backend/services/admin/api.py | 7 +++++++
 1 file changed, 7 insertions(+)
```

Atomic, single-file, revert-able. Cycle-1+2+3+4+5+6+7 правки НЕ переписаны.

---

## Outcome

SERV-P0-002 closed. The P0 privilege-escalation vector при AuthZ outage was
closed in cycle 1 (commit `da9d6173`); cycle 8 adds audit-trail continuity
(docstring marker `cycle-8/D-AUDIT-801`) and runtime re-verification. No
regression, no logic change, no new dependency, no new tests needed (5 cycle-1
regression tests already cover all branches).
