# S3 / Cache / Logging — Production-Readiness Audit

**Date**: 2026-10-21
**Cycle**: 171
**Base**: HEAD `86c5eff2d` (post cycle-170)
**Scope**: S3/object storage (never previously audited), cache + logging (re-verification of cycle 168-170 claims)
**Method**: grilling (3 rounds, 8 decisions) + agent fact-finding + direct code verification + runtime proof

---

## 0. Executive verdict

**S3 — NOT PRODUCTION-READY.** Four CRITICAL defects, three of which lose or
expose data. S3 had **zero** prior audit coverage in cycles 168-170 despite
being a Tier-1 storage backend.

**Cache — PRODUCTION-READY with 2 caveats.** Cycle 168/170 fixes are genuine
(verified in code, not trusted from the report). Two HIGH issues remain and one
documented "workaround" is invalid.

**Logging — NOT PRODUCTION-READY.** Production emits cleartext logs over a
transport selected *by* the TLS flag. A mandated AI-safety rule (R-V15-11) is
documented but never wired.

| Severity | S3 | Cache | Logging | Total |
|---|---|---|---|---|
| CRITICAL | 3 | 0 | 1 | **4** |
| HIGH | 5 | 2 | 2 | **9** |
| MEDIUM | 4 | 2 | 0 | **6** |
| LOW | 3 | 1 | 1 | **5** |

---

## 1. Methodology note — claims were verified, not trusted

The governing review (`deliverables/prod-readiness-review-2026-10-19/REVIEW.md`)
recorded a verdict invalidated because it trusted a stale report. Two independent
failure modes were caught in this cycle and are worth recording as process rules:

**1.1 Contradicting agent claims, resolved in the code.** Two agents disagreed
on cache TTL. Agent A claimed `MemoryBackend.set()` "silently drops ttl" and
`DiskCacheBackend` has "no TTL sidecar". Direct inspection of
`infrastructure/cache/backends/memory.py:42-56,110-126` and
`backends/disk.py:43,92-117` shows both claims are **false**: `_CacheEntry`
carries `expires_at`, `_resolve_expires_at()` honours per-key TTL, and
`.expires` sidecar is checked on read. Accepting agent B's report would have
filed two bogus HIGH findings and triggered a pointless rewrite of working code.

**1.2 An agent reported tests exist without checking they run.** The S3 agent
cited "~24 tests" for the S3 backend. Those tests are **100% skipped**:

```
tests/unit/storage/test_s3_object_storage.py:31:
  Skipped: moto not in test deps; S124 W2 honest skip (TD-0244)
```

`moto` is absent from `pyproject.toml` entirely. Every S3 claim of test coverage
in this repository — including `docs/analysis/storage-coverage-status.md` — is
hollow.

> **Process rules adopted**
> 1. A claim about test coverage requires observing a test *run*, not reading a test file.
> 2. When two sources conflict, the source code decides. Never arbitrate by seniority.

---

## 2. S3 — runtime proof (CRITICAL-01)

Live containers were requested but **Docker Hub is unreachable from this
environment** (`pull access denied for minio/minio`). Runtime proof was
therefore obtained against the **real production classes** rather than mocks:
`FallbackObjectStorage` + `LocalFSStorage` + authentic
`botocore.exceptions.EndpointConnectionError`, constructed exactly as
`factory.py:183-187` constructs them.

```
PROOF 1 — S3 OUTAGE
  upload() RETURNED NORMALLY -> '/tmp/.../uploads/2026/contract.pdf'
  Files written to pod-local disk : 1  (28 bytes)
  Primary (S3) invocations        : 1
  fallback_count                  : {'upload': 1, ...}
  Subsequent download() works    : True
```

**A total S3 outage is invisible to the caller.** The write lands in a
pod-local directory, returns success, and subsequent reads are served from
that directory. Pod eviction, node drain, or redeploy destroys the data with no
error, no exception, and no caller-visible signal.

**PROOF 2 — the catch clause is not an outage detector**

```
Primary raises ValueError("cannot serialize metadata field 'expiry' to JSON")
  upload() -> '/tmp/.../uploads/report.pdf'      # accepted
  Files silently written to disk : 1
```

`fallback_exceptions = (Exception,)` (`fallback.py:73`) treats a programming
bug identically to an infrastructure outage. A serialization defect is masked
as "successful" storage, discovered only by reading logs.

> Method correction: the first run of this proof used an invalid key, so both
> primary and secondary raised `ValueError` and the secondary error propagated,
> making the clause look correctly scoped. The warning log from that run
> nevertheless recorded `primary failed (ValueError ...) falling back to
> secondary` — i.e. it *had* been swallowed. The corrected run uses a valid key
> so the secondary succeeds, isolating the behaviour.

