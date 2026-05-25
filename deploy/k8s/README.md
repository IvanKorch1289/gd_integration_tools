# Kubernetes manifests — `gd-integration-tools`

> **Sprint 17 / K-OPS-2 (DoD #12)** — scaffold уровня. Полный Helm chart — S18 K5 W4.

## Содержимое

| Файл | Назначение |
|---|---|
| `namespace.yaml` | Namespace `gd-integration` с pod-security: restricted |
| `configmap.yaml` | Non-secret env: DB/Redis/Temporal hosts, OTel, feature-flags |
| `secret.yaml` | Secret template (production через ExternalSecrets+Vault) |
| `deployment-app.yaml` | Main FastAPI app — 3 replicas, RollingUpdate, probes, securityContext |
| `deployment-worker.yaml` | Temporal workflow worker — 2 replicas, 300s graceful drain |
| `service.yaml` | ClusterIP gd-app + headless temporal-worker-metrics |
| `ingress.yaml` | TLS+ModSecurity OWASP CRS через nginx-ingress |
| `networkpolicy.yaml` | Zero-trust: default-deny + explicit DB/Redis/Temporal/Vault/OTel egress |
| `pdb.yaml` | PodDisruptionBudget minAvailable=1 для app + worker |
| `hpa-app.yaml` | HPA для app (CPU 70% + memory 80%) |
| `temporal-worker-hpa.yaml` | HPA для worker (custom metric `temporal_task_queue_depth`, S12 K2 W2) |
| `jobs/migration.yaml` | Pre-deploy alembic Job (K-OPS-4, S17 K5 W3) |

## Применение (dev/staging)

```bash
# Image tag через env-variable (envsubst или Kustomize в production)
export GD_IMAGE="ghcr.io/your-org/gd-integration-tools:1.0.0"

# 1) Namespace + конфиг
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml  # ⚠️ замените placeholder-секреты!

# 2) Pre-deploy migration
envsubst < deploy/k8s/jobs/migration.yaml | kubectl apply -f -
kubectl wait --for=condition=complete --timeout=600s job/gd-migration -n gd-integration

# 3) NetworkPolicy + PDB + HPA
kubectl apply -f deploy/k8s/networkpolicy.yaml
kubectl apply -f deploy/k8s/pdb.yaml
kubectl apply -f deploy/k8s/hpa-app.yaml
kubectl apply -f deploy/k8s/temporal-worker-hpa.yaml

# 4) Workloads + Services
envsubst < deploy/k8s/deployment-app.yaml | kubectl apply -f -
envsubst < deploy/k8s/deployment-worker.yaml | kubectl apply -f -
kubectl apply -f deploy/k8s/service.yaml

# 5) Ingress (требует cert-manager + ingress-nginx в кластере)
kubectl apply -f deploy/k8s/ingress.yaml

# Проверка
kubectl get all -n gd-integration
kubectl logs -l app.kubernetes.io/component=app -n gd-integration --tail=50
```

## Dry-run валидация

```bash
kubectl apply --dry-run=server -f deploy/k8s/ -R
# Все ресурсы должны валидироваться без ошибок (требует подключение к кластеру).

# Offline (без кластера):
kubectl apply --dry-run=client -f deploy/k8s/ -R
```

## Production deployment (carryover S18)

* **Helm chart** — `deploy/helm/gd-integration-tools/` (Chart.yaml + values.{dev,staging,prod}.yaml).
* **ExternalSecrets + Vault** — для секретов вместо placeholder Secret.
* **ArgoCD / FluxCD** — GitOps continuous deployment.
* **Kustomize overlays** — для multi-environment.
* **ServiceMonitor + PodMonitor** — Prometheus Operator scrape config.
* **VerticalPodAutoscaler** — recommender mode для CPU/memory tuning.
* **OPA Gatekeeper / Kyverno** — admission policies (no privileged, image registry allowlist).

## Связанные документы

* `docs/runbooks/disaster_recovery.md` — DR runbook (4 сценария).
* `ops/backup/` — backup scripts (PG/Redis/ClickHouse/restore).
* PLAN.md V22 §S17 W17 (K-OPS-2).
* `.claude/KNOWN_ISSUES.md` Sprint 17 carryover list.
