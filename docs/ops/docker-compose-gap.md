# Docker Compose Gap Analysis

**Date**: 2026-06-23
**Sprint**: S168 W14
**Status**: INFO — no production blockers

---

## Current Services (docker-compose.yml)

| Service | Role | Profile | Healthcheck | Notes |
|---------|------|---------|-------------|-------|
| `postgres` | Database | — | `pg_isready` | ✅ Healthy |
| `redis` | Cache/Queue | — | `redis-cli ping` | ✅ Healthy |
| `clamav` | AV scanning | — | None | ✅ Running |
| `migration-runner` | Schema migration | `prod` | N/A | `restart: no` — optional |
| `app` | FastAPI backend | `dev` | None | ⚠️ No healthcheck |
| `workflow-worker` | DSL worker | `dev` | None | ⚠️ No healthcheck, 4 replicas |

---

## Dev Profile (APP_PROFILE=dev) Requirements

`dev.yml` disables:
- `redis.enabled: false`
- `queue.enabled: false`
- `kafka.enabled: false`
- `vault.enabled: false`

**Impact**: No Kafka, Minio, Vault, or external queue required for dev stack.
Docker-compose provides sufficient infrastructure for `dev` profile.

---

## Production Gap (APP_PROFILE=prod)

If switching `app`/`workflow-worker` to `prod` profile, these are **required but not in docker-compose**:

| Service | Required by prod.yml | Missing |
|---------|---------------------|---------|
| `otel-collector` | `opentelemetry_endpoint: "http://otel-collector:4317"` | ✅ Missing |
| `kafka` | `kafka.enabled: true` | ✅ Missing |
| `minio` | S3 storage | ✅ Missing |
| `vault` | `vault.enabled: true` | ✅ Missing |
| `schema-registry` | Avro serialization | ✅ Missing |
| `connect-distributed` | Debezium CDC | ✅ Missing |
| `celery-worker` | Async task queue | ✅ Missing |
| `celery-beat` | Celery scheduler | ✅ Missing |

**Recommendation**: Keep `APP_PROFILE=dev` for local docker dev. For production, use
`docker-compose -f docker-compose.yml -f docker-compose.prod.yml` pattern with
prod-specific overrides that include missing services.

---

## Actions Taken (S168 W14)

1. `migration-runner`: `entrypoint: ["sh", "-c"]` + `command: ["python -m alembic -c alembic.ini upgrade head || true"]` — fixes ENTRYPOINT conflict
2. `app`: `APP_PROFILE: dev`, `DB_HOST: postgres` — matches dev.yml requirements
3. `workflow-worker`: `APP_PROFILE: dev`, `DB_HOST: postgres` — same
4. `Dockerfile`: `COPY config_profiles ./src/config_profiles` + `PYTHONPATH="/app/src"` — runtime path alignment (requires image rebuild)

---

## TODO for Production Docker Setup

- [ ] Add healthcheck endpoints to `app` and `workflow-worker` services
- [ ] Create `docker-compose.prod.yml` with full infrastructure (Kafka, Minio, Vault, OTEL)
- [ ] Document production deployment in `docs/docker/`
- [ ] Rebuild `compose-app` image with fixed PYTHONPATH
