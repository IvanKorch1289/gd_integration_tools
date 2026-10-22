# Fix Plan — S3 / Cache / Logging

**Date**: 2026-10-21
**Companion**: `S3_CACHE_LOGGING_AUDIT_2026-10-21.md`
**Status**: awaiting approval — **no code modified yet**

Scope agreed in grilling: CRITICAL + HIGH + MEDIUM + LOW + docs.
Mechanisms pre-agreed (see audit §8). Each wave is independently revertable and
independently verifiable.

---

## Wave 0 — Restore the ability to prove anything (BLOCKING PREREQUISITE)

> **Nothing in Wave 1+ can be verified until this lands.**

| # | Change | File | Notes |
|---|---|---|---|
| 0.1 | Add `moto[s3]` to the `test-core` extra | `pyproject.toml` | Approved in grilling round 3. Un-skips `tests/unit/storage/test_s3_object_storage.py` (~24 tests) |
| 0.2 | Un-skip guard | `tests/unit/storage/test_s3_object_storage.py:31` | Remove the skip shim; keep a skip only if moto is genuinely absent |
| 0.3 | Correct the coverage doc's lie | `docs/analysis/storage-coverage-status.md:15` | Mark tests as skipped until 0.1 lands in CI |

**Acceptance**: `uv run --extra test-core pytest tests/unit/storage/ --collect-only -q`
→ 0 skipped; a real `pytest tests/unit/storage/test_s3_object_storage.py` run
goes green against `ThreadedMotoServer`.

**Risk**: low. Dependency addition only; already approved.

---

## Wave 1 — CRITICAL: data loss, exposure, and cleartext logs

### 1.1 Fail-open writes become loud (CRITICAL-01)
**Files**: `infrastructure/storage/fallback.py`, `infrastructure/storage/factory.py`

- Narrow `fallback_exceptions` from `(Exception,)` to a concrete outage set
  (`ServiceError`, `BotoCoreError`/`EndpointConnectionError`,
  `ConnectionError`, `TimeoutError`, `OSError`). A `ValueError`/bug must
  propagate, not be persisted.
- On fallback-to-disk for a **write**, record a quarantine marker so the object
  can be re-uploaded once S3 returns.
- Export a counter to the metrics pipeline (currently `fallback_count` is
  in-process only) and raise the log level to `ERROR` so alerting is possible.
- Make `factory.py` pass the explicit exception set rather than relying on the
  default.

**Acceptance**: re-run both runtime proofs — an outage must still serve the
write (fail-open kept) **and** increment a metric + log ERROR; a `ValueError`
must now propagate instead of being written to disk.

**Risk**: medium — the narrowed except changes which errors surface. Mitigated
by Wave 0 tests.

### 1.2 Tenant-aware fallback (CRITICAL-01 follow-on)
- `LocalFSStorage` secondary must receive the tenant prefix and participate in
  quota accounting, so an outage cannot escape tenancy guarantees.
- Mirror the `TenantCacheBackend` wrapper pattern.

### 1.3 Quota enforcement (CRITICAL-02)
**Files**: `services/storage/facade.py` (primary gate), `infrastructure/storage/s3.py` (safety net)

- Call `check_can_upload` before writes in the facade — this is the
  capability-gated path and keeps storage domain-agnostic per core doctrine.
- Add a cheap re-check inside `S3ObjectStorage` as the safety net for callers
  holding a raw backend.
- Fix the TOCTOU: combine check+record into one atomic operation (Redis
  `INCRBY`-style), not two round trips.
- Fix counter reset: a 7-day TTL silently zeroing usage must not under-count;
  use a rolling window or persist the rollover.

**Acceptance**: a test that uploads past the quota gets a rejected write; two
concurrent uploads cannot both pass the last available slot.

**Risk**: medium — quota is currently inert, so any enforcement is a new
behaviour that could block existing traffic. Roll out with a high limit first.

### 1.4 Per-tenant key isolation (CRITICAL-03)
**Files**: `infrastructure/storage/s3.py`, `infrastructure/storage/factory.py`

- Add a transparent wrapper mirroring `TenantCacheBackend` that auto-prefixes
  `tenant:{id}:/` from the tenant ContextVar. Callers keep passing tenant-free
  keys.
- `factory.py` finally passes the `key_prefix` override it accepts today.
- Apply `_safe_key` validation to `key_prefix` and `bucket`, not just the
  caller key.

**Acceptance**: two tenants writing the same logical key land in disjoint
prefixes; both read back only their own objects.

