# K8s Health Probes Reference

**Status**: ✅ Documented (2026-08-13, cycle 167 D-AUDIT-16701)
**Source**: `deploy/k8s/deployment-app.yaml`, `deploy/helm/gd-integration-tools/templates/`

## Overview

App exposes 4 health endpoints, все публичные (без auth и без API key):

| Endpoint | Purpose | K8s probe |
|----------|---------|-----------|
| `/health` | Liveness (is app alive?) | `livenessProbe` |
| `/health/live` | Alias for /health (K8s convention) | `livenessProbe` alt |
| `/ready` | Readiness (can app serve traffic?) | `readinessProbe` |
| `/health/ready` | Alias for /ready (K8s convention) | `readinessProbe` alt |

All 4 return 200 OK без auth. **Cycle 158-164 fixes** добавили missing public paths.

## Endpoints

### `GET /health` (and `/health/live` alias)

**Liveness probe.** Проверяет что процесс alive и event loop отвечает.

```bash
curl http://app:8000/health
# {"status":"alive","version":"0.1.0"}
```

**Не зависит от DB, cache, или external services.** Быстрый response (<100ms).

**K8s livenessProbe** (cycle 30+):
```yaml
livenessProbe:
  httpGet:
    path: /health/live    # or /health
    port: http
  initialDelaySeconds: 30
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3
```

### `GET /ready` (and `/health/ready` alias)

**Readiness probe.** Проверяет что critical components healthy (DB, cache, etc.) и можно направлять traffic.

```bash
curl http://app:8000/ready
# {"status":"ok","timestamp":"...","mode":"fast","components":{...}}
```

**Зависит от `HealthAggregator`** который параллельно проверяет зарегистрированные components.

**K8s readinessProbe** (cycle 30+):
```yaml
readinessProbe:
  httpGet:
    path: /health/ready    # or /ready
    port: http
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3
```

### `startupProbe` (cycle 30+)

Initial slow probe — waits for app to fully start:

```yaml
startupProbe:
  httpGet:
    path: /health/ready
    port: http
  failureThreshold: 30
  periodSeconds: 2
```

## Configuration Requirements

Для корректной работы probes **все 4 endpoint'а должны быть public**:

1. **`AuthRequiredMiddleware`** — `src/backend/entrypoints/middlewares/auth_required.py`
   `DEFAULT_PUBLIC_PATH_PREFIXES` содержит `/health`, `/health/live`, `/ready`, `/readyz`, `/livez`.

2. **`APIKeyMiddleware`** — `src/backend/entrypoints/middlewares/api_key.py`
   `settings.secure.routes_without_api_key` (config_profiles/base.yml) содержит `/health`, `/health/live`, `/health/ready`, `/ready`, `/readyz`, `/livez`.

**Cycles 161-164 fixes** добавили все 4 missing paths.

## Cycle History

| Cycle | Fix | Impact |
|-------|-----|--------|
| 161 | `/ready` to public paths | K8s readinessProbe: 401 → 200 |
| 162 | `/health/ready` + `/health/live` alias routes | K8s convention paths: 404 → 200 |
| 163 | `/health/live` to public paths | K8s livenessProbe: 401 → 200 |
| 164 | 4 paths to routes_without_api_key | APIKeyMiddleware: 401 → 200 |
| 166 | PII masking skip gzip | /metrics: 500 → 200 (cycle 167) |

## Local Testing

```bash
# Запустить dev-стек
sudo docker compose -f ops/compose/docker-compose.light.yml up -d

# Проверить все 4 endpoints (должны быть 200)
for path in /health /health/live /ready /health/ready; do
  curl -fsS -w "$path: %{http_code}\n" -o /dev/null "http://localhost:8000$path"
done
```

Expected output:
```
/health: 200
/health/live: 200
/ready: 200
/health/ready: 200
```