---

## 3. S3 findings

### CRITICAL-01 — Fail-open writes lose data silently
- **Where**: `infrastructure/storage/fallback.py:73,134-154`; `factory.py:183-187`
- **What**: Any primary exception routes the write to pod-local disk and
  returns success. `factory.py` constructs the chain without passing
  `fallback_exceptions`, so the `(Exception,)` default applies.
- **Evidence**: runtime proof §2.
- **Aggravating**: the fallback is not tenant-aware — the LocalFS secondary
  receives no tenant prefix and no quota accounting, so data written during an
  outage also escapes tenancy and quota guarantees.

### CRITICAL-02 — Per-tenant quota is entirely dead code
- **Where**: `infrastructure/storage/tenant_file_quota.py`
- **What**: `check_can_upload` and `record_upload` have **zero callers** outside
  their own module. No upload path is quota-gated.
- **Evidence**: `grep -rn "check_can_upload\|record_upload" src/ extensions/ routes/` → empty.
- **Also**: the two calls are separate round trips (TOCTOU), so concurrent
  uploads all pass the check even once wired; and the 7-day counter TTL resets
  usage to 0, under-counting.

### CRITICAL-03 — No per-tenant key isolation on a shared bucket
- **Where**: `infrastructure/storage/s3.py:122-124`; `factory.py:154`
- **What**: A single global `key_prefix="uploads"` prefixes every object for
  every tenant. The constructor accepts a `key_prefix` override explicitly
  documented at `s3.py:109` as *"override префикса из настроек (для
  tenant-изоляции)"* — **`factory.py` never passes it**. Two tenants writing
  `report.pdf` collide in one bucket.
- **Also**: `_safe_key()` validates the caller's key but never `key_prefix` or
  `bucket`.

### HIGH-01 — aioboto3 connection pooling is a no-op
- **Where**: `s3.py:152-154` (`_S3Session.__aenter__`), `s3.py:136`
- **What**: a client is constructed and torn down per operation.
  `max_pool_connections: 20` is passed into `BotoConfig` but the pool dies with
  each call. Every operation pays full TCP+TLS handshake.

### HIGH-02 — No YAML route can reach object storage
- **Where**: `dsl/yaml_loader/build.py:198`; `dsl/builders/infrastructure_dsl.py:486-487`
- **What**: `_apply_processor` resolves YAML steps via
  `getattr(builder, proc_name)`, but the `RouteBuilder` S3 methods were deleted.
  Five processors exist (`to_s3`, `from_s3`, `s3_presign`, `s3_delete`,
  `s3_list` in `dsl/engine/processors/storage/s3.py`) and are unreachable.
- **Also a collision**: YAML `from_s3:` resolves to an S3 **poll sensor**
  trigger (`dsl/builders/eip/sources.py:363`), not the storage-read processor —
  the same key means two different things.

### HIGH-03 — Capability check silently bypassed
- **Where**: `dsl/engine/processors/storage/s3.py:89-91`; `services/storage/facade.py:56-58`
- **What**: the DSL fallback path constructs a facade with
  `capability_check=None`; when absent, the facade no-ops the check. A V11.1
  capability-gated resource is reachable without a declared capability.

### HIGH-04 — S3 credentials are never validated (silent anonymous degradation)
- **Where**: `config_profiles/prod.yml:187-195`; `config/services/storage.py:46-51`
- `access_key`/`secret_key` default to `""` = anonymous, and **none of the five
  config profiles define them** — credentials are correctly supplied via
  environment variables at deploy time.
- **The defect is the missing validation, not anonymous operation**: if
  `FS_ACCESS_KEY` is missing or misspelled, the client degrades silently to
  anonymous instead of failing at startup. Combined with HIGH-05 (soft fail on
  init error), a misconfigured deploy looks healthy while being unable to write.
- **Positive**: `verify: true`, `use_ssl: true` in prod and staging — TLS
  hygiene is clean; no `CERT_NONE`/`check_hostname=False` anywhere in storage.

### HIGH-05 — Misconfiguration fails soft outside production; the guard can disable itself
- **Where**: `storage/factory.py:150-169,41-92`
- **What**: any `S3ObjectStorage` init error (including bare `Exception`) is
  swallowed into a bare LocalFS backend with a WARNING.
- **Correction (verified against `test_factory.py:300`)**: this is **not**
  silent in production. Both fallback branches call `get_local_fs_storage()`,
  which runs `_enforce_local_fs_safe_in_prod()` and raises
  `ProductionConfigError` — there is an explicit test asserting exactly that,
  whose docstring reads "НЕ silent fallback".
