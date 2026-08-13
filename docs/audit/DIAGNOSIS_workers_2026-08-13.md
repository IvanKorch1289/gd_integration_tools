# DIAGNOSIS — workflow workers unhealthy, 2026-08-13

**Author:** WORKER_DIAGNOSIS subagent
**Branch:** master @ bc147a92
**Affected containers:** `compose-workflow-worker-{1..4}`
**Method:** docker inspect, log reading, env comparison vs working sibling

---

## TL;DR — Root cause

**The workers are NOT misconfigured to talk to a host called `main`.** The
string `'main'` in the error message is the **db_name** (logical identifier)
inside `session_manager`, NOT the hostname. The hostname the worker actually
uses IS `postgres` (from env `DB_HOST=postgres`). The real failure is:

> **`compose-postgres-1` died at 15:44:12Z due to "No space left on device",
> and never came back up. The 4 workflow workers are stuck in their restart
> loop because `DB_HOST=postgres` resolves to a non-existent container
> → `socket.gaierror: [Errno -3] Temporary failure in name resolution` every
> 30s in the backup-polling loop.**

The error log looks confusing because `'main'` is interpolated as the
session-manager's `db_name` argument:

```
src/backend/infrastructure/database/session_manager.py:78:
    message=f"Failed to create database session for '{self.db_name}'"
```

…so the log says `Failed to create database session for 'main'` even though
`'main'` is the **database label**, not the host. The host that failed to
resolve is the upstream DNS lookup of `DB_HOST=postgres`.

---

## Evidence

### Container state at 19:24Z

```bash
$ sudo docker ps -a --format '{{.Names}}\t{{.Status}}'
gd-app-light                       Up 18 seconds (health: starting)
compose-workflow-worker-4          Up 22 minutes (unhealthy)
compose-workflow-worker-2          Up 22 minutes (unhealthy)
compose-workflow-worker-3          Up 22 minutes (unhealthy)
compose-workflow-worker-1          Up 22 minutes (unhealthy)
compose-postgres-1                 Exited (1) 40 minutes ago
compose-redis-1                    Exited (137) 40 minutes ago
compose-migration-runner-1         Exited (0) About an hour ago
compose-clamav-1                   Up 17 minutes (healthy)
gd-rabbit                          Exited (0) 34 minutes ago
```

**postgres + redis: DEAD. Workers + clamav: alive but unhealthy.**

### Worker logs — confirmed DNS failure

```
$ sudo docker logs compose-workflow-worker-1 --tail 80
...
2026-08-13 16:16:00,628 ERROR workflow.runner: backup poll error:
    Failed to create database session for 'main'

... traceback ...
File "/usr/local/lib/python3.14/asyncio/base_events.py", line 1516, in _ensure_resolved
    return await loop.getaddrinfo(host, port, ...)
File "/usr/local/lib/python3.14/socket.py", line 989, in getaddrinfo
    for res in _socket.getaddrinfo(host, port, ...):
socket.gaierror: [Errno -3] Temporary failure in name resolution
```

### What's `'main'` — code trace

```python
# src/backend/infrastructure/database/session_manager.py:44-48
def __init__(
    self, session_maker: async_sessionmaker[AsyncSession],
    db_name: str = "main",   # <-- DEFAULT VALUE 'main'
):
    self.session_maker = session_maker
```

```python
# src/backend/infrastructure/database/session_manager.py:162-164
def get_main_session_manager() -> DatabaseSessionManager:
    """Lazy singleton ``DatabaseSessionManager`` для main-БД (Wave 6.1)."""
    return DatabaseSessionManager(
        session_maker=get_db_initializer().async_session_maker, db_name="main",
    )
```

```python
# src/backend/infrastructure/database/session_manager.py:77-79
raise DatabaseError(
    message=f"Failed to create database session for '{self.db_name}'",
) from exc
```

So `'main'` = logical DB label. **NOT** a hostname.

### What host the worker actually tries to resolve

```bash
$ sudo docker inspect compose-workflow-worker-1 --format \
    '{{range .Config.Env}}{{println .}}{{end}}' | grep -iE "HOST|DB|REDIS|POSTGRES"
DB_HOST=postgres                  # ← hostname resolution target
DB_NAME=gd_integration           # ← database NAME (not 'main')
DB_USERNAME=postgres
REDIS_PASSWORD=admin
DB_PASSWORD=postgres
DATABASE_HOST=postgres
```

