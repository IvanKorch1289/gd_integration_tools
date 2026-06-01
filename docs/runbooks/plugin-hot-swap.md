# Runbook: Plugin hot-swap

> Status: Sprint 9 K3 W7 — AUDIT-2 закрытие docs-drift.
> Owner: K3 DSL/Workflow.

## Symptom

Команде нужно горячо обновить версию плагина (новый код в
`extensions/<name>/`) без рестарта приложения — например, при выкатке
hotfix в `credit_pipeline` плагин.

## Pre-conditions

* `feature_flags.plugin_hot_swap_enabled` = True.
* В `extensions/<name>/plugin.toml` повышена версия (semver bump).
* Capability-список в новой версии плагина — **подмножество** старого
  (расширение capabilities требует full restart с явным capability-grant).
* План state-migration документирован в `extensions/<name>/CHANGELOG.md`.

## Diagnosis

1. Текущая версия плагина:
   ```bash
   curl -s http://<api>/api/v1/plugins | jq '.items[] | {name, version, status}'
   ```

2. Сравнение plugin.toml old vs new:
   ```bash
   diff <(git show HEAD~1:extensions/<name>/plugin.toml) \
        extensions/<name>/plugin.toml
   ```

## Mitigation

### Hot-swap flow (живой rollout)

1. Скопировать новую версию плагина в файловую систему контейнера
   через kubectl cp или Vault secret-injector.

2. Послать сигнал `SIGHUP` главному процессу:
   ```bash
   kubectl exec deploy/<service> -- kill -HUP 1
   ```

3. Hot-reloader (`core/plugin_runtime/hot_swap.py`):
   * блокирует in-flight requests для затронутых routes через
     `asyncio.Lock` per plugin;
   * вызывает `plugin.shutdown()` для старой версии;
   * загружает новый bundle через `PluginLoader.import_plugin()`;
   * вызывает `plugin.bootstrap()` для новой версии;
   * unblock'ирует requests.

4. Lock TTL — 30 секунд; если bootstrap превышает, hot-swap **откатывается**
   к старой версии и записывается ошибка в audit.

### Cold-swap (требует полного restart)

Когда:
* Изменены capability-grant'ы (capability set расширен);
* Изменена схема state (Pydantic-модели в `domain/`);
* Изменена backend-конфигурация (новый Redis/CH connection pool).

Процедура: blue-green deploy (см. `runbooks/blue-green-rollback.md`).

## Verification

* `curl /api/v1/plugins | jq '.items[] | select(.name=="<name>") | .version'`
  должно вернуть новую версию.
* `make audit-plugin-capabilities` — capability diff = пустой.
* Grafana dashboard `plugin-load-success-rate` — спайк не выше +5%.
* Audit log содержит событие `plugin.hot_swap.success` с timestamp.

## Rollback

При hot-swap failure (lock TTL exceeded, bootstrap raised):

1. Hot-reloader автоматически откатывает к старой версии (locked-rollback).
2. Если auto-rollback не сработал — manual restart pod:
   ```bash
   kubectl rollout restart deploy/<service>
   ```

## Postmortem template

Применять стандартный шаблон из `incident-response.md` секции "Postmortem".

## References

* `core/plugin_runtime/hot_swap.py` — реализация
* ADR-0056 — V11 routes & plugin contract
* PLAN.md V19.1 §S9 K3 W7