- **The real residual risk is narrower**:
  1. **staging** (`environment != "production"`) degrades silently to bare
     LocalFS — the very environment where misconfiguration is supposed to be
     caught;
  2. `_enforce_local_fs_safe_in_prod` wraps its Settings import in
     `except Exception: return` (`factory.py:68-71`) — if Settings cannot be
     imported the guard silently no-ops, and `provider` itself defaults to
     `"local"` at `factory.py:144-145`, yielding silent LocalFS even in prod.

### CRITICAL-05 — `aioboto3` is undeclared (found while implementing Wave 0)

`aioboto3` appears in neither `pyproject.toml` nor `uv.lock`, yet
`S3ObjectStorage.__init__` calls it eagerly (`s3.py:125`,
`_import_aioboto3().Session()`).

- **Impact in production is loud**, not silent: the resulting `ImportError`
  hits `factory.py:155-160`, which calls `get_local_fs_storage()`, whose guard
  raises `ProductionConfigError`. A production deploy therefore **fails to
  start** rather than quietly serving pod-local disk.
- **Impact outside production is silent**: staging/dev degrade to bare LocalFS
  with a WARNING, which looks healthy while providing no object storage.
- **Blocked fix**: declaring `aioboto3` was attempted and reverted. `aiobotocore`
  (its transitive dependency) pins `boto3`/`botocore` to narrow ranges that are
  incompatible with the `boto3`/`botocore 1.43.75` pinned in `uv.lock`, and the
  configured index offers only `aioboto3 <= 13.0.1`. Adding it makes the project
  unsatisfiable. This needs an explicit decision (pin an older `boto3`/`botocore`,
  wait for `aiobotocore`, or keep the dependency external), not a unilateral
  change.

### MEDIUM-01 — `ServiceError` contract broken
- **Where**: `s3.py:193` vs `s3.py:242`
- `_ensure_bucket()` runs inside `__aenter__`, **outside** each method's `try`.
  It catches only `ClientError`, so `BotoCoreError` escapes un-wrapped and
  violates the documented `ServiceError` contract.

### MEDIUM-02 — No encryption/ACL/versioning settings exist
- **Where**: `config/services/storage.py`
- Absent entirely: server-side encryption, ACL/public-read, presign TTL ceiling
  (`presigned_url()` defaults to 3600s with **no maximum**), bucket
  versioning, lifecycle rules.

### MEDIUM-03 — Presign has no ownership check
- **Where**: `services/storage/facade.py:158-162`
- checks `storage.read` capability only; does not authorize the caller for that
  specific key. Combined with CRITICAL-03, knowledge of a key pattern yields
  cross-tenant presigned URLs.

### MEDIUM-04 — Dead configuration and dead code
- `config_profiles/base.yml:611` `resilience.fallbacks.minio` — read by nothing;
  `factory.py` hardcodes the chain.
- `s3.py:215-219` `_wrap_boto` — no call sites, and its body is broken.
- `infrastructure_dsl.py:334,347,356` `_get_real_s3_*` — no call sites.
- `s3_cache.py:47` requires `get_object_bytes`, which `S3ObjectStorage` does not
  implement → the adapter cannot work with the production backend.
- `dsl/builders/eip/sources.py:363-369` `.from_s3(bucket, key, endpoint_url=...)`
  accepts a DSL-controlled endpoint → SSRF-shaped surface.

### LOW-01 — `.env` hygiene
- 3 `FS_*` keys in working-tree `.env`; correctly gitignored (`.gitignore:28`,
  confirmed untracked). No action required.

---

## 4. Cache findings

Cycle 168/170 claimed 13/13 critical/high closed. **Verification: 6 of 8 claims
CONFIRMED, 1 PARTIAL, 1 doc-invalidating.**

### CONFIRMED (cycle 168/170 fixes are real)
| Claim | Evidence |
|---|---|
| Tenant prefix via facade | `cache_processor.py:79` → `services/cache/facade.py:217-226` → `tenant_wrapper.py:72-83`; wrapped at `cache/factory.py:107` |
| `RedisError` widening (ADR-0356) | `cache_processor.py:87-93` |
| MemoryBackend per-key TTL | `memory.py:42-56,82-126` — `_CacheEntry.expires_at` honoured in `set()` |
| DiskCacheBackend TTL sidecar | `disk.py:43,92-151` — `.expires` checked in `get()` |
| memory/disk fallback wrapped | `plugins/composition/service_setup.py:136,148` |
| `core/rate_limiter/` removal (ADR-0353) | removed, **no dangling references** repo-wide |

