# Cycle 170 — Final Production Readiness Assessment (cache + logging)

* **Дата**: 2026-10-20
* **Цикл**: 170
* **Область**: cache + logging — финальная оценка после cycles 168-170

## TL;DR

**VERDICT: ГОТОВ к production** (с оговорками).

| Компонент | Статус до cycle 168 | Статус сейчас (cycle 170) |
|---|---|---|
| **Cache infrastructure** | ❌ НЕ ГОТОВ (4 critical) | ✅ ГОТОВ |
| **Cache DSL** | ❌ НЕ ГОТОВ (3 high + 1 med) | ✅ ГОТОВ |
| **Logging infrastructure** | ⚠️ Частично | ✅ ГОТОВ (централизованный init) |
| **Logging DSL** | ❌ НЕ ГОТОВ (3 high) | ✅ ГОТОВ (cycle 169) |

**Все critical/high issues закрыты в cycles 168-170.** Остаются deferred items
для cycle 175+ (non-blocking).

---

## 1. Cache Infrastructure — финальный статус

### Cycle 168 (PROD_READINESS_LOGGING_CACHE_2026-10-20.md)

| Issue | Статус |
|---|---|
| §1.1 DiskCacheBackend без TTL | ✅ Closed (TTL через expiry sidecar) |
| §1.2 memory_fallback/disk_fallback без tenant wrapper | ✅ Closed (TenantCacheBackend wrapped) |
| §1.3 MemoryBackend без per-key TTL | ✅ Closed (LRUCache + _CacheEntry wrapper) |
| §1.6 tag_index success-only update | ✅ Closed |
| §1.7 get_cache_facade() ABC contract | ✅ Closed (cycle 169) |
| §1.8 l1_enabled dead config | ✅ Closed |
| §2.1 base.yml disk_fallback_* | ✅ Closed |
| §3 Log throttling (5000 warnings/sec) | ✅ Closed (50x reduction) |

### Cycle 170 (ADR-0354, ADR-0356)

| Issue | Статус |
|---|---|
| CacheProcessor без tenant prefix (cross-tenant risk) | ✅ Closed (services.UnifiedCacheFacade через DI) |
| CacheProcessor узкий except | ✅ Closed (redis.exceptions.RedisError + builtin) |

### Остаётся deferred

- **Cluster-wide tag invalidation** (multi-process deployment).
  Workaround: используйте `RedisBackend.delete_by_tag` напрямую для cluster-wide.

---

## 2. Cache DSL — финальный статус

### Cycle 169 (DSL_AUDIT_CACHE_LOGGING_2026-10-20.md)

| Issue | Статус |
|---|---|
| §1.1 RouteBuilder.log signature gap | ✅ Closed |
| §1.2 LogProcessor message + ${...} interpolation | ✅ Closed |
| §1.3 InfraLogWriteProcessor literal vs docs | ✅ Closed |

### Cycle 170 (ADR-0354, ADR-0355, ADR-0356)

| Issue | Статус |
|---|---|
| §2.1 CacheProcessor без tenant prefix | ✅ Closed (ADR-0354) |
| §2.2 CacheProcessor узкий except | ✅ Closed (ADR-0356) |
| §2.3 policy.cache() MRO collision | ✅ Closed (ADR-0355, renamed cache_policy) |
| §4 infra_log_write dead declaration | ✅ Closed (InfraLoggingMixin) |
| Stale `route.to_cache()` docs (3 files) | ✅ Closed (cycle 169) |

### Остаётся deferred

- **`policy.cache_policy()` реальная cache реализация** (cycle 175+).
  Сейчас marker — нужно интегрировать с UnifiedCacheFacade.

---

## 3. Logging Infrastructure — финальный статус

### Cycle 168

- ✅ `init_application_logging()` централизованный startup
- ✅ Phase 1 миграция `schema_registry` на `get_logger`
- ✅ Lifecycle tests + centralized init tests + settings-driven init tests

### Cycle 169 (DSL logging fix)

- ✅ `RouteBuilder.log(level, message="")` — signature расширен
- ✅ `LogProcessor.message` с `${...}` interpolation
- ✅ `InfraLogWriteProcessor` с `${...}` interpolation (был docstring mismatch)

