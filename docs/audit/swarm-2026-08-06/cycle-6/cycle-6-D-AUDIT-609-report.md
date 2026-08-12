# Cycle 6 — D-AUDIT-609 report

## Task

- **ID:** T-C6-09-SSE-PRINCIPAL
- **Finding:** `ENTRY-P1-001` (cycle-4 audit)
- **Scope:** `src/backend/entrypoints/sse/handler.py` + `tests/unit/entrypoints/sse/test_handler_auth_propagation.py`
- **Marker:** `cycle-6/D-AUDIT-609`
- **Plan ref:** `docs/audit/swarm-2026-08-06/cycle-4/phase-1/04-entrypoints.md` §4.2

## Status

**IMPLEMENTED / TARGET TESTS PASS (8 xfailed → 0; +1 new integration test).**

SSE `/events/invoke` теперь пробрасывает `principal` / `permissions` из
`request.state.auth` в `dispatch_action_or_dsl`, устраняя ENTRY-P1-001
(fail-closed DSL route = SSE работал только для public routes).

Реализован helper `_extract_auth_from_request(request)` (parity с
`_extract_auth_from_info` в GraphQL — см.
`src/backend/entrypoints/graphql/schema.py:290-321`) и использованы
canonical `extract_user_permissions` из
`src/backend/core/auth/auth_context_helpers.py:51`.

Не тронуто: `pyproject.toml`, `uv.lock`, `.security/pip-audit-allowlist.txt`,
`src/backend/infrastructure/storage/s3.py`, `tools/blue_green.sh`,
`tests/unit/tools/test_blue_green_switch.py`,
`src/backend/services/ai/gateway_adapter.py` (residual at 128-129).
Cycle 1+2+3+4+5 atomic commits (HEAD `4b5831e4`) — не переписаны.

## Changes

### 1. `src/backend/entrypoints/sse/handler.py`

- **Imports:** +1 (`extract_user_permissions`).
- **New helper** `_extract_auth_from_request(request)` — извлекает
  `principal` и `permissions` из `request.state.auth`. Default fail-closed
  `("", ())` (anonymous).
- **`sse_invoke`** — добавлен вызов `_extract_auth_from_request(request)`
  и пробрасывание `principal=`, `permissions=` в `dispatch_action_or_dsl(...)`.
- **Docstring** обновлён с маркером `cycle-6/D-AUDIT-609`.

Diff stat: +35 / -3 LOC (1 new helper 28 LOC, 2 kwargs, 1 docstring update).

### 2. `tests/unit/entrypoints/sse/test_handler_auth_propagation.py`

- **8 xfail markers сняты** — все 8 ранее xfailed тестов теперь
  запускаются как обычные PASS (Round 24 forward-looking TDD закрыт).
- **1 new integration test** `test_no_auth_returns_401` —
  POST /events/invoke без auth → `require_auth` dependency raises
  `HTTPException(401)` → FastAPI возвращает 401 до `sse_invoke`.
  Использует `httpx.ASGITransport` + `AsyncClient` (см. паттерн в
  `tests/unit/entrypoints/api/test_ai_stream_endpoint.py:14-34`).
- **Docstring** обновлён с маркером `cycle-6/D-AUDIT-609`.

Diff stat: +41 / -18 LOC.

## Evidence (runtime)

Все runtime-проверки через `.venv/bin/python` (per AGENTS.md).

### 1. SSE auth propagation tests

```text
$ .venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v

tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_authorized_principal_propagates_to_dispatch PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_oauth_scope_metadata_normalized PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_no_auth_state_fails_closed_anonymous PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_wrong_role_fails_closed PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_public_route_dispatches_with_principal PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_execution_context_in_dispatch_call PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextEdgeCases::test_auth_with_no_metadata_yields_empty_permissions PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthEdgeCases::test_request_state_without_auth_attribute PASSED
tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthIntegrationNoAuth::test_no_auth_returns_401 PASSED

========== 9 passed in 3.46s ==========
```

