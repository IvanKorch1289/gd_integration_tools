# Object Storage (S3 / MinIO / LocalFS) — configuration and failure behaviour

**Cycle**: 171 (audit 2026-10-21)
**Code**: `src/backend/infrastructure/storage/`, `src/backend/core/config/services/storage.py`

This document exists because `FS_*` settings were previously documented
**nowhere** — `grep -rn "FS_PROVIDER\|FS_BUCKET\|FS_ENDPOINT" docs/ *.md`
returned no matches, while object storage is a Tier-1 subsystem with real
data-loss failure modes.

---

## 1. Settings reference

Model: `FileStorageSettings` (`core/config/services/storage.py`),
`env_prefix="FS_"`, `extra="forbid"`.

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `enabled` | `FS_ENABLED` | `true` | Master switch |
| `provider` | `FS_PROVIDER` | **required** | `minio` \| `aws` \| `other` \| `local`. `local` → `LocalFSStorage` alone; anything else → S3 chain |
| `bucket` | `FS_BUCKET` | `my-bucket` | Object bucket |
| `endpoint` | `FS_ENDPOINT` | **required** | S3/MinIO endpoint |
| `interface_endpoint` | `FS_INTERFACE_ENDPOINT` | **required** | Console/UI URL |
| `use_ssl` | `FS_USE_SSL` | **required** | Must be `true` in production |
| `verify` | `FS_VERIFY` | **required** | TLS certificate verification. Never set `false` in production |
| `ca_bundle` | `FS_CA_BUNDLE` | `None` | Path to CA bundle for private CAs |
| `access_key` | `FS_ACCESS_KEY` | `""` | **Empty means anonymous** — see §4 |
| `secret_key` | `FS_SECRET_KEY` | `""` | **Empty means anonymous** — see §4 |
| `key_prefix` | `FS_KEY_PREFIX` | `uploads` (base.yml) | Prefix inside the bucket. **Not** the tenant segment — see §5 |
| `timeout` | `FS_TIMEOUT` | `30` (base.yml) | Connect timeout, seconds |
| `read_timeout` | `FS_READ_TIMEOUT` | `30` (base.yml) | Read timeout, seconds |
| `retries` | `FS_RETRIES` | `5` (base.yml) | Adaptive retry attempts |
| `max_pool_connections` | `FS_MAX_POOL_CONNECTIONS` | `20` (base.yml) | See the caveat in §6 |
| `local_storage_path` | `FS_LOCAL_STORAGE_PATH` | `dev_storage` | Only used when `provider=local` |

### Profile defaults

| Profile | provider | endpoint | use_ssl | verify |
|---|---|---|---|---|
| `prod` | `aws` | `https://s3.prod.local` | `true` | `true` |
| `staging` | `minio` | `https://minio-staging:9000` | `true` | `true` |
| `dev` | `minio` | `http://127.0.0.1:9090` | `false` | `false` |
| `dev_light` | `local` | — | — | — |

**No profile defines `access_key`/`secret_key`.** Credentials are supplied
through environment variables at deploy time — that is correct practice, but
it means nothing validates that they arrived (see §4).

---

## 2. Composition

`storage/factory.py::get_object_storage()` (singleton, `lru_cache`):

```text
provider == "local"  →  LocalFSStorage
otherwise            →  TenantObjectStorage(
                            FallbackObjectStorage(
                                primary   = S3ObjectStorage(fs_settings),
                                secondary = LocalFSStorage(...)))
```

Tenant key scoping is applied by the **outermost** layer, so both the S3
primary and the LocalFS fallback receive identical scoping.

---

## 3. Failure behaviour (this is the part that matters)

### On S3 outage

Writes **fail open** — the call succeeds and the object lands on pod-local
disk. This is deliberate (availability), but it is now loud:

| Signal | Behaviour |
|---|---|
| Log level | `ERROR` for writes (data at risk), `WARNING` for reads |
| Message | Explicitly names that data is on a temporary carrier |
| Metric | `storage_fallback_total{chain,operation,severity}` |
| Quarantine | `FallbackObjectStorage.quarantined` — objects needing re-upload |

