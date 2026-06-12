# ADR-0162 — Sprint 80 closure: P1 #6 LiteLLM Gateway pool registration (PoolHealthMonitor integration, 8 NEW tests) (6 commits)

* Статус: Accepted (Autonomous work cycle S80, 2026-06-12)
* Связано с: FINAL_REPORT_V2 P1 #6 ("Добавить connection pool
  для LiteLLM Gateway"), направление #3, S37.2 (UnifiedPoolManager)

## Контекст

S80 = **P1 направление #3 closure** (FINAL_REPORT_V2 P1 #6: "Добавить
connection pool для LiteLLM Gateway"). Pre-S80: LiteLLM Gateway
(services/ai/gateway/client.py) использовал `litellm.acompletion()`
напрямую — НЕ был зарегистрирован в `PoolHealthMonitor`, health
checks НЕ выполнялись.

## Команда результаты (6 commits)

### W1: Pool registration helper (commit `dd1704eb`)
- File: `src/backend/services/ai/gateway/pool_registration.py` (NEW, 119 LOC)
- `_litellm_ping(gateway) → bool` — liveness check (litellm.models query)
- `register_litellm_pool(gateway, name, idle_timeout, monitor)`:
  - Lazy-import litellm (opt-in [ai] extra)
  - Registers в PoolHealthMonitor с custom ping

### W2: Lifecycle integration (commit `08e38eef`)
- File: `src/backend/plugins/composition/setup_infra/pools.py` (+18, -0)
- `_register_pools_in_unified_manager()` теперь auto-регистрирует
  LiteLLM (feature_flags.ai_gateway_enforce guard, try/except safety)

### W2 follow-up: feature flag fix (commit `049d2940`)
- File: `pools.py` (+1, -1)
- Correct flag: `ai_gateway_enforce` (S25 W1, ADR-NEW-19)
- Pyright reported unknown `ai_gateway_enabled` — fixed

### W3: Testability (commit `e4a06ce4`)
- File: `pool_registration.py` (+1, -1) + tests (+127, -0)
- Added `monitor=` keyword arg (default None → singleton)
- 8 NEW tests (4 ping + 4 register)

### W4: Tests fix (commit `f2dee66d`)
- File: `test_litellm_pool_registration.py` (+7, -13)
- Use `monitor._pools` internal dict (no public `list_pools()` method)

### W5: Closure (this commit)

## Final state vs FINAL_REPORT_V2 P1 #6

| Aspect | Before S80 | After S80 |
|---|---|---|
| LiteLLM pool registered | ❌ | ✅ **S80 W1+W2** |
| PoolHealthMonitor tracks LiteLLM | ❌ | ✅ |
| Liveness check (ping) | ❌ | ✅ `_litellm_ping` |
| Auto-registration on startup | ❌ | ✅ `_register_pools_in_unified_manager` |
| Feature flag guard | ❌ | ✅ `ai_gateway_enforce` |
| Tests | 0 | **8 NEW** |

**Status vs FINAL_REPORT_V2 P1 #6**: CLOSED.

## Use case

```python
# Pre-S80: LiteLLM health was untracked
# UnifiedPoolManager reported: db_main, redis_main, s3_main, clickhouse_main
# LiteLLM: NOT REGISTERED → health blind spot

# Post-S80:
gateway = LiteLLMGateway(default_model="gpt-4")
register_litellm_pool(gateway, name="litellm_main", idle_timeout=60.0)
# UnifiedPoolManager now reports: ... + litellm_main (with liveness ping)
```

## Files changed summary

- W1: 1 file (+119, -0) — pool_registration.py
- W2: 1 file (+18, -0) — pools.py
- W2 follow-up: 1 file (+1, -1) — flag name
- W3: 2 files (+128, -1) — testability + tests
- W4: 1 file (+7, -13) — use _pools
- W5: 3 files (closure, this commit)
- **Total: 9 files, NET +273 LOC**

## S81+ epic candidates

1. **S81: CircuitBreakerMiddleware restoration** (P1 направление #16)
2. **S82: docs/cookbooks/** (P1 направление #13)
3. **S83+: AI stack consolidation** (5 frameworks → 2-3)
4. **S83+: 196 layer violations** (направление #2 class moves)
5. **S83+: tools/check_decomp_bugs.py** (recurring pattern fix)
