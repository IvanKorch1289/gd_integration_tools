# Runbook: Pool warm-up tuning

> Owner: K2.

## Symptom

* Cold-start latency p95 > 50ms на первый запрос после рестарта.
* Grafana `db_pool_health` показывает 0 active connections в первые
  ~100ms жизни pod.

## Detection

```bash
curl -s http://<api>/api/v1/admin/pool-stats | jq
# {"pg": {"size": 0, "max": 10}, "redis": {...}, "clickhouse": {...}}
```

## Diagnosis

PoolWarmup config (`infrastructure/database/pool_warmup.py`):
* `min_connections` (default 3) — сколько connections открыть в startup.
* `timeout_seconds` (default 5.0) — после превышения warmup забрасывается.

Если timeout превышается → warmup-task не сработал → cold start.

## Mitigation

### Option A: увеличить min_connections
```python
# lifecycle.py
await PoolWarmup(
    pg_engine=engine,
    redis_client=redis,
    clickhouse_client=ch,
    min_connections=10,  # было 3
    timeout_seconds=10.0,
).warmup()
```

### Option B: parallel warmup (default)
`PoolWarmup.warmup()` уже выполняет PG/Redis/CH параллельно через
`asyncio.gather`. Проверьте `WarmupResult.failed_pools` для отказавших.

### Option C: disable для CI / dev_light
```bash
export POOL_WARMUP_DISABLED=true
```

## Verification

* p95 первого запроса < 50ms.
* `pool_warmup_duration_seconds` histogram p99 < 5s.
* `WarmupResult.failed_pools == []`.

## Tuning recipe

| Use case | min_connections | timeout_s |
|---|---|---|
| Dev / single replica | 1 | 2.0 |
| Staging | 3 | 5.0 |
| Production (k8s HPA) | 10 | 10.0 |
| Burst pattern (Black Friday) | 30 | 15.0 |

## Failure mode

Если warmup пропускается с `timeout`:

* Не помеха startup — приложение продолжит загрузку (degraded mode).
* Первые запросы пройдут через cold-start lazy connection.
* Восстановление автоматическое после первой нагрузки.
