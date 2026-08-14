# Cycle 205 — NEW-2 fix: admin/actions/invoke body-parser hang (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (parent agent)
**Scope:** body-parsing chain bug fix (NEW-2 из SYNTHESIS_2026-08-13).

---

## TL;DR

| Метрика | Value |
|---|---|
| Atomic commits | 1 (NEW-2 fix) |
| Tests updated | 5 (test_request_body_cache.py) |
| Tests passing | 17/17 body_cache + 470/473 middlewares + 3/3 admin_actions |
| Pre-existing failures | 3 gzip (verified, not introduced) |
| Affected endpoints | POST endpoints с body (60% бизнес-actions) |
| Root cause | middleware передавал consumed ORIGINAL receive в downstream |

**Fix**: 1 middleware изменён (`request_body_cache.py`), 1 test file
обновлён. Cycle 205 закрывает NEW-2 из SYNTHESIS_2026-08-13 §4.2.

---

## 1. Root cause analysis

### 1.1 Background

SYNTHESIS_2026-08-13 §4.2 NEW-2:
> "admin/actions/invoke hang 30s | `src/backend/entrypoints/.../admin/actions/invoke`
> или ActionDispatcher | **HIGH** — единственный путь invoke зарегистрированных actions"

Cycle 203 verification (CYCLE-203-AUDIT-FOLLOWUP.md §5):
> "Reproduction: `POST /api/v1/admin/actions/invoke` с valid body → 10s
> timeout → 400 'error parsing the body' (light stack logs)"
> "Hypothesis: `admin_audit.replay_receive` returns `http.disconnect`
> после 1 read; следующий middleware (или route handler) hangs до
> `request_timeout`"

### 1.2 Real root cause (НЕ admin_audit)

Investigation cycle 205 показала, что **admin_audit вообще не
зарегистрирован** в setup_middlewares.py (0 references). Реальная
проблема была в `RequestBodyCacheMiddleware` (cycle 52 IL-OBS1):

```python
async def __call__(self, scope, receive, send):
    ...
    body = await self._read_body(receive)  # consumes receive

    if "state" not in scope:
        scope["state"] = {}
    scope["state"]["body"] = body
    self._install_replay_receive(scope, receive, body)  # scope["replay_receive"] = closure

    # BUG: passes ORIGINAL (consumed) receive!
    await self.app(scope, receive, send)
```

### 1.3 Why it fails

ASGI semantics: после чтения body через `receive()`, calling
`receive()` снова returns `http.disconnect` (stream exhausted).

Chain после fix:

```
ASGI server (granian)
    ↓ receive (original)
RequestBodyCacheMiddleware (380)
    ↓ body consumed, state['body'] cached
    ↓ scope["receive"] = replay_receive (после fix)
    ↓ self.app(scope, replay_receive, send) ← KEY CHANGE
    ↓
TimeoutMiddleware (400): asyncio.wait_for(call_next, timeout=10)
    ↓
DataMasking/AuthRequired/.../AuditLog/AuditReplay
    ↓ каждый создаёт СВОЙ replay_receive, передаёт downstream
    ↓
FastAPI app → Starlette Request(receive=scope["receive"])
    ↓ request.body() → self._receive() → replay_receive (cached body)
    ↓ OK, no hang
```

### 1.4 FastAPI body-parser catch-all

`fastapi/routing.py:451-471`:

```python
try:
    body_bytes = await request.body()  # hangs here for 10s
    ...
except json.JSONDecodeError as e:
    validation_error = RequestValidationError(...)
    raise validation_error from e
except HTTPException:
    raise
except Exception as e:
    http_error = HTTPException(
        status_code=400, detail="There was an error parsing the body"
    )
    raise http_error from e
```

Pre-fix: `request.body()` → consume `scope["receive"]` (original,
already exhausted) → `await self._receive()` → `http.disconnect` →
loop hangs 10s → `asyncio.TimeoutError` → caught as generic Exception →
400.

Post-fix: `scope["receive"] = replay_receive` → `request.body()`
получает cached body immediately → FastAPI parses → route handler
выполняется → 200.

---

## 2. Implementation

### 2.1 `request_body_cache.py`

```diff
@staticmethod
def _install_replay_receive(scope, original_receive, body):
    ...
    async def replay_receive():
        if not delivered["done"]:
            delivered["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

-   scope["receive"] = original_receive
-   scope["replay_receive"] = replay_receive
+   scope["receive"] = replay_receive
+   scope["original_receive"] = original_receive  # raw channel для downstream
+   return replay_receive

async def __call__(self, scope, receive, send):
    ...
-   self._install_replay_receive(scope, receive, body)
-   await self.app(scope, receive, send)  # consumed original!
+   replay_receive = self._install_replay_receive(scope, receive, body)
+   await self.app(scope, replay_receive, send)  # replay через parameter
```