### HIGH-07 — `delete_by_tag` is NOT cluster-wide; the documented workaround is invalid
- **Where**: `cache/backends/redis.py:107-132`
- All commands target the single connected client. No node fan-out. On
  `RedisCluster` a multi-key `DEL` across hash slots raises `CROSSSLOT`.
- **Contradiction**: `CYCLE_170_PROD_READINESS_2026-10-20.md:48` states
  *"Workaround: используйте `RedisBackend.delete_by_tag` напрямую для
  cluster-wide"*. That workaround does not work. The doc must be corrected.

### HIGH-08 — `DiskCacheBackend.exists()` ignores TTL
- **Where**: `cache/backends/disk.py:189-203`
- `get()` enforces expiry; `exists()` only checks file presence → stale
  `True` for expired keys.

### MEDIUM-05 — `policy.cache_policy()` is metadata-only
- **Where**: `dsl/builders/policy_mixin.py:61-106`
- It appends a `PolicyMarkerProcessor` and touches no backend. `CacheProcessor`
  is never triggered from this path, so callers relying on ADR-0355 as a
  runtime fix silently bypass caching. Real caching requires
  `builder.cache(key_fn=..., ttl=...)`.

### MEDIUM-06 — Unbounded semantic cache
- **Where**: `cache/rag/semantic.py:118-148`
- `SemanticCache._cache` is a plain `dict` with no eviction and no TTL,
  bypassing the TTL that cycle 168 added to `MemoryBackend`. Unbounded growth in
  long-running RAG workers.

### LOW-02 — tenant-prefix flag description contradicts its default
- `core/config/features/sprints_18_21.py:232-241`: field default is `True`
  (isolation ON — the safe direction) while the description says
  *"default-OFF"*. An operator reading it would believe isolation is disabled.

---

## 5. Logging findings

### CRITICAL-04 — Production emits cleartext logs; `use_tls` selects the plaintext path
- **Where**: `logging/backends/graylog_gelf.py:373` (`_send_tcp`),
  `logging/factory.py:276-277`
- Verified causal chain:
  1. `config_profiles/prod.yml:158,167` set `use_tls: true`.
  2. `factory.py:277`: `graylog_protocol = "tcp" if _settings.logging.use_tls else "udp"`.
  3. `graylog_gelf.py:373`: `_send_tcp` opens a raw
     `socket.socket(AF_INET, SOCK_STREAM)`. The file contains **zero**
     references to `ssl`, `create_default_context`, or `starttls` (grep
     confirmed empty).
- **The flag is honored as a protocol selector, never as encryption.** Setting
  `use_tls: true` — the correct security intent — routes traffic to the only
  transport incapable of TLS. Logs carry tenant context and PII.

### HIGH-09 — `logging.basicConfig` in production path
- **Where**: `logging/structlog_backend.py:275`
- Doctrine forbids `logging.basicConfig`; it mutates the root logger globally
  and can discard handlers installed by `init_application_logging()`
  (cycle 168's central init) depending on import order.

### HIGH-10 — R-V15-11 AI workspace TTL cleanup is not wired
- **Where**: `core/ai/workspace_cleaner.py:72`
- `AIWorkspaceCleaner` exists with a `_run_loop`, but `grep -rn
  "AIWorkspaceCleaner" src/` returns only its own docstring and class
  definition. **No instantiation anywhere.** The feature flag defaults `True`
  while nothing runs. A 7-day retention rule is dead.

### LOW-03 — inline `import logging`
- 74 files (not the 83 previously claimed), concentrated on the hot path:
  4 in `entrypoints/middlewares/`, 4 in `dsl/engine/processors/`.

### Verified clean in logging/cache
No `ssl.CERT_NONE`; no `print()`; no `except Exception: pass`; all
`asyncio.create_task` calls registered via `get_task_registry()` per R-V15-11;
no blocking I/O in async paths.

---

## 6. Documentation findings

### DOC-01 — Coverage doc actively misreports S3 as ready (HIGH)
`docs/analysis/storage-coverage-status.md:15` marks S3 ✅ with *"20 (S61
W1+W3)"* unit tests and 5 DSL processors. Both are false: the tests are
skipped, and the processors are unreachable from YAML. This is the document an
operator would trust.

### DOC-02 — No `FS_*` settings documentation exists (MEDIUM)
`grep -rn "FS_PROVIDER\|FS_BUCKET\|FS_ENDPOINT\|FS_ACCESS_KEY" docs/ *.md` → **no
matches**. No documentation of any S3 setting, and fallback semantics are
documented only in source docstrings.

