"""Unit-тесты offline-валидации deployment-конфигов.

Sprint 171 (S170+) / B-series audit (2026-08-03). Ловит регрессии, при которых
docker-compose / k8s / Helm манифесты ссылаются на несуществующие модули,
пропускают ``command:`` для worker-контейнеров или не передают ``-c alembic.ini``
в Job миграции — категория deployment-blockers, которую не покрывают unit-тесты
доменной логики.

Покрывает:
    * ``ops/compose/docker-compose.yml``;
    * ``ops/compose/docker-compose.light.yml``;
    * ``deploy/k8s/deployment-worker.yaml``;
    * ``deploy/helm/gd-integration-tools/templates/deployment-worker.yaml``;
    * ``deploy/helm/gd-integration-tools/templates/job-migration.yaml``.

Не покрывает:
    * helm Secret placeholder-значения — они безопасно помечены в комментариях
      как dev/staging-only, production использует ExternalSecrets+Vault
      (см. ``deploy/helm/gd-integration-tools/templates/secret.yaml``).
"""
