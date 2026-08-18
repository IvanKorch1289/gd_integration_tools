# Cycle 225 — Redis methods fix + functional testing (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 225)
**Scope:** Continue cycle 224 Redis fix (pubsub + caller). More functional testing.

---

## TL;DR

| Item | Status |
|---|---|
| RedisClient `pubsub()` (D-AUDIT-20815) | ✅ DONE (12/12 redis tests pass) |
| HITL caller `await` (D-AUDIT-20816) | ✅ DONE (8/8 hitl tests pass) |
| Functional tests via cURL | ✅ 10+ endpoints verified |
| RedisClient `health_check()` (missing) | ⚠️ DEFERRED cycle 226+ (multi-method refactor) |
| NEW-3 MCP real JSON-RPC | ❌ STILL 404 (multi-cycle debug) |

**2 commits** (`65e9f84a`, `6d3afd63`).

---

## 1. Cycle 225 changes

### 1.1 `RedisClient.pubsub()` (D-AUDIT-20815)

```python
# src/backend/infrastructure/clients/storage/redis/__init__.py
async def pubsub(self, kind: RedisKind = "queue") -> Any:
    """Public Pub/Sub handle (delegates to underlying redis.asyncio.Redis.pubsub)."""
    client = await self.get_client(kind)
    return client.pubsub()
```

**Root cause**: `RedisClient(ConnectionMixin, CacheMixin, HelpersMixin, StreamMixin)` — StreamMixin provides xadd/xread (Redis Streams), NOT pubsub (Redis Pub/Sub). Caller `hitl_signal_store_redis.py:328` failed with `'RedisClient' object has no attribute 'pubsub'`.

### 1.2 HITL caller `await` (D-AUDIT-20816)

```diff
- pubsub = client.pubsub()
+ pubsub = await client.pubsub()
```

**Root cause**: After cycle 225 added `async def pubsub()`, the caller continued to use sync pattern, getting a coroutine instead of PubSub object. Error: `'coroutine' object has no attribute 'subscribe'`.

---

## 2. Functional testing (cycle 225c)

### 2.1 Test matrix

| Endpoint | Method | Result |
|---|---|---|
| `/health` | GET | ✅ 200 |
| `/api/v1/health/components` | GET | ⚠️ 200 (Redis 'health_check' missing) |
| `/api/v1/admin/system-info` | GET | ✅ 200 |
| `/api/v1/admin/actions` | GET | ✅ 200 (131 actions) |
| `/api/v1/admin/services` | GET | ✅ 200 (25 service groups) |
| `/api/v1/admin/feature-flags` | GET | ✅ 200 |
| `/api/v1/admin/actions/invoke` | POST | ✅ 200 (mock) |
| `/graphql` | POST | ✅ 200 |
| `/openapi.json` | GET | ✅ 200 |
| `/mcp` | POST | ❌ 404 (NEW-3) |

### 2.2 Discovered bugs

1. **`'RedisClient' object has no attribute 'health_check'`** (D-AUDIT-20817) — same root cause as ping/pubsub. Different code path: health_aggregator expects `.health_check()` method.
2. **`'coroutine' object has no attribute 'subscribe'`** — FIXED in this cycle (D-AUDIT-20816).
3. **`'RedisClient' object has no attribute 'pubsub'`** — FIXED in this cycle (D-AUDIT-20815).

---

## 3. Recommended next cycle (cycle 226+)

Per analyst top 5 priorities:
- Cycle 226: `RedisClient` inherit from `ManagedAsyncClient` (gets `health_check`, `_ping`, etc. — fixes all remaining missing methods in ONE change)
- Cycle 227: NEW-3 MCP lifespan wire (low risk, 2-effort)
- Cycle 228: McpAuthMiddleware re-attach
- Cycle 229: gRPC Cython (option C — manual handler)
- Cycle 230: DSL builder mixin lazy `__getattr__`

**Cycle 226 is the smallest atomic refactor** — single class inheritance change fixes 3 missing methods (ping, pubsub, health_check). Per Ponytail "smallest working diff wins", this is the optimal next step.

---

## 4. Артефакты

- `src/backend/infrastructure/clients/storage/redis/__init__.py` (+18/-0)
- `src/backend/services/workflows/hitl_signal_store_redis.py` (+3/-1)
- `docs/audit/CYCLE-225-REDIS-METHODS-FIX.md` (this file)

**HEAD**: `6d3afd63`

---

## 5. Status summary (cycles 201-225)

- **40 atomic commits**, +6700+ LOC, 50+ new tests, 0 regressions
- **NEW-3** at 99% (mount path mismatch deferred)
- **gRPC Cython** real RPC deferred (lock file change)
- **Cycles 222-225** (4 cycles): 9 pre-existing test failures fixed + 2 real bugs found and 1 fully fixed
- **Remaining Redis methods** (health_check) — cycle 226+ (single-class-inheritance refactor)