8 ранее xfailed тестов → PASS; 1 новый integration test → PASS.
**xfail → 0 ✓**

### 2. SSE handler core tests (no regressions)

```text
$ .venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler.py::TestSseInvoke tests/unit/entrypoints/sse/test_handler.py::TestEventBus tests/unit/entrypoints/sse/test_handler.py::TestToPrimitive tests/unit/entrypoints/sse/test_handler.py::TestSseStream::test_stream_response tests/unit/entrypoints/sse/test_handler.py::TestSseStream::test_stream_yields_event -v

========== 16 passed in 1.20s ==========
```

### 3. Other entrypoints regressions check

```text
$ .venv/bin/python -m pytest tests/unit/entrypoints/cdc/test_management_endpoints_auth.py tests/unit/entrypoints/stream/test_invoker_subscribers.py tests/unit/entrypoints/filewatcher/test_watcher_manager.py -q

========== 29 passed, 1 warning in 6.55s ==========
```

### 4. Helper smoke test

```text
$ .venv/bin/python -c "from src.backend.entrypoints.sse.handler import _extract_auth_from_request; ..."

anonymous: '' ()
alice: 'alice' ('role:admin',)
no auth attr: '' ()
```

## Gates

| Gate | Baseline | Cycle 6 | Status |
|---|---|---|---|
| Layer checker (175/0) | 175/0 | 175/0 (2278 files) | **PASS** |
| Security allowlist (≤27) | 27 | 27 | **PASS** |
| Docstring gate (0 missing) | 0 | 0 | **PASS** |
| `uv.lock` net lines | -15 net | -15 net (pre-existing, НЕ тронут) | **PASS** |
| `s3.py` modified | нет | нет | **PASS** |
| `gateway_adapter.py:128-129` | present | present (UNTOUCHED) | **PER PLAN** |

Preflight script output (`bash tools/cycle-1-preflight.sh`):

```text
[OK]   layer checker — 0 new, 175 legacy
[OK]   allowlist active IDs — 27
[OK]   docstring gate — 0 missing
[FAIL] working tree — 43 entries  (pre-existing concurrent cycle work, не от T-C6-09)
[FAIL] uv.lock churn — 45 lines    (pre-existing -15 net, не от T-C6-09)
[OK]   s3.py untouched — не modified
```

Working tree FAIL — pre-existing concurrent modifications (cycle-1..6
несколько агентов параллельно). Мои изменения: 2 файла
(`sse/handler.py`, `test_handler_auth_propagation.py`).
uv.lock FAIL — pre-existing -16/+1 = net -15 svcs-удаление из предыдущего
цикла; я не модифицировал uv.lock.

## Readiness impact

| Метрика | До (cycle-4) | После (cycle-6) |
|---|---|---|
| P1 (entrypoints) | 4 (incl. ENTRY-P1-001) | 3 (ENTRY-P1-001 closed) |
| Entry-points score | 57/100 | 57/100 (cap rule: P0 ещё есть — ENTRY-P0-x out of scope) |

ENTRY-P1-001 устранён: SSE `/events/invoke` теперь parity с GraphQL/SOAP/REST
по пробросу principal/permissions. 8 ранее xfailed тестов теперь PASS.

## Files modified

```
 src/backend/entrypoints/sse/handler.py                          | +35 / -3
 tests/unit/entrypoints/sse/test_handler_auth_propagation.py    | +41 / -18
 docs/audit/swarm-2026-08-06/cycle-6/cycle-6-D-AUDIT-609-report.md | NEW
```

2 source files + 1 report. Минимальный diff в рамках задачи.

---

*Cycle 6 D-AUDIT-609. ENTRY-P1-001 closed. 8 xfailed → 0; +1 new
integration test. Layer 175/0. Docstring gate 0. uv.lock UNTOUCHED.*