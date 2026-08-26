# Local Redis Sentinel — Development Stack (S60 W1)

> **Purpose**: Local development environment for Redis Sentinel HA testing.
> Enables verification of Sentinel failover WITHOUT depending on infra team
> provisioning production Sentinel.

## Quick Start

```bash
# Start local Sentinel stack (master + replica + 3 sentinels)
cd /home/user/dev/gd_integration_tools
docker compose -f ops/compose/docker-compose.redis-sentinel.yml up -d

# Wait for all containers healthy (~10s)
docker compose -f ops/compose/docker-compose.redis-sentinel.yml ps

# Verify sentinel sees the master
docker compose -f ops/compose/docker-compose.redis-sentinel.yml exec sentinel-0 \
  redis-cli -p 26379 SENTINEL masters
```

## Architecture

```
┌──────────────────┐
│ redis-master     │ ← master (read/write)
│ :6379            │
└──────────────────┘
        │ async replication
        ↓
┌──────────────────┐
│ redis-replica    │ ← replica (read-only)
│ :6379 (host 6380)│
└──────────────────┘

3× Sentinel processes (quorum 2/3):
- sentinel-0: :26379 (host 26379)
- sentinel-1: :26380 (host 26380)
- sentinel-2: :26381 (host 26381)
```

## App Configuration

Set environment variables for the app:

```bash
# Enable Sentinel mode
export REDIS_SENTINEL_MODE=true
export REDIS_SENTINEL_NODES=sentinel-0:26379,sentinel-1:26379,sentinel-2:26379
export REDIS_SENTINEL_SERVICE_NAME=gd-mobile-redis
export REDIS_PASSWORD=redis-dev-password  # for Sentinel auth-pass
export REDIS_HOST=redis-master            # initial master (Sentinel auto-discovers)
export REDIS_PORT=6379
```

Or via `config_profiles/dev.yml`:

```yaml
redis:
  enabled: true
  host: redis-master
  port: 6379
  password: redis-dev-password
  use_ssl: false
  sentinel_mode: true
  sentinel_nodes:
    - sentinel-0:26379
    - sentinel-1:26379
    - sentinel-2:26379
  sentinel_service_name: gd-mobile-redis
  sentinel_password: redis-dev-password
```

## Testing Failover

### Manual failover (controlled)

```bash
# 1. Verify master is up
docker compose -f ops/compose/docker-compose.redis-sentinel.yml exec redis-master \
  redis-cli -a redis-dev-password ping
# Expected: PONG

# 2. Trigger failover (via Sentinel 0)
docker compose -f ops/compose/docker-compose.redis-sentinel.yml exec sentinel-0 \
  redis-cli -p 26379 SENTINEL FAILOVER gd-mobile-redis
# Expected: OK (within seconds)

# 3. Verify new master elected
docker compose -f ops/compose/docker-compose.redis-sentinel.yml exec sentinel-0 \
  redis-cli -p 26379 SENTINEL get-master-addr-by-name gd-mobile-redis
# Expected: <new-master-ip> 6379 (may still be redis-master if Sentinel
# decided not to swap, or may be different)

# 4. App reconnects automatically via +switch-master pub/sub
# Verify with:
curl http://localhost:8000/api/v1/admin/health | jq .redis
```

### Hard kill (chaos testing)

```bash
# Kill master container
docker compose -f ops/compose/docker-compose.redis-sentinel.yml kill redis-master

# Watch sentinels elect new master (typically <30 seconds)
docker compose -f ops/compose/docker-compose.redis-sentinel.yml logs -f sentinel-0

# Verify app reconnects
curl http://localhost:8000/api/v1/admin/health | jq .redis
# After ~30s should show {"status": "ok"} again

# Restart master (optional)
docker compose -f ops/compose/docker-compose.redis-sentinel.yml up -d redis-master
```

## CI Integration

In CI pipeline:

```yaml
# .github/workflows/sentinel-integration.yml (example)
- name: Start local Sentinel stack
  run: docker compose -f ops/compose/docker-compose.redis-sentinel.yml up -d
- name: Wait for health
  run: sleep 15
- name: Run integration tests
  run: |
    REDIS_SENTINEL_MODE=true \
    REDIS_SENTINEL_NODES=sentinel-0:26379,sentinel-1:26379,sentinel-2:26379 \
    REDIS_SENTINEL_SERVICE_NAME=gd-mobile-redis \
    REDIS_PASSWORD=redis-dev-password \
    uv run pytest tests/integration/redis_sentinel/ -v
- name: Stop stack
  run: docker compose -f ops/compose/docker-compose.redis-sentinel.yml down -v
```

## Cleanup

```bash
# Stop stack
docker compose -f ops/compose/docker-compose.redis-sentinel.yml down

# Stop + remove volumes (wipe state)
docker compose -f ops/compose/docker-compose.redis-sentinel.yml down -v
```

## Differences from Production

| Setting | Local Dev | Production |
|---|---|---|
| `protected-mode` | no | yes (firewall-restricted) |
| TLS (SSL) | no | yes (use_ssl=true) |
| Sentinel passwords | `redis-dev-password` | vault-stored random |
| Resource limits | none (compose defaults) | k8s limits set |
| Health check | 5s interval | 10-30s interval |
| Sentinel down-after | 5s | 30s+ |

## Production Deployment

For production Sentinel deployment specs, see
`docs/security/REDIS_HA_INFRASTRUCTURE_REQUIREMENTS.md`.

## References

- `docs/security/REDIS_HA_INFRASTRUCTURE_REQUIREMENTS.md` — production Sentinel specs
- `docker-compose.redis-sentinel.yml` — this stack definition
- `redis/sentinel/master.conf`, `replica.conf`, `sentinel.conf` — configs
- `src/backend/core/config/services/cache.py` — RedisSettings (S59 W2 Sentinel fields)
- `src/backend/infrastructure/clients/storage/redis/connection_mixin.py` — _build_client
