# Runbook: Routes hot-reload feature-flag rollout

> Owner: K3.

## Symptom / Trigger

Команда хочет включить `feature_flags.route_loader_hot_reload = True`
в production (default-OFF в Sprint 9 backbone).

## Pre-conditions

* RouteHotReloader scaffold реализован (S9 K3 W1).
* Staging-смоук: 24h без `hot_reloader.reload_failed` ошибок.
* Тесты `tests/unit/services/routes/test_hot_reloader.py` зелёные.

## Diagnosis (pre-rollout)

```bash
# Проверить текущее состояние:
.venv/bin/python -c "
from src.backend.core.config.features import feature_flags
print('hot_reload:', feature_flags.route_loader_hot_reload)
"
# False (default)
```

## Mitigation (rollout)

### Stage 1: staging
```bash
kubectl set env deploy/<service> -n staging ROUTE_LOADER_HOT_RELOAD=true
# observation 24h
```

Smoke-test:
```bash
# Modify routes/test/test.dsl.yaml
# Logs: hot_reloader.route_reloaded
curl http://staging/api/v1/test
```

### Stage 2: pre-prod canary
1 из 10 реплик с `ROUTE_LOADER_HOT_RELOAD=true`. Observation 24h:
* `hot_reloader.reload_failed_count` < 0.1% от reload_total.
* p95 reload duration < 3s.

### Stage 3: production
Phase-by-phase enable: eu-east → eu-west → ru. По 4 часа observation.

После 7 дней без incidents — обновить `core/config/features.py`
default в True (separate PR).

## Verification

* `feature_flags.route_loader_hot_reload == True` в admin panel.
* Sample reload: SSH в pod, изменить YAML, hot-reloader emit event.
* `route_reload_success_rate` > 99.5%.

## Rollback

```bash
kubectl set env deploy/<service> ROUTE_LOADER_HOT_RELOAD=false
kubectl rollout restart deploy/<service>
```

## Postmortem template

См. `incident-response.md`. Обязательно:
* Stage где fail случился.
* Какая ошибка (validation / capability / race).
* Action: добавить test case в hot_reloader tests.
