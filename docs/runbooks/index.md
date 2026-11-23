# Runbooks

Эксплуатационные сценарии: что делать, когда «оно сломалось». Каждый runbook
самодостаточен: симптомы → диагностика → действие → проверка.

> Навигация: [Tutorials](../tutorials/index.md) · [How-to](../how-to/index.md) ·
> [Cookbooks](../cookbooks/README.md) · [Operations](../ops/index.md)

## Доступность и инциденты

| Runbook | Сценарий |
|---|---|
| [incident-response.md](incident-response.md) | Общая последовательность действий при инциденте |
| [disaster_recovery.md](disaster_recovery.md) | Восстановление после потери данных/сервисов |
| [secret-rotation.md](secret-rotation.md) | Ротация секретов без простоя |
| [blue-green-rollback.md](blue-green-rollback.md) | Откат blue/green-релиза |

## Деплой и релизы

| Runbook | Сценарий |
|---|---|
| [extension-deploy.md](extension-deploy.md) | Выкладка расширения (плагина) |
| [hot-reload-rollback.md](hot-reload-rollback.md) | Откат hot-reload плагина |
| [plugin-hot-swap.md](plugin-hot-swap.md) | Горячая замена плагина |
| [feature-flag-rollout.md](feature-flag-rollout.md) | Раскатка feature-флага |
| [feature-flag-kill-switch.md](feature-flag-kill-switch.md) | Аварийное отключение фичи флагом |
| [routes-feature-flag-rollout.md](routes-feature-flag-rollout.md) | Раскатка флага на уровне роутов |

## Локальная разработка

| Runbook | Сценарий |
|---|---|
| [local-dev-environments.md](local-dev-environments.md) | Локальные окружения (dev / dev_light) |
| [lazy-processor-warmup.md](lazy-processor-warmup.md) | Прогрев лениво загружаемых процессоров |
| [pool-warmup-tuning.md](pool-warmup-tuning.md) | Тюнинг прогрева пулов |
| [toxiproxy-setup.md](toxiproxy-setup.md) | Toxiproxy для тестов отказоустойчивости |

## Инфраструктура и сеть

| Runbook | Сценарий |
|---|---|
| [waf-policy-update.md](waf-policy-update.md) | Обновление политик WAF |
| [http3-server.md](http3-server.md) | HTTP/3-сервер |
| [saml-troubleshooting.md](saml-troubleshooting.md) | Диагностика SAML |
| [temporal-mtls-rotation.md](temporal-mtls-rotation.md) | Ротация mTLS-сертификатов Temporal |
| [grafana-import.md](grafana-import.md) | Импорт дашбордов Grafana |
| [clickhouse-flush-tuning.md](clickhouse-flush-tuning.md) | Тюнинг flush-цикла ClickHouse |

## Очереди, DLQ и workflow

| Runbook | Сценарий |
|---|---|
| [dlq-replay.md](dlq-replay.md) | Повтор сообщений из DLQ |
| [hitl-stuck-workflow.md](hitl-stuck-workflow.md) | Workflow застрял в HITL |
| [eip-sensors-triggers.md](eip-sensors-triggers.md) | EIP: сенсоры и триггеры |

## Наблюдаемость и качество

| Runbook | Сценарий |
|---|---|
| [chaos-test-debug.md](chaos-test-debug.md) | Разбор провала chaos-теста |
| [git-server-docstring-gate.md](git-server-docstring-gate.md) | Docstring-гейт на git-сервере |

## Ресурсы и лимиты

| Runbook | Сценарий |
|---|---|
| [token-budget-overage.md](token-budget-overage.md) | Превышение token-бюджета |
