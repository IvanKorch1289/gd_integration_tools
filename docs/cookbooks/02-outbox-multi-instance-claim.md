# Cookbook #2: Multi-Instance Outbox Claim (Atomicity + Lease)

**Sprint**: S72 (per-row outbox claim + sweeper)
**Audience**: backend engineers, SRE
**Time**: 20 minutes

## Goal

Deploy gd_integration_tools в multi-instance setup (K8s, 3+ replicas)
БЕЗ duplicate outbox message processing. Каждое message processed
exactly once across all instances.

## How it works

```
Instance A          Instance B          Instance C
    |                    |                    |
    |--- claim() ------->|                    |  ← SKIP LOCKED
    |←-- msg[0..99]      |                    |
    |                    |--- claim() ------->|  ← SKIP LOCKED
    |                    |←-- msg[100..199]   |
    |                    |                    |--- claim() → 0 rows
    |                    |                    |
    |--- mark_sent() --->|                    |
    |--- mark_failed() ->|                    |  (release lease)
```

Each claim acquires row-level lock + lease. Other instances see
locked rows и skip them. If instance crashes, lease expires,
sweeper releases stale claims.

## Prerequisites

* PostgreSQL 14+ (SELECT FOR UPDATE SKIP LOCKED support)
* Migrations applied: `cd src/backend/infrastructure/database && alembic upgrade head`

## Step 1: Verify migration applied

```bash
.venv/bin/python -c "
import sqlalchemy as sa
from src.backend.core.config.settings import settings
engine = sa.create_engine(settings.database.url_sync)
with engine.connect() as conn:
    r = conn.execute(sa.text(\"\"\"
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'outbox_messages' AND column_name IN ('claimed_by', 'claimed_at', 'claimed_until')
    \"\"\"))
    print('Claim columns:', [row[0] for row in r])
"
# Expected: ['claimed_at', 'claimed_by', 'claimed_until']
```

## Step 2: Configure outbox worker

In `settings.yaml`:

```yaml
outbox:
  enabled: true
  poll_interval_seconds: 5
  batch_size: 100
  worker_id_source: hostname  # each K8s pod has unique HOSTNAME
  claim_lease_seconds: 300   # 5 min lease (Tune for your latency)
  sweeper_interval_seconds: 60  # 1 min periodic sweeper
```

## Step 3: Run outbox worker

```bash
# Single instance (dev)
.venv/bin/python -m src.backend.workflows.outbox_worker

# Multi-instance (K8s deployment)
# Each pod runs same command — claim() ensures no duplicates
```

## Step 4: Test multi-instance

```python
# 2 workers, concurrent claim():
import asyncio
from src.backend.infrastructure.repositories.outbox import claim_pending, mark_sent

async def worker(worker_id: str, results: list) -> None:
    while True:
        msgs = await claim_pending(limit=10, worker_id=worker_id, lease_seconds=60)
        if not msgs:
            break
        for msg in msgs:
            # Process msg
            await mark_sent(msg.id)

asyncio.run(asyncio.gather(worker("worker_a", []), worker("worker_b", [])))
# Expected: total processed = total pending, no duplicates
```

## Verification

```bash
# Test 1: Single instance, claim all
.venv/bin/python -c "
import asyncio
from src.backend.infrastructure.repositories.outbox import claim_pending, count_pending
async def t():
    n_pending = await count_pending()
    msgs = await claim_pending(limit=n_pending + 10, worker_id='test')
    print(f'Claimed {len(msgs)} of {n_pending}')
asyncio.run(t())
"
# Expected: Claimed == n_pending (all)

# Test 2: Concurrent workers, no duplicates
.venv/bin/python -m pytest tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py -q
# Expected: 5/5 tests pass

# Test 3: Sweeper releases stale claims
# Wait 60+ seconds, then check processing rows
```

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `psycopg2.errors.UndefinedColumn` | Migration not applied | `alembic upgrade head` |
| All workers get 0 rows | `worker_id` not unique / lease not expired | Check HOSTNAME env, lower `claim_lease_seconds` |
| Duplicate processing | `mark_sent` doesn't clear claim | Verify `mark_sent` clears `claimed_by/at/until` |
| Stale "processing" rows | Sweeper not running | Verify `sweeper_interval_seconds` > 0, worker alive |

## Related

- **ADR-0154**: Sprint 72 closure (per-row claim + sweeper)
- **Tooling**: `tools/check_outbox_health.py` (WIP)