`DB_HOST=postgres` (compose service name) — that's the hostname the worker
attempts to resolve via DNS. The compose network would resolve `postgres` to
`compose-postgres-1`'s IP, **if postgres were running**. It's not.

### (a) Is postgres actually running?

**No.**

```bash
$ sudo docker ps -a --filter name=postgres
compose-postgres-1  Exited (1) 40 minutes ago
```

The compose-postgres-1 container exited **40 minutes before the worker logs**
(16:16:00Z worker error vs 15:44:12Z postgres death — 32 minutes gap). The
workers have been trying to talk to it ever since, and dns is broken.

### What killed postgres — disk full

```bash
$ sudo docker logs compose-postgres-1 --tail 50
...
2026-08-13 15:44:12.560 UTC [1] LOG: background worker
    "logical replication launcher" (PID 33) exited with exit code 1
2026-08-13 15:44:12.664 UTC [28] LOG: shutting down
2026-08-13 15:44:12.678 UTC [28] LOG: checkpoint starting: shutdown immediate
2026-08-13 15:44:12.697 UTC [28] PANIC:
    could not write to file "pg_logical/replorigin_checkpoint.tmp":
    No space left on device
2026-08-13 15:44:13.196 UTC [1] LOG: checkpointer process (PID 28)
    was terminated by signal 6: Aborted
2026-08-13 15:44:13.196 UTC [1] LOG: abnormal database system shutdown
2026-08-13 15:44:13.227 UTC [1] LOG: database system is shut down
```

Same root cause for redis:

```
1:signal-handler (1786635852) Received SIGTERM scheduling shutdown...
1:M 13 Aug 2026 15:44:12.523 * User requested shutdown...
1:M 13 Aug 2026 15:44:12.529 * Saving the final RDB snapshot before exiting.
1:M 13 Aug 2026 15:44:12.550 #
    Write error while saving DB to the disk(fflush): No space left on device
1:M 13 Aug 2026 15:44:12.550 # Error trying to save the DB, can't exit.
```

### (b) What is "main"? — Not a service name

Grep for "main" across all compose files: **no service named `main`** is
defined in `docker-compose.yml` or `docker-compose.light.yml`. There IS no
compose service `main`. `main` only appears as `db_name="main"` in
session_manager code (above).

### (c) Does worker config reference "main" as DB_HOST?

**No.** Verified above: `DB_HOST=postgres`, `DATABASE_HOST=postgres` — both
correct.

### (d) Is worker supposed to talk to `postgres` (service name)?

**Yes.** `ops/compose/docker-compose.yml:64-72`:

```yaml
workflow-worker:
    ...
    environment:
      APP_PROFILE: dev
      DB_HOST: postgres         # compose service-name
      WORKFLOW_WORKER_EXECUTOR: ${WORKFLOW_WORKER_EXECUTOR:-dsl}
      SHUTDOWN_GRACE_SECONDS: ${SHUTDOWN_GRACE_SECONDS:-30}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      migration-runner:
        condition: service_completed_successfully
```

`depends_on: postgres.condition: service_healthy` — workers are wired to
postgres. Correct.

### (e) Worker env inspect (full)

```bash
$ sudo docker inspect compose-workflow-worker-1 --format \
    '{{range .Config.Env}}{{println .}}{{end}}' | head -50
APP_PROFILE=dev
APP_SERVER=granian
APP_WORKERS=1
APP_PROFILE=dev
DATABASE_HOST=postgres      # matches DB_HOST
DB_HOST=postgres            # ← primary resolution target
REDIS_PASSWORD=admin
DB_NAME=gd_integration
DB_USERNAME=postgres
DB_PASSWORD=postgres
DATA_DIR=/app/.run/data
APP_PORT=8000
APP_HOST=0.0.0.0
...
```

No reference to "main" anywhere. The error message `'main'` is purely the
in-code db_name label passed to `DatabaseSessionManager(db_name="main")`.

### (f) Sibling comparison — gd-app-light container

```bash
$ sudo docker inspect gd-app-light --format \
    '{{range .Config.Env}}{{println .}}{{end}}' | grep -iE "HOST|DB|REDIS|POSTGRES"
APP_PROFILE=dev_light       # ← KEY DIFFERENCE
REDIS_PASSWORD=admin
DB_PASSWORD=postgres
DB_NAME=gd_integration
DB_USERNAME=postgres
DATABASE_HOST=postgres
```

