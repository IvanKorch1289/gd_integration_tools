# Redis HA Infrastructure — Requirements & Deployment Patterns

> **Purpose**: Concrete infrastructure requirements for production Redis
> deployment. Provides exact env vars, validation rules, and topology
> patterns. Bridges code (S59 W2 Sentinel support) and infra team
> provisioning.
>
> **Audience**: DevOps, infra team, backend team.
> **Status**: READY (S59 W2 adds Sentinel support — both Cluster and Sentinel
> topologies now supported in code).

## Overview

Production Redis deployment requires HA (High Availability) infrastructure.
The codebase supports **two HA topologies**:

1. **Sentinel** (master-replica failover, simpler) — RECOMMENDED for most cases
2. **Cluster** (sharding + replication, complex) — for high-throughput scenarios

Both topologies are configured via `RedisSettings` (see
`src/backend/core/config/services/cache.py`).

## Code Support Status (S59 W2)

| Topology | Code Support | Since | Use Case |
|---|---|---|---|
| **Single instance** | ✅ Always | (baseline) | dev/test only |
| **Sentinel (HA failover)** | ✅ **S59 W2** | This sprint | Production (RECOMMENDED) |
| **Cluster (sharding + HA)** | ✅ Pre-S59 | Sprint 0 | High-throughput / large datasets |

**Validation rule**: `cluster_mode` and `sentinel_mode` are mutually exclusive
(per `RedisSettings._check_cluster_consistency`).

## Topology 1: Redis Sentinel (RECOMMENDED)

### What is Sentinel?

Redis Sentinel is a distributed system that:
- Monitors master + replicas
- Automatically promotes replica to master on failure
- Provides client discovery via `+switch-master` pub/sub
- 3+ Sentinel nodes for quorum (avoid split-brain)

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Application (gd-integration-tools pods)                       │
│   ↓                                                           │
│   Sentinel client (Sentinel.master_for service_name)         │
│   ↓ auto-reconnect on failover                                │
└─────────────────────────────────────────────────────────────┘
            ↓                ↓                ↓
    ┌──────────┐       ┌──────────┐       ┌──────────┐
    │Sentinel 0│       │Sentinel 1│       │Sentinel 2│
    │:26379    │       │:26379    │       │:26379    │
    └────┬─────┘       └────┬─────┘       └────┬─────┘
         │                │                │     (quorum: 2/3)
         └────────────────┼────────────────┘
                          ↓ monitor + election
              ┌────────────────────────┐
              │   Master (read/write)  │   ← auto-failover target
              │   :6379               │
              └───────────┬───────────┘
                          ↓ async replication
              ┌────────────────────────┐
              │ Replica (read-only)    │
              │ :6379                  │
              └────────────────────────┘
```

### Required Configuration (env vars / values.yaml)

```yaml
redis:
  enabled: true
  host: redis-master.gd-integration.svc.cluster.local  # initial master (Sentinel auto-discovers)
  port: 6379
  password: "<vault-secret-redis-password>"
  use_ssl: true
  ca_bundle: /etc/ssl/ca-bundle.crt

  # Sentinel-specific (S59 W2)
  sentinel_mode: true
  sentinel_nodes:
    - sentinel-0.gd-integration.svc.cluster.local:26379
    - sentinel-1.gd-integration.svc.cluster.local:26379
    - sentinel-2.gd-integration.svc.cluster.local:26379
  sentinel_service_name: gd-mobile-redis
  sentinel_password: "<vault-secret-sentinel-password>"  # optional, if Sentinel ACL enabled
```

### Infrastructure Provisioning Checklist

- [ ] **3+ Sentinel nodes** deployed (minimum for quorum)
- [ ] **1 master + N replicas** (recommend 2+ replicas for HA)
- [ ] **Sentinel monitors master** via `SENTINEL MONITOR gd-mobile-redis <master-ip> 6379 2`
  (quorum = 2 votes for failover decision)
- [ ] **DNS records** for master and sentinels (or use k8s service abstraction)
- [ ] **TLS certificates** if `use_ssl=true` (mount via Vault or k8s secret)
- [ ] **Network policies**: allow app pods to reach Sentinel (26379) and master (6379)
- [ ] **Monitoring**: Prometheus Sentinel exporter (e.g., `redis_sentinel_exporter`)
- [ ] **Backup strategy**: master + replicas should be backed up separately

### Failover Behavior

When master fails:
1. Sentinel detects (within seconds)
2. Sentinel quorum votes on promotion
3. New master promoted (typically <30 seconds)
4. App receives `+switch-master` notification
5. `redis-py` master_for() client reconnects to new master
6. Operations resume automatically (transparent to app)

**App-level behavior**: `record_circuit_breaker_state()` metric reflects any
Redis errors during failover window. Circuit breaker may trip if failover takes >5s,
but resets automatically when Redis becomes available.

## Topology 2: Redis Cluster (ADVANCED)

### What is Cluster?

Redis Cluster provides:
- **Sharding**: data partitioned across 6+ nodes (3 master + 3 replicas minimum)
- **Replication**: each master has 1+ replicas
- **Automatic failover**: like Sentinel, but per-shard

### When to Use

- Dataset > Redis single-instance memory limit (~25GB practical)
- Throughput > 100K ops/sec
- Need horizontal scaling (more shards = more capacity)

### Required Configuration

```yaml
redis:
  enabled: true
  use_ssl: true

  # Cluster-specific (Sprint 0)
  cluster_mode: true
  cluster_nodes:
    - redis-cluster-0.gd-integration.svc.cluster.local:6379
    - redis-cluster-1.gd-integration.svc.cluster.local:6379
    - redis-cluster-2.gd-integration.svc.cluster.local:6379
    - redis-cluster-3.gd-integration.svc.cluster.local:6379
    - redis-cluster-4.gd-integration.svc.cluster.local:6379
    - redis-cluster-5.gd-integration.svc.cluster.local:6379