### DOC-03 — Stale copy-paste example in a live docstring (MEDIUM)
`dsl/builders/infrastructure_dsl.py:401` shows `.s3_put("backups/daily.json")`
in a route example. `def s3_put` exists **nowhere** in the codebase — the only
occurrence is the docstring itself.

---

## 7. What was NOT done

- **No live MinIO/KeyDB container proof** — Docker Hub unreachable. Real classes
  and an authentic botocore outage error were used instead; multipart, presign,
  and quota paths under true network failure remain UNVERIFIED.
- **No code modified** — per the change policy agreed in grilling round 1.
- `mutants/tests/unit/storage/*` duplicates of `tests/unit/storage/*` were not
  audited; only the canonical suite was read.

---

## 8. Remediation status (cycle 171 implementation)

Branch: `audit/s3-cache-logging-cycle-171`. Each wave is one commit.

| ID | Finding | Status | Evidence |
|---|---|---|---|
| CRITICAL-01 | Fail-open writes lose data silently | **FIXED** | `a978d3beb` — narrowed catch, ERROR logging, `storage_fallback_total` metric, quarantine registry. 15 regression tests |
| CRITICAL-02 | Tenant quota is dead code | **OPEN** | Deferred: needs facade gate + atomic check; not started |
| CRITICAL-03 | No per-tenant key isolation | **FIXED** | `02db354b9` — `TenantObjectStorage`, 11 tests, factory wires it around the whole chain |
| CRITICAL-04 | Cleartext logs; `use_tls` selects plaintext path | **FIXED** | `9bba00f8a` — real TLS in the sink; 5 tests with a live TLS server |
| CRITICAL-05 | `aioboto3` undeclared | **PARTIAL / BLOCKED** | Cannot be declared (aiobotocore ↔ boto3 1.43.75 conflict). Needs a dependency decision |
| HIGH-07 | `delete_by_tag` not cluster-wide | **PARTIAL** | Cycle-170 doc corrected (`5a2857423`); real fan-out still open |
| HIGH-08 | `DiskCacheBackend.exists()` ignores TTL | **FIXED** | `c8c19b299` |
| HIGH-09 | `logging.basicConfig` in prod path | **FIXED** | `5a2857423` |
| HIGH-10 | AI workspace cleanup never started | **FIXED** | `c8c19b299` — new startup phase; root cause was the missing `start_ai_safety` caller, not the unused cleaner class |
| HIGH-03 | Capability gate silently bypassed | **FIXED** | `48a40ad85` — gate resolved from registry; ungated path now warns |
| HIGH-04 | Credentials never validated | **FIXED (scoped)** | `fd29f9873` — loud ERROR in prod, non-fatal |
| MEDIUM-05 | `policy.cache_policy()` is a marker | Open | Documented; needs ADR |
| MEDIUM-06 | Unbounded semantic cache | Open | — |
| LOW-02 | Flag description vs default | **FIXED** | `5a2857423` |
| LOW-03 | 74 inline `import logging` | Open | Hot-path subset not migrated |
| DOC-01/02/03 | Coverage doc, `FS_*` docs, `.s3_put` | **PARTIAL** | `7d8f07268`, `5a2857423`; `FS_*` reference doc still missing |

**Self-correction recorded**: the Wave 0 commit message claimed a clean deploy
would "silently run on pod-local disk". That was wrong for production and was
retracted in `4505d15d5` — see §3 CRITICAL-05 for the verified scope.

---

## 9. Decision record (grilling, 3 rounds)

| # | Decision | Choice |
|---|---|---|
| 1 | Cache/logging prior verdict | Re-verify all claims against HEAD |
| 2 | S3 breadth | Full stack incl. DSL, tenancy, capability-gate, docs |
| 3 | Change policy | Audit + ranked plan, then wait for go-ahead |
| 4 | Evidence standard | Runtime proof for degradation paths |
| 5 | S3 write failure mode | Fail open **loudly**: metric + alert + quarantine |
| 6 | Graylog TLS | Real TLS in TCP sink + interim prod mitigation |
| 7 | S3 DSL gap | Restore `RouteBuilder` methods |
| 8 | Fix scope | CRITICAL + HIGH + MEDIUM + LOW + docs |
| 9 | `moto` dependency | Add `moto[s3]` to `test-core` |
| 10 | Tenant isolation | Transparent wrapper auto-prefixing `tenant:{id}:/` |
| 11 | Quota enforcement | Facade primary gate + backend safety net |
| 12 | Connection pooling | One shared long-lived `aioboto3.Session` |