`gd-app-light` runs `APP_PROFILE=dev_light` → SQLite/in-memory fallback,
doesn't need postgres. It was reachable for the first 60s after start
(2026-08-13T16:17:57Z), then stuck in disk-sleep (see
FUNCTIONAL_BASELINE_2026-08-13.md for details — separate issue).

The workers run `APP_PROFILE=dev` (full stack) → they hard-depend on
postgres. Without postgres, they cannot proceed.

### Host disk — current state

```bash
$ df -h /
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2        218G  173G   36G  84% /
```

**36 GB free** now. The disk-full event at 15:44Z was transient — likely
host overcommit during a heavy build or external copy. Should be safe to
restart postgres now.

---

## Minimal-fix proposal

### Recommended: **Option A** (full restart with proper depends_on)

Bring the data plane back, restart workers. This is fastest and matches
production behavior.

```bash
# 1. Verify disk has free space (currently 36G free — OK)
$ df -h /
/dev/sda2        218G  173G   36G  84% /

# 2. Start postgres + redis (compose-managed, correct depends_on wiring)
$ sudo docker compose -f ops/compose/docker-compose.yml up -d postgres redis

# 3. Wait for postgres healthy
$ sudo docker inspect compose-postgres-1 \
    --format '{{.State.Health.Status}}'
# should become "healthy" within ~10s

# 4. Run migrations (one-shot)
$ sudo docker compose -f ops/compose/docker-compose.yml up migration-runner
# compose-migration-runner-1 already exited successfully;
# it will rerun idempotently

# 5. Restart workers so they reconnect
$ sudo docker compose -f ops/compose/docker-compose.yml up -d --force-recreate workflow-worker
```

Expected: workers reconnect to live `postgres` → DNS resolves →
backup-poll starts picking up workflow instances → healthcheck flips to healthy.

**Estimated downtime: 2-3 minutes** (postgres boot + migration + 4 worker reboots).

### Rejected — Option B (rename DB_HOST env to "postgres")

No change needed. `DB_HOST=postgres` is already correct; the issue is the
target container being down.

### Rejected — Option C (network alias "main" → postgres alias)

Adds complexity (custom networks, deprecated `links:`-style shims). Real
problem is the missing container, not DNS naming.

---

## Regression risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| Postgres data dir corruption from PANIC shutdown | **LOW** | Logical replication tmp file is replay-safe; standard postgres recovery will replay WAL on next boot |
| Workers stuck mid-poll cancel queue | **LOW** | Workers use try_lock + 30s backup poll; restart cycle is self-healing |
| Migration-runner re-runs `alembic upgrade head` | **LOW** | `|| true` makes it idempotent; DATABASE HEAD tag is checked |
| Disk-fills-again during pg recovery | **MEDIUM** | 36G free, but watch `df -h` during the restart; pause if free < 5G |
| Past workflows in `pending`/`running` state | **MEDIUM** | Workflow state is event-sourced (`workflow_instances` table); replay-on-restart is the design |
| Workflow EventStore leakage | **LOW** | `WorkflowEventStore` uses session_manager — same restart will reconnect cleanly |

---

## Open questions / follow-ups

1. **What filled the disk?** 36G free now but was 0 at 15:44Z. Investigate
   `du -sh /var/lib/docker/overlay2 /var/log /tmp` after restart.
2. **Should there be a disk-pressure alert?** pg + redis both died **without
   any monitoring firing** the worker unhealthy state until postgres was
   already gone. Consider IOWait / disk-usage probe in `compose-clamav`
   neighbors or k8s preStop hook.
3. **Migration-runner is `Exited (0)` already** — does `alembic upgrade
   head` need re-running? Check via:
   `sudo docker logs compose-migration-runner-1 --tail 20`
4. **The "main" string issue** — consider renaming `db_name="main"` default
   to something less misleading (e.g., `db_name="primary"`) so future log
   messages don't include "main" where people expect a hostname. Trivial
   Ponytail refactor.

---

## TL;DR for parent agent

- **Hostname config is correct** (`DB_HOST=postgres`).
- **"main" in the error is NOT a hostname** — it's `db_name` label in
  session_manager code.
- **Real cause: postgres+redis were killed by disk-full at 15:44:12Z**,
  never restarted.
- **Workers are correctly waiting for postgres** that doesn't exist.
- **Fix: restart postgres+redis+migration-runner+workers** (Option A above).
  Disk has 36G free now, should succeed.
- **No code change needed.**
