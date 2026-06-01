# Runbook: Route hot-reload rollback

> Owner: K3.

## Symptom

После hot-reload route (K3 W1) появляются 500-ошибки в API. Audit-event
`hot_reloader.reload_failed` зафиксирован для route_name=X.

## Detection

```bash
# Streamlit: pages/11_Routes → видна индикация "load_error"
# Или через API:
curl http://<api>/api/v1/admin/routes/<name>
# {"status": "load_error", "version": "0.1.0", "error": "..."}
```

## Diagnosis

1. Найти ошибку в логе:
   ```bash
   kubectl logs deploy/<service> --since=10m | grep hot_reloader
   ```

2. Проверить новый YAML локально:
   ```bash
   uv run python -m src.backend.services.routes.validate \
     routes/<name>/route.toml
   ```

## Mitigation

### Option A: исправить YAML
1. Откатить файл через `git checkout HEAD~1 -- routes/<name>/`.
2. Hot-reloader подхватит изменение через 0.5s (debounce).
3. Verify: `make routes` → 0 errors.

### Option B: отключить через feature_flag
```bash
# emergency: выключить hot-reload globally
kubectl set env deploy/<service> ROUTE_LOADER_HOT_RELOAD=false
kubectl rollout restart deploy/<service>
```

### Option C: unload route
```bash
curl -X POST http://<api>/api/v1/admin/routes/<name>/unload
```

## Verification

* `curl /api/v1/admin/routes/<name>` → status: enabled, version restored.
* 500-ошибки прекращаются.
* `route_load_success_total` метрика растёт.

## Rollback к предыдущей версии routes/

```bash
git log --all -- routes/<name>/  # найти "хорошую" version
git checkout <commit> -- routes/<name>/
```

## Postmortem

* Какой шаг hot-reload-flow упал (manifest load / dispatch / capability check).
* Был ли automatic rollback (locked-rollback в hot_reloader.py).