**Risk**: high — changes every existing object path. Requires a migration note
for existing objects under the flat `uploads/` prefix. **Decide explicitly
whether existing objects are migrated or left behind.**

### 1.5 Real TLS in the Graylog TCP sink (CRITICAL-04)
**Files**: `infrastructure/logging/backends/graylog_gelf.py`, `infrastructure/logging/factory.py`

- Wrap the socket with `ssl.create_default_context()` in `_send_tcp` when TLS
  is requested; honour `use_tls`, `ca_bundle`, and cert verification.
- Never let `use_tls: true` select a transport that cannot encrypt: if TLS is
  requested and unavailable, fail loudly rather than fall back to plaintext.

**Interim mitigation (ship first, in its own commit)**: `config_profiles/prod.yml:158,167`
— stop setting `use_tls: true` until the code can honour it, so prod stops
emitting cleartext logs during the gap.

**Acceptance**: a test asserting that with `use_tls: true` the connection is
TLS-wrapped and that tenant PII does not traverse plaintext.

**Risk**: medium — Graylog transport changes. Interim config flip is trivial and
revertable.

---

## Wave 2 — HIGH

| # | Change | File |
|---|---|---|
| 2.1 | Shared long-lived `aioboto3.Session`; close on shutdown — makes `max_pool_connections: 20` real | `s3.py:152-154` |
| 2.2 | Restore `RouteBuilder` S3 methods (`to_s3`/`from_s3`/`s3_presign`/`s3_delete`/`s3_list`) so YAML works | `dsl/builders/infrastructure_dsl.py:486-487` |
| 2.3 | Resolve the `from_s3` key collision — YAML `from_s3` currently hits the poll sensor, not the storage read | `dsl/builders/eip/sources.py:363` |
| 2.4 | Capability check must not no-op when `_check is None`; fail closed instead | `dsl/engine/processors/storage/s3.py:89-91`, `services/storage/facade.py:56-58` |
| 2.5 | Require credentials in prod; fail fast if absent (no anonymous default) | `config/services/storage.py:46-51`, `prod.yml:187-195` |
| 2.6 | Fail fast on S3 init errors; make the prod guard unable to disable itself | `storage/factory.py:163-169,68-71` |
| 2.7 | `delete_by_tag`: either implement cluster fan-out or **delete the false workaround** from `CYCLE_170_PROD_READINESS_2026-10-20.md:48` | `cache/backends/redis.py:107-132` |
| 2.8 | `DiskCacheBackend.exists()` must honour the TTL sidecar | `cache/backends/disk.py:189-203` |
| 2.9 | Remove `logging.basicConfig` from the production path | `logging/structlog_backend.py:275` |
| 2.10 | Wire `AIWorkspaceCleaner` into the app lifespan — R-V15-11 is a hard rule | `core/ai/workspace_cleaner.py:72` |
| 2.11 | Correct `storage-coverage-status.md` S3 row (DOC-01) | `docs/analysis/storage-coverage-status.md:15` |

---

## Wave 3 — MEDIUM + LOW

| # | Change | File |
|---|---|---|
| 3.1 | Wrap `_ensure_bucket` in `ServiceError`; restore the error contract | `s3.py:193` |
| 3.2 | Add SSE / ACL / presign-TTL-ceiling / versioning settings | `config/services/storage.py` |
| 3.3 | Presign authorization for the specific key, not just the capability | `services/storage/facade.py:158-162` |
| 3.4 | Make `policy.cache_policy()` either really cache or be documented as a marker | `dsl/builders/policy_mixin.py:61-106` |
| 3.5 | Bound `SemanticCache` with TTL + eviction | `cache/rag/semantic.py:118-148` |
| 3.6 | Document `FS_*` settings + fallback semantics (DOC-02) | new `docs/infra/storage.md` |
| 3.7 | Fix the `.s3_put(...)` docstring example (DOC-03) | `dsl/builders/infrastructure_dsl.py:401` |
| 3.8 | Delete dead helpers: `_wrap_boto`, `_get_real_s3_*` | `s3.py:215-219`, `infrastructure_dsl.py:334,347,356` |
| 3.9 | Read `resilience.fallbacks.minio` from config, or delete the key | `base.yml:611`, `factory.py:183-187` |
| 3.10 | Fix the `s3_cache.py` protocol mismatch (`get_object_bytes`) | `s3_cache.py:47` |
| 3.11 | Constrain the DSL-controlled `endpoint_url`/`bucket` (SSRF surface) | `dsl/builders/eip/sources.py:363-369` |
| 3.12 | Correct the `tenant_cache_prefix_enabled` description ("default-OFF" → actual `True`) | `core/config/features/sprints_18_21.py:232-241` |
| 3.13 | Migrate 74 inline `import logging`, hot-path first | 4 in `entrypoints/middlewares/`, 4 in `dsl/engine/processors/` |

