# ADR-0444 — Helm Secret не пропускает плейсхолдеры в прод

* Статус: Accepted (2026-11-10, волна 31)
* Cycle: 188 (волна 31)
* Связан с: ADR-0364 (секреты через Vault), ADR-0441 (инфра-чек-лист)
* Затрагивает: `deploy/helm/gd-integration-tools/templates/secret.yaml`, `deploy/helm/gd-integration-tools/values.yaml`

## Контекст

Chart содержал placeholder-Secret: `VAULT_TOKEN: CHANGEME`, пустые API-ключи.
`helm install` в прод проходил успешно → креды оказывались неверными, а
отказ проявлялся только во время работы приложения (Vault недоступен).

## Решение

* В `templates/secret.yaml` — `fail` на рендере, если `secrets.vaultToken`
  пуст или равен `CHANGEME` (ADR-0429: fail-loud вместо тихой деградации);
* escape-hatch только для dev/staging: `--set secrets.allowPlaceholders=true`;
* значения перенесены в `values.yaml` (`secrets.vaultToken`,
  `secrets.openaiApiKey`, `secrets.anthropicApiKey`);
* в проде используется ExternalSecrets + Vault operator (операционная задача,
  ADR-0441).

## Последствия

* `helm install` в прод без реального токена → понятная ошибка рендера,
  а не «Vault недоступен» в рантайме;
* dev/staging сохраняют рабочий сценарий через явный флаг.
