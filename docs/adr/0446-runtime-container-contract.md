# ADR-0446 — Рантайм-контур контейнера: расширения, пулы, healthz-алиас, Vault-refresher

* Статус: Accepted (2026-11-10, волны 31–32)
* Cycle: 188
* Связан с: ADR-0267 (fail-closed worker), ADR-0383 (RLS), ADR-0429 (громкая семантика провала), ADR-0442 (extras образа)
* Затрагивает: `ops/compose/docker-compose.{light,prod}.yml`, `src/backend/plugins/composition/setup_infra/pools.py`, `src/backend/plugins/composition/setup_infra/lifecycle.py`, `config_profiles/base.yml`

## Контекст

Функциональная проверка контейнера (независимый агент) нашла четыре дефекта,
невидимые по коду и тестам:

1. **0 workflow-деклараций.** Автозагрузка искала каталог расширений по
   `<repo_root>/extensions`, а в образе `repo_root` = `/app/src` → искался
   `/app/src/extensions`, тогда как расширения лежат в `/app/extensions`.
   Дополнительно образ не содержал extra `workflow` (temporalio) → компилятор
   падал («temporalio SDK not installed») даже с верным путём.
2. **4 pool ping FAIL.** `JupyterHubClient`, `AntivirusService`,
   `VaultSecretsBackend` создавались без обязательных аргументов
   (`# type: ignore[call-arg]` это маскировал) → ping всегда падал.
3. **`/healthz` → 401.** k8s livenessProbe-алиас был зарегистрирован, но не
   попал в `routes_without_api_key` → проба не проходит.
4. **~100 error-логов «Vault недоступен».** Secret-refresher стартовал при
   `vault.enabled: false` (dev_light) и каждые ~2,5 мин падал.

## Решение

* `EXTENSIONS_DIR=/app/extensions` — в compose для `app` и `workflow-worker`
  (prod и light); extra `workflow` — в дефолт `UV_EXTRAS` (ADR-0442);
* ping-функции передают реальные зависимости (настройки JupyterHub, DI-сервис
  антивируса, addr/token Vault);
* `/healthz` добавлен в `routes_without_api_key`;
* secret-refresher не стартует при `vault.enabled: false` (тихий info вместо
  error-шума).

## Последствия

* Контейнер: 4 workflow-декларации, 0 pool ping FAIL, 0 Vault-ошибок,
  `/healthz` 200;
* аддитивно и без изменения семантики бизнес-логики.
