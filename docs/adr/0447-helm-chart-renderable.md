# ADR-0447 — Helm-chart обязан рендериться; CI-шаг `helm lint`/`helm template`

* Статус: Accepted (2026-11-10, волны 31–32)
* Cycle: 188
* Связан с: ADR-0444 (Secret без плейсхолдеров), ADR-0412 (service-DNS)
* Затрагивает: `deploy/helm/gd-integration-tools/templates/*`, `deploy/helm/gd-integration-tools/values.yaml`, `.github/workflows/lint.yml`, `tests/unit/deploy/test_deploy_manifests.py`

## Контекст

Chart **не рендерился вообще**: в YAML-комментарии `servicemonitor.yaml` была
Go-template директива (`{{- if ... }}`). Helm вычисляет шаблоны и внутри
комментариев → директива вырезала кусок манифеста, и `helm template` падал с
«parse error». Ни один CI-шаг chart не рендерил, поэтому дефект жил незамеченным.

Дополнительно в `values.yaml` отсутствовала секция `serviceMonitor`, на которую
ссылался шаблон, и не было секции `prometheusRule` (ADR-0440).

## Решение

* директивы из YAML-комментариев убраны (комментарии остаются текстом);
* в `values.yaml` добавлены секции `serviceMonitor` и `prometheusRule`;
* CI-шаг `helm lint` + `helm template` (ADR-0444 — с плейсхолдерами для
  dev/staging);
* регресс-тест: в шаблонах Helm не должно быть Go-template директив внутри
  YAML-комментариев; guard плейсхолдеров обязан быть исполняемым кодом, а не
  комментарием.

## Последствия

* chart рендерит 16 ресурсов; guard плейсхолдеров срабатывает на дефолтных
  значениях → `helm install` в prod без реального токена падает на рендере.
