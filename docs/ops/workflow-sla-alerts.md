# Workflow: SLA-алерты и DLQ-поступление (волна 22, ADR-0408)

> Owner: K3 DSL+Workflow (контракт), K2/SRE (доставка правил в Prometheus).

Runbook по зависшим workflow'ам: [hitl-stuck-workflow.md](../runbooks/hitl-stuck-workflow.md).
Решение: [ADR-0408](../adr/0408-workflow-dlq-contract-and-sla-alerting.md).

## Что эмитится

| Метрика | Labels | Смысл |
|---|---|---|
| `workflow_sla_compliance_total` | `level` (`none`/`soft`/`hard`) | Оценка SLA каждого терминального перехода workflow'а (`succeeded`/`failed`) |
| `workflow_dlq_publish_total` | `status` (`published`/`duplicate`/`no_writer`/`error`) | Публикация исчерпанного шага в DLQ (transport `workflow`) |

Labels ограничены уровнем/статусом: `workflow_id`, `tenant_id`, `route_id`
в Prometheus-labels не попадают (cardinality + PII-политика) — детали
ищите в DLQ-записи и в логах.

Эмиссия происходит в pg-runner runner'е
(`src/backend/infrastructure/workflow/runner.py`) на терминальном переходе
workflow'а. Счётчики объявлены в
`src/backend/core/observability/workflow_sla.py`.

## Порог нарушения

Бюджет времени workflow'а (SLA hard-limit) определяется так:

1. `__sla_hard_limit_s` — маркер в payload'е инстанса;
2. `__execution_timeout_s` — тот же лимит, прокинутый как
   `execution_timeout` (ADR-0396);
3. `run_timeout_s` — бюджет времени из спеки workflow'а (реестр
   workflow'ов).

Если бюджет не задан — SLA не оценивается (метрика не растёт).

Бюджет выставляется автором workflow'а в соответствии с **SLO роутов**
(`route.toml::slo`):

```toml
# routes/hello_route/route.toml
slo = { p95_ms = 500, timeout_ms = 5000 }
```

`timeout_ms` — тот же бюджет, что и `SlaPolicy.hard_limit_seconds`
(`sla:` в декларации workflow'а) и `run_timeout_s` в спеке. Soft-уровень
(`level="soft"`) используется, если soft-лимит задан явно.

Агрегированный порог алерта — **error budget 5 %** (SLO-цель 95 %,
соответствует p95-целям роутов): доля workflow'ов, превысивших бюджет,
не должна быть выше 5 % за час.

## Правила Prometheus / alertmanager

```yaml
groups:
  - name: gd_workflow_sla_alerts
    interval: 30s
    rules:
      - alert: WorkflowSlaHardBreach
        expr: sum(increase(workflow_sla_compliance_total{level="hard"}[1h])) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Workflow превысил SLA-бюджет (hard-breach)"
          description: >-
            Есть workflow'ы, превысившие бюджет времени (SLA hard-limit из
            route.toml::slo.timeout_ms / SlaPolicy.hard_limit_seconds).
            Исчерпанные шаги дополнительно уходят в DLQ (transport=workflow) —
            разбирать их нужно в DLQ-очереди, workflow уже в статусе failed.

      - alert: WorkflowSlaComplianceDegraded
        expr: >-
          sum(increase(workflow_sla_compliance_total{level="hard"}[1h]))
          / clamp_min(sum(increase(workflow_sla_compliance_total[1h])), 1) > 0.05
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Доля SLA-нарушений workflow > 5 % (error budget)"
          description: >-
            Порог 5 % соответствует SLO-цели 95 % (error budget) из настроек
            SLO роутов. Проверьте бюджеты времени workflow'ов и маршруты,
            попавшие в DLQ (transport=workflow).

      - alert: WorkflowDlqNotWired
        expr: sum(increase(workflow_dlq_publish_total{status="no_writer"}[15m])) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Workflow-DLQ не настроен — исчерпанные шаги теряются"
          description: >-
            Runner не смог опубликовать исчерпанный шаг в DLQ (writer не
            сконфигурирован). Связать DLQWriter с DurableWorkflowRunner
            (dlq_writer / set_dlq_writer) в composition root.

      - alert: WorkflowDlqPublishErrors
        expr: sum(increase(workflow_dlq_publish_total{status="error"}[15m])) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ошибка записи в DLQ для исчерпанных шагов workflow"
          description: >-
            Запись в DLQ падает (БД/транспорт). Workflow'ы падают без записи
            в DLQ — проверьте доступность БД и состояние dlq_inbox.
```

## Доставка правил

В репозитории нет Prometheus rule-файлов (`deploy/` содержит только
helm/k8s/windows-worker), поэтому рул приведён здесь. Варианты:

1. **Статический файл** — скопировать YAML-блок в
   `prometheus/rules/workflow-sla.yml` и подключить в
   `prometheus.yml` (`rule_files`).
2. **Через реестр приложения** — `PrometheusAlertManager`
   (`src/backend/infrastructure/observability/prometheus_alerting.py`)
   умеет отрендерить правила:

   ```python
   from src.backend.infrastructure.observability.prometheus_alerting import (
       PrometheusAlertManager,
   )

   mgr = PrometheusAlertManager()
   mgr.register_alert(
       "WorkflowSlaHardBreach",
       condition='sum(increase(workflow_sla_compliance_total{level="hard"}[1h])) > 0',
       severity="critical",
       summary="Workflow превысил SLA-бюджет (hard-breach)",
       description="Исчерпанные шаги уходят в DLQ (transport=workflow).",
   )
   print(mgr.render_rules_yaml())
   ```

## Проверка в рантайме

```bash
# 1) Метрика растёт (жёсткое нарушение бюджета):
curl -s http://<api>/metrics | grep workflow_sla_compliance_total

# 2) DLQ-записи исчерпанных шагов (transport=workflow):
curl -s "http://<api>/api/v1/admin/dlq?transport=workflow"
```

Ожидаемый вид метрики:

```
workflow_sla_compliance_total{level="none"} 42.0
workflow_sla_compliance_total{level="hard"} 3.0
workflow_dlq_publish_total{status="published"} 3.0
```

## Что делать при срабатывании

1. `WorkflowSlaHardBreach` — найти workflow'и в статусе `failed` с
   ошибкой `max_attempts exceeded` (admin-API
   `/api/v1/admin/workflows/<wf_id>`), разобрать их в DLQ (transport
   `workflow`), починить первопричину шага.
2. `WorkflowSlaComplianceDegraded` — сверить бюджеты времени workflow'ов
   с SLO роутов (`route.toml::slo.timeout_ms`); если workflow ждёт
   сигнал (HITL) — см. runbook
   [hitl-stuck-workflow.md](../runbooks/hitl-stuck-workflow.md).
3. `WorkflowDlqNotWired` / `WorkflowDlqPublishErrors` — конфигурация
   DLQ (см. ADR-0408 §Открытое): writer подключается в composition root
   (`DurableWorkflowRunner(dlq_writer=...)` / `set_dlq_writer(...)`).
