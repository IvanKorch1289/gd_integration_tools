# Runbook: Extension (plugin) deploy

> Owner: K5.

## Symptom / Trigger

Команда хочет:
1. Создать новый plugin в `extensions/<name>/`.
2. Обновить существующий plugin (hot-swap или cold-swap).
3. Откатить plugin к предыдущей версии.

## Pre-conditions

* `make new-plugin NAME=<name>` для scaffold (см. K5 W3).
* `plugin.toml` валиден через `make plugin-schema`.
* Capabilities заявлены и одобрены security team.

## Diagnosis

```bash
# Список installed plugins:
curl http://<api>/api/v1/plugins | jq
# Inspect один plugin:
curl http://<api>/api/v1/plugins/<name> | jq
```

## Mitigation (deploy)

### Scenario A: new plugin

1. Scaffold:
   ```bash
   make new-plugin NAME=my_plugin FEATURES='action_a,action_b' \
     CAPABILITIES='net.outbound.api.example.com:external'
   ```

2. Имплементировать functions/ + routes/ + workflows/.

3. Тесты:
   ```bash
   uv run pytest extensions/my_plugin/tests/ -v
   ```

4. Deploy:
   * Git commit + PR
   * Merge → CI builds container → deploy в staging
   * Smoke: `curl /api/v1/plugins/my_plugin` → status: enabled

### Scenario B: update plugin (hot-swap)

См. `plugin-hot-swap.md` runbook.

### Scenario C: rollback

```bash
# Откатить через blue-green:
kubectl rollout undo deploy/<service>
# Или удалить plugin через admin API:
curl -X POST http://<api>/api/v1/admin/plugins/<name>/disable
```

## Verification

* `make audit-plugin-capabilities` — capability diff пустой.
* `pytest extensions/<name>/tests/ -v` — все pass.
* Routes из plugin отвечают через API.
* `make new-plugin-test` smoke.

## CI gates

* `check_plugin_schema` — plugin.toml валиден.
* `check_workflows_extensions` — workflows только в extensions/, не в src/.
* `check_capability_decl` — все используемые capabilities заявлены.

## Postmortem

* Какой stage упал (scaffold / tests / staging deploy / production).
* Был ли capability missing?
* Action items для PluginCodegen / make new-plugin шаблона.