### Остаётся deferred (ADR-0351 phase 2+)

- **83 inline `import logging`** в не-инфраструктурных модулях. Это
  multi-cycle plan; не критично для prod (log-spam через эти модули
  ограничен), но желательно для unified observability.

---

## 4. Verification — cycle 170

### Tests

- **6004 tests passed** (после cycle 170 фиксов)
- 22 skipped (pre-existing, external deps)
- 32 xfailed (expected failures)
- 25 xpassed (теперь проходят)
- **0 failed**

### Tools

- `make check-cache-facade-uniqueness` → CLEAN
- `uv run python tools/check_layers.py --strict` → pre-existing violations only, no new

### Commits (cycles 168-170)

| Cycle | Commits | Domain |
|---|---|---|
| 168 | 8 commits | Cache infra fixes (TTL, tenant wrapper, log throttling) |
| 169 | 8 commits | DSL audit + log/audit fixes + stale docs |
| 170 | 5 commits | Deferred ADR fixes (rate_limiter, MRO, tenant, RedisError) |
| **Total** | **21 commits** | Atomic production-readiness work |

---

## 5. Production Recommendations

### MUST (перед deploy)

1. **Configure tenant-aware cache keys** для production routes:
   ```yaml
   - cache:
       key_fn: "${context.tenant_id}:${body.user_id}"
       ttl: 300
   ```
   ADR-0354 применяет `TenantCacheBackend` автоматически поверх вашего
   key, но для явной tenant-isolation в key рекомендуется включать
   `tenant_id` в сам key_fn.

2. **Verify `cache_settings.disk_fallback_enabled`** для in-cluster
   production. Cycle 168 default = `false` (disk anti-pattern для
   shared k8s pods). Override через env `CACHE_DISK_FALLBACK_ENABLED=true`
   если disk volume выделен.

3. **Set log level через env vars**:
   - `LOG_LEVEL=info` (production default)
   - `LOG_LEVEL=debug` (только для dev/staging)
   - `LOG_HOST/PORT/USE_TLS` для Graylog (см. `config_profiles/base.yml`).

### SHOULD (cycle 175+)

1. **Migrate 83 inline `import logging`** (ADR-0351 phase 2+).
2. **Remove `policy.cache()` deprecated shim** после полной migration
   на `policy.cache_policy()` (cycle 175+).
3. **Implement real cache в `policy.cache_policy()`** через
   `UnifiedCacheFacade` (cycle 175+ ADR followup).
4. **Cluster-wide tag invalidation** для multi-process deployments.

### NICE-TO-HAVE

1. CI guard для inline `import logging` (cycle 169 TODO).
2. CI guard для stale DSL method references (e.g., `to_cache`).
3. AI workspace TTL cleanup verification (R-V15-11).

---

## 6. Outstanding Tasks (cycle 175+)

| # | Task | Severity | Source |
|---|---|---|---|
| 1 | ADR-0351 phase 2+: migrate 83 inline `import logging` | MEDIUM | ADR-0351 |
| 2 | Cluster-wide tag invalidation | MEDIUM | PROD_READINESS §1.5 |
| 3 | Real cache в `policy.cache_policy()` | LOW | ADR-0355 followup |
| 4 | Remove deprecated `policy.cache()` shim | LOW | ADR-0355 followup |
| 5 | Cache DSL docs update (Cycle 169 + ADR-0354) | LOW | DSL_AUDIT §6 |
| 6 | ADR-0084/0090/0311 re-baseline | LOW | PROD_READINESS §5 |

---

## 7. Заключение

**Cache + Logging — готовы к production** после cycle 170.

Закрыто:
- 13 из 13 critical/high issues (cycles 168-170)
- 3 stale documentation fixes
- 1 dead declaration discovery + fix
- 4 ADRs jointly accepted (0353, 0354, 0355, 0356)

Качество:
- 6004 unit-тестов passing
- Layer check без новых violations
- Cache facade uniqueness guard CLEAN
- 21 atomic commits за 3 цикла
- Все fixes backward-compat

Outstanding (non-blocking):
- 6 deferred items для cycle 175+

**Вердикт**: PRODUCTION-READY с recommendations (см. §5).