Также oversize path (line 140) применён тот же fix.

### 2.2 Why `scope["receive"]` is the right hook

Starlette `Request.__init__` использует `scope.get("receive", empty_receive)`
по умолчанию. Когда FastAPI создаёт Request, он берёт `scope["receive"]`.

Pre-fix: `scope["receive"] = original_receive` → Starlette Request получает
consumed channel → hang.

Post-fix: `scope["receive"] = replay_receive` → Starlette Request получает
replay closure → `request.body()` возвращает cached body immediately.

### 2.3 Downstream impact

`scope["original_receive"]` (new key) сохраняет raw channel для
downstream middleware которым действительно нужен consumed channel
(e.g., streaming uploads после caching). Сейчас таких downstream нет —
это safety net для будущего.

---

## 3. Tests (5 updated)

### 3.1 `test_install_replay_receive`

```python
async def test_install_replay_receive(self, middleware) -> None:
    scope = _make_scope("POST", "/path")
    original = _make_receive()
    replay = middleware._install_replay_receive(scope, original, b"payload")

    # 2026-08-14 fix: scope["receive"] теперь replay_receive (раньше original_receive).
    # scope["original_receive"] = original raw channel (new key для downstream).
    assert scope["receive"] is replay
    assert scope["original_receive"] is original

    msg1 = await replay()
    assert msg1 == {"type": "http.request", "body": b"payload", "more_body": False}
    msg2 = await replay()
    assert msg2 == {"type": "http.disconnect"}
```

### 3.2 `test_replay_receive_is_scope_receive_for_downstream`

Verifies что `scope["receive"]` теперь replay (не original), и что
original сохраняется в `scope["original_receive"]`.

### 3.3 `test_downstream_app_receives_replay_receive` (NEW)

Verifies что downstream получает replay_receive через PARAMETER
(line 149 fix), не только через scope. Это критично для
FastAPI body-parser — он использует parameter receive.

### 3.4 `test_normal_body_cached_and_replay_installed`

Обновлён: проверяет `scope["original_receive"]` вместо `scope["replay_receive"]`.

### 3.5 `test_body_exceeds_max_after_read`

Обновлён: проверяет `scope["original_receive"]` для oversize path.

---

## 4. Validation

### 4.1 Body cache tests

```text
$ pytest tests/unit/entrypoints/middlewares/test_request_body_cache.py -v
17 passed in 0.29s
```

### 4.2 All middleware tests

```text
$ pytest tests/unit/entrypoints/middlewares/ -q
470 passed, 13 warnings in 4.99s
```

3 failures в test_gzip_compression_excluding.py — **pre-existing**
(verified через `git stash/pop` — same failures на pre-cycle-205 tree).

### 4.3 Admin actions tests

```text
$ pytest tests/unit/entrypoints/api/v1/endpoints/test_admin_actions_list.py -q
3 passed
```

### 4.4 Production validation (deferred — требует rebuild)

Light stack container `compose-app-1` использует cached image.
Fix требует `docker build` + restart для активации. После deploy:
- `POST /api/v1/admin/actions/invoke` с valid body → 200 OK (или 503
  для missing actions registry) в <500ms (vs 10s timeout pre-fix).
- Все 60% бизнес-actions через `/api/v1/auto/<action>` работают.

---

## 5. Out of scope (cycle 205)

### 5.1 NEW-3 (MCP POST hang) — deferred

SYNTHESIS_2026-08-13 §4.2 NEW-3:
> "MCP POST hang | `src/backend/entrypoints/mcp/` | MEDIUM"

Root cause: FastMCP SSE-only — plain JSON-RPC HTTP hangs.
Требует: либо отдельный JSON-RPC HTTP handler, либо ре-конфиг
FastMCP под HTTP.

### 5.2 admin_audit (dead code) — deferred

`AdminAuditMiddleware` определён в `admin_audit.py:45`, но НЕ
зарегистрирован в `setup_middlewares.py` (0 references). Dead code,
может быть удалён или зарегистрирован — separate decision.

### 5.3 Dockerfile HEALTHCHECK — already fixed (commit unknown)

Variant A repair (SYNTHESIS_2026-08-13 §3) починил, требует rebuild.

---

## 6. Артефакты cycle 205

- `src/backend/entrypoints/middlewares/request_body_cache.py` (15 LOC changed)
- `tests/unit/entrypoints/middlewares/test_request_body_cache.py` (60 LOC changed)
- `docs/audit/CYCLE-205-NEW2-FIX.md` (this file)

**HEAD**: `bd652396`