```

### Important Constraints

- **All keys must be hash-tagged** for multi-key operations: `{user:123}:profile`
- **No multi-database**: `db_cache/db_queue/db_limits` IGNORED in cluster mode
- **Cross-slot operations** (like `MGET` on different tags) are slower

## Deployment Validation

### After Provisioning

```bash
# 1. Sentinel check (from app pod)
redis-cli -h sentinel-0 -p 26379 SENTINEL masters
# Expected: list of monitored masters including gd-mobile-redis

# 2. Master reachable
redis-cli -h redis-master -p 6379 PING
# Expected: PONG

# 3. Failover test (CAREFUL — causes brief unavailability)
redis-cli -h sentinel-0 -p 26379 SENTINEL FAILOVER gd-mobile-redis
# Expected: OK, new master promoted within seconds

# 4. App reconnects automatically
curl https://api.example.com/mobile/v1/health
# Expected: 200 OK (after brief errors during failover)
```

### App-Side Verification

```bash
# Check Redis metric: circuit_breaker_state
curl http://prometheus:9090/api/v1/query?query=circuit_breaker_state
# Expected: state=0 (closed) under normal ops

# Check Redis health
curl https://api.example.com/api/v1/admin/health | jq .redis
# Expected: {"status": "ok", "error": null}
```

## Connection String Reference

### Sentinel Connection String (internal, NOT exposed via REDIS_URL)

Sentinel mode uses `sentinel_nodes` + `sentinel_service_name`, NOT a single
URL. The `redis.asyncio.sentinel.Sentinel` API:
```python
sentinel = Sentinel(
    [("sentinel-0", 26379), ("sentinel-1", 26379)],
    password="...",
)
client = sentinel.master_for(service_name="gd-mobile-redis", db=0)
```

### Cluster Connection String

```python
RedisCluster(
    startup_nodes=[
        ClusterNode(host="redis-0", port=6379),
        ClusterNode(host="redis-1", port=6379),
    ],
    password="...",
)
```

### Single Instance (dev/test)

```yaml
redis:
  host: localhost
  port: 6379
  password: null
```

## References

- `src/backend/core/config/services/cache.py` — RedisSettings (S59 W2 + pre-S59 Cluster)
- `src/backend/infrastructure/clients/storage/redis/connection_mixin.py` — _build_client with all 3 paths
- `docs/security/MOBILE_JWT_PRODUCTION_FLIP_RUNBOOK.md` — uses this for Redis HA
- `docs/security/S13_PHASE4_STAGING_ROLLOUT_RUNBOOK.md` — uses this for Redis HA
- `ops/compose/docker-compose.redis-sentinel.yml` — local Sentinel stack for dev/CI (S60 W2)
- `tests/integration/redis_sentinel/` — Docker-gated integration tests (S60 W3)
- `.github/workflows/sentinel-integration.yml` — CI integration workflow (S61 W1)
- `deploy/helm/gd-integration-tools/values-sentinel.example.yaml` — production Helm values template (S61 W2)
- redis-py docs: https://redis-py.readthedocs.io/en/stable/connections.html
- Redis Sentinel docs: https://redis.io/docs/management/sentinel/
- Redis Cluster docs: https://redis.io/docs/management/scaling/

## Sign-off

| Role | Name | Date | Status |
|---|---|---|---|
| Infra team lead | TBD | | Pending — provisioning |
| DevOps | TBD | | Pending — deployment |
| Backend team | Kimi Code (S59 W2) | 2026-08-25 | Sentinel support ✅ |

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-08-25 | Initial infra requirements doc + Sentinel code support | Kimi Code (S59 W2) |
| 2026-08-25 | Local Sentinel Docker stack + integration tests | Kimi Code (S60) |
| 2026-08-25 | GitHub Actions workflow + Helm values template | Kimi Code (S61) |
| TBD | Sentinel provisioning | Infra team |
| TBD | Production deployment | DevOps |