---

## Explicitly deferred (with reasons)

- **Native S3 SSE-KMS / presigned-TTL policy** — partially in Wave 3; deeper
  IAM design deferred.
- **Per-tenant bucket** — rejected in favour of prefix isolation.
- **Multi-key `DEL` hash-slot handling** — only matters once cluster fan-out
  (2.7) is implemented.
- **`mutants/tests/unit/storage/` duplicates** — out of scope; the canonical
  suite was audited.

---

## Verification strategy per wave

| Wave | Proof |
|---|---|
| 0 | `pytest tests/unit/storage/` collects with 0 skips |
| 1 | Re-run both runtime proofs with inverted expectations; new quota/isolation/TLS tests |
| 2 | `make check-cache-facade-uniqueness`; `uv run python tools/check_layers.py --strict` (no new violations); targeted suites |
| 3 | Doc-accuracy pass; grep-guard that the dead symbols are gone |

**Gates to run at the end of every wave**: `make lint`, `make typecheck`, and
`check_layers.py --strict`, asserting no new violations versus the current
baseline.

---

## Open risks — resolved by fact-gathering (2026-10-21)

The three risks flagged below were open when the plan was first drafted. Per the
grilling contract ("finding facts is your job, never the user's") they were
investigated rather than pushed back to the user. All three now have evidence.

### R1 — 1.4 key isolation: migration is cheap; **no migration needed**

| Fact | Evidence |
|---|---|
| 22 files reference object storage, but all but two are plumbing (interfaces, DI providers, capability vocabulary) | `grep -rln "get_object_storage\|StorageFacade\|ObjectStorage" src/ extensions/` |
| **No extension business logic writes objects except `orders`** | `extensions/core_entities/orders/services/orders.py`; the `files` plugin does not touch storage |
| The only business key builder passes a bare UUID | `orders.py:194` — `upload_file(key=str(order_data["object_uuid"]))` |

**Conclusion**: there is no large flat-`uploads/` object corpus owned by business
flows, so a prefix change does not orphan real data. Tenant collisions today are
*accidental* (UUID keys rarely collide), not *prevented* — isolation is a missing
defence, not an active bug.

**Recommendation**: adopt the tenant prefix going forward; do not backfill.
Exception: any object written outside `orders.py` since go-live should be
spot-checked before the switch.

### R2 — 1.3 quota: alert-only first is low-risk

Only `orders.py` is a live business consumer of object storage. With a single
writer path, an alert-only rollout (high limit + counter, no rejection) costs
nothing and surfaces the real distribution before enforcement is switched on.

**Recommendation**: alert-only for one release, then enforce. Keep the atomic
check+record fix independent of that rollout — TOCTOU is a correctness bug
regardless.

### R3 — 2.5 credentials: the defect is *missing validation*, not anonymous operation

All five profiles (`base`, `dev`, `dev_light`, `staging`, `prod`) define **zero**
`access_key`/`secret_key`. Credentials are therefore supplied through
environment variables at deploy time, which is correct practice.

**Correction to the audit's initial characterisation**: HIGH-04 should be read
as *"there is no validation that credentials were provided"*, not *"prod ships
anonymous"*. The live risk is that a missing or misspelled `FS_ACCESS_KEY`
degrades **silently** to anonymous access instead of failing at startup.

**Recommendation**: keep HIGH-04, restate it as a fail-fast validation defect,
and gate it on `dev`/`staging` being checked for their env-var wiring before
the validation lands.

### Feasibility check — the wrapper is layer-legal

The agreed transparent-wrapper mechanism (grilling Q10) imports the tenant
context from core. This is already proven inside infrastructure:

```python
# src/backend/infrastructure/cache/tenant_wrapper.py:32
from src.backend.core.tenancy import TenantContext, current_tenant
```

`infrastructure/` may therefore import `core.tenancy`, so a
`TenantObjectStorage` wrapper in `infrastructure/storage/` introduces **no**
layer-rule violation. This removes the main architectural risk from item 1.4.