**Pod eviction destroys quarantined data.** Drain the quarantine
(`drain_quarantine()`) once S3 recovers, and re-upload it.

### Which errors trigger fallback

`DEFAULT_FALLBACK_EXCEPTIONS = (ServiceError, OSError)` — infrastructure
failures only. A `ValueError`, `TypeError` or `KeyError` in caller code now
**propagates** instead of being persisted as a fake success. It was
`(Exception,)` before cycle 171.

Widen it explicitly if you need to:

```python
FallbackObjectStorage(primary, secondary,
                      fallback_exceptions=DEFAULT_FALLBACK_EXCEPTIONS + (MyErr,))
```

### On misconfiguration

| Environment | Behaviour |
|---|---|
| `production` | `ProductionConfigError` at composition root — the deploy fails to start |
| `staging` / `dev` | Silent degradation to bare `LocalFSStorage` with a `WARNING` |

Staging degrading silently is the main residual risk: it looks healthy while
providing no object storage. Watch for the warning, or run staging with
`APP_ENVIRONMENT=production` for storage checks.

---

## 4. Credentials

Empty `FS_ACCESS_KEY`/`FS_SECRET_KEY` means an **anonymous** client. Nothing
validates that they were provided, so a typo produces a silently anonymous
client rather than a startup failure.

Cycle 171 added `FileStorageSettings.has_credentials()` and a factory check
that logs at `ERROR` in production, `WARNING` elsewhere. It is deliberately
**non-fatal** so environments relying on a public/anonymous bucket keep
working. Making it fatal is a separate policy decision.

---

## 5. Tenant isolation

`TenantObjectStorage` prefixes every key with `tenants/{tenant_id}/`, reading
the tenant from the request `ContextVar`. Objects written outside a tenant
context go to `tenants/_unscoped_/`.

`list_keys` applies the prefix to the pattern and strips it from results, so
callers see the same tenant-free keys they passed in.

`FS_KEY_PREFIX` is **not** the tenant segment. It is a static prefix applied by
`S3ObjectStorage` underneath the tenant layer.

---

## 6. Known limitations

- **`aioboto3` is not declared** in `pyproject.toml`/`uv.lock`. `aiobotocore`
  pins `boto3` to ranges incompatible with the `1.43.75` in `uv.lock`, and the
  index offers only `aioboto3 <= 13.0.1`. Production fails fast (see §3);
  staging degrades silently.
- **`max_pool_connections` is effectively dead.** A client is constructed and
  torn down per operation (`s3.py:_S3Session.__aenter__`), so the pool does not
  survive the call. Fixing this requires `aioboto3` to be importable.
- **No server-side encryption, ACL, versioning or lifecycle settings exist.**
- **`presigned_url` has no maximum TTL** and `StorageFacade` checks only the
  `storage.read` capability, not authorisation for that specific key.
- `config_profiles/base.yml::resilience.fallbacks.minio` is read by nothing —
  the chain is hardcoded in `factory.py`.

---

## 7. DSL surface

Five steps are available from YAML and from the Python builder:

```yaml
steps:
  - to_s3:      { key_from: "doc_key", data_property: "body" }
  - s3_list:    { prefix_from: "uploads/" }
  - s3_get:     { key_from: "s3_key", result_property: "file_body" }
  - s3_presign: { key_from: "s3_key", expires_in: 900 }
  - s3_delete:  { key_from: "s3_key" }
```

> The read step is `s3_get`, **not** `from_s3`. `from_s3` is the S3 *poll
> sensor* (`SourcesEIPsMixin`) and means something else entirely; both are
> pinned by tests so the semantics cannot drift.

Per-tenant quota is enforced at the `StorageFacade` gate. It runs
**alert-only** by default (`storage.enforce_quota=false`): breaches log at
`ERROR` and increment `storage_quota_violation_total` but do not block. Review
the distribution before enabling enforcement.