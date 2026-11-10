# ADR-0440 — Prometheus-правила SLA/DLQ для workflow

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0403 (SLA-политика), ADR-0408 (DLQ-контракт)
* Затрагивает: `deploy/helm/gd-integration-tools/templates/prometheusrule.yaml`, `tests/unit/deploy/test_deploy_manifests.py`

## Контекст

Метрики `workflow_sla_compliance_total{level}` и
`workflow_dlq_publish_total{status}` эмитились (core/observability/workflow_sla.py),
но в репозитории не было ни одного rule-файла: Prometheus Operator не знал, когда
по ним алертить. В chart'е был только ServiceMonitor.

## Решение

`templates/prometheusrule.yaml` (Opt-in: `prometheusRule.enabled=true`):
* recording rule `workflow:sla_hard_breach_ratio:rate5m`;
* алерты `WorkflowSlaHardBreach`, `WorkflowSlaSoftBreach`,
  `WorkflowDlqNoWriter`, `WorkflowDlqPublishError`.

Labels правила совпадают с selectorLabels ServiceMonitor (`release: prometheus`),
иначе Prometheus Operator не подберёт правило.

## Последствия

* SLA/DLQ-алерты появляются при включении правила в Helm-релизе.
* Тесты фиксируют структуру правил и совпадение labels.
