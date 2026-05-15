# Grafana dashboards import — K2 S7 финальный набор

Runbook по импорту 7 финальных Grafana-dashboards проекта `gd_integration_tools`
и регистрации multi-window SLO burn-rate alerts.

> Owner: K2 Resilience+Perf. Sprint 7 Wave 2.
> Feature-flag: `grafana_dashboards_final` (default-OFF).

---

## Состав

| Файл | UID | Назначение |
|---|---|---|
| `api_latency_p95.json` | `gd-api-latency-p95` | API latency p50/p95/p99 + RPS per-endpoint |
| `db_pool_health.json` | `gd-db-pool-health` | PG/Redis/HTTP pool size + utilization + recycle |
| `temporal_workflows.json` | `gd-temporal-workflows` | Running workflows + activity heatmap + saga state |
| `resilience_snapshot.json` | `gd-resilience-snapshot` | CB / RateLimit / Bulkhead matrix + degradation events |
| `ai_cost_per_tenant.json` | `gd-ai-cost-per-tenant` | Cost by model/tenant + token rate + budget alerts |
| `outbox_dlq_depth.json` | `gd-outbox-dlq-depth` | DLQ depth per transport + replay rate |
| `slo_burn_rate.json` | `gd-slo-burn-rate` | Multi-window error budget burn (1h/6h/24h) |

Все dashboards используют datasource `Prometheus` (uid не привязан — используется
default). Templating-переменные подсасываются из реальных метрик в кластере.

## Alerts: SLO burn-rate trio

Файл `infrastructure/observability/alerts/slo_burn.yaml` содержит 3 правила:

| Alert | Window | Threshold | Severity | Action |
|---|---|---|---|---|
| `error_budget_burn_fast` | 1h | 14.4x | critical | PagerDuty/Telegram on-call |
| `error_budget_burn_medium` | 6h | 6x | high | reaction within 1h |
| `error_budget_burn_slow` | 24h | 3x | warning | backlog ticket |

SLO target: `0.999` (3 9's availability). Меняется через переменные правил.

---

## Импорт в Grafana

### Способ 1: provisioning (recommended)

В `grafana/provisioning/dashboards/gd_integration_tools.yaml`:

```yaml
apiVersion: 1
providers:
  - name: gd_integration_tools
    orgId: 1
    folder: "K2 Resilience"
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: false
    options:
      path: /var/lib/grafana/dashboards/gd_integration_tools
```

Скопируйте 7 JSON-файлов в `/var/lib/grafana/dashboards/gd_integration_tools/`
и перезапустите Grafana — dashboards подхватятся автоматически.

### Способ 2: UI import (manual)

1. Grafana → **Dashboards** → **New** → **Import**.
2. Upload JSON (по одному файлу).
3. Выберите datasource Prometheus.
4. **Import**.

> Повторите для всех 7 файлов.

### Способ 3: HTTP API

```bash
GRAFANA_URL="https://grafana.internal"
GRAFANA_TOKEN="<service-account-token>"

for f in src/backend/infrastructure/observability/grafana/*.json; do
  curl -X POST "$GRAFANA_URL/api/dashboards/db" \
    -H "Authorization: Bearer $GRAFANA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"dashboard\": $(cat "$f"), \"overwrite\": true}"
done
```

---

## Импорт SLO alerts в Prometheus

```bash
# Скопировать правила в prometheus rules directory.
cp src/backend/infrastructure/observability/alerts/slo_burn.yaml \
   /etc/prometheus/rules.d/

# Применить (Prometheus reload).
curl -X POST http://prometheus:9090/-/reload
```

Либо через Prometheus Operator (Kubernetes):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: gd-slo-burn
  namespace: monitoring
spec:
  groups:
  # ... вставить содержимое slo_burn.yaml::groups
```

---

## Verification checklist (post-import)

- [ ] Все 7 dashboards отображаются в папке `K2 Resilience`.
- [ ] Templating-переменные (`endpoint`, `tenant`, `namespace`, `service`) заполняются.
- [ ] Метрики не пустые (требует активного scrape Prometheus).
- [ ] `kubectl get prometheusrule gd-slo-burn` (или `promtool check rules`) проходит.
- [ ] Alertmanager routes для severity `critical`/`high`/`warning` сконфигурированы.

## Screenshot placeholders

> Скриншоты добавляются после первого staging-импорта.

- `docs/runbooks/img/grafana-api-latency-p95.png` *(TODO)*
- `docs/runbooks/img/grafana-db-pool-health.png` *(TODO)*
- `docs/runbooks/img/grafana-temporal-workflows.png` *(TODO)*
- `docs/runbooks/img/grafana-resilience-snapshot.png` *(TODO)*
- `docs/runbooks/img/grafana-ai-cost-per-tenant.png` *(TODO)*
- `docs/runbooks/img/grafana-outbox-dlq-depth.png` *(TODO)*
- `docs/runbooks/img/grafana-slo-burn-rate.png` *(TODO)*

## Связь с feature-flag

`grafana_dashboards_final` (см. `src/backend/core/config/features.py`) — управляет
автоимпортом dashboards через Grafana provisioning API в startup-хуке. Default-OFF
до прохождения staging-smoke с реальным трафиком и метриками.

После успешного smoke-теста: включить flag в production environment.

## См. также

- Google SRE Workbook: [Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/)
- Prometheus AlertManager docs
- ADR-0060 (Blue/Green) — `docs/architecture/decisions/0060-blue-green.md`
