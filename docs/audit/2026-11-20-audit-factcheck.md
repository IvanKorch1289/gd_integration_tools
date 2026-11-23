# Фактчек аудита prod-readiness — срез `bd707471a220` (2026-11-20)

Документ фиксирует **проверенные** факты по находкам аудита от 19.11.2026
(отчёт `CODE_AUDIT_2026-11-18.md` / `PROD_READINESS_2026-11-18.md`) и план
ограниченной волны исправлений.

## 1. Базовая линия

| Параметр | Значение |
|---|---|
| Репозиторий | `/home/user/dev/gd_integration_tools` |
| Ветка | `master` |
| HEAD | `bd707471a2204699e59ddda819f2b336785e04af` |
| Python | 3.14.0 (`.venv/bin/python`) |
| Доступ | `gh` авторизован (IvanKorch1289), GitHub API проверен эмпирически |

В рабочем дереве присутствуют **чужие незакоммиченные изменения**
(ADR 0087/0088, `mkdocs.yml`, `src/backend/dsl/setup.py`,
`tools/checks/check_tenant_isolation.py` и др.). Волна исправлений их
не трогает и не откатывает.

## 2. Статус находок

| # | Находка аудита | Статус | Доказательство |
|---|---|---|---|
| 3.1 | Персонализированные ответы объявляются `public` | **CONFIRMED** | `response_cache.py:208-215` — `_cache_control()` жёстко возвращает `public, max-age=N`; `response_cache.py:191-198` — исходные `ETag`/`Cache-Control` удаляются, политика endpoint'а (`no-store`) теряется |
| 3.2 | Полная буферизация GET-ответов ломает SSE/streaming | **CONFIRMED** | `response_cache.py:112-136` — `body_chunks` накапливает тело **всех** ответов; проверка `content-type` выполняется **после** накопления (`response_cache.py:146`); ответ уходит клиенту только после `await self.app(...)` |
| 3.3 | Release gate не привязан к workflow | **CONFIRMED** | см. §3 — эмпирическая проверка GitHub API |
| 4 | Impersonation не меняет effective tenant | **CONFIRMED** | `tenant.py:220-231` — capability разрешает mismatch, но `state["tenant_id"] = auth_tenant`; `_resolve_tenant_id` (`tenant.py:308-319`) тоже отдаёт `auth_tenant` → capability объявлена, но не действует |
| 2 | Подмена tenant через заголовок | **FIXED** (в коде) | `tenant.py:216-251` — авторитетный tenant из `AuthContext`, mismatch → 403, principal без tenant → fail-closed. Capability `tenant_impersonation` **нигде в production-коде не выставляется** (только в тестах) → правка контракта не влияет на прод |
| 7 | Метрики `runtime` ≠ состояние запущенного сервиса | **CONFIRMED** | `tools/generate_current_metrics.py:232-239` — `create_app()` без входа в ASGI `lifespan` |
| 5 | «24 545 passed» | **NOT_RUN / не перепроверено** | заявление отчёта, независимого прогона в этой сессии нет |
| 5 | Положительный бизнес-E2E (заказ → результат → документ) | **ENV_BLOCKED** | нет доступа к СКБ/внешнему сервису |

## 3. Эмпирическая проверка release-gate (GitHub API)

Запрос гейта (`.github/workflows/release-gate.yml:77-80`):

```
/repos/IvanKorch1289/gd_integration_tools/actions/runs
    ?head_sha=bd707471a220...&workflow_id=lint.yml&per_page=1
```

Факт: **`workflow_id` игнорируется** — ответ содержит 15 прогонов *разных*
workflow (`perf.yml`, `chaos.yml`, `zap.yml`, …), т.е. `.workflow_runs[0]`
может быть прогоном совершенно другого workflow. Документированный
workflow-specific endpoint (`/actions/workflows/{workflow_id}/runs`) работает
корректно.

Факт: гейт **не ждёт** завершения прогонов. В логе прогона гейта
`44516825191` (HEAD, push, 19.11.2026 11:39:58Z) все 7 обязательных
workflow дали `conclusion: missing` — на момент опроса `conclusion=null`
(run ещё выполнялся), а `jq '.conclusion // "missing"'` превращает `null` в
`"missing"`. То есть гейт красный даже при полностью зелёных прогонах.

Факт: `2>/dev/null || echo '{"workflow_runs":[]}'` смешивает ошибку API с
отсутствием прогона и глушит диагностику.

Факт по SHA: для `pull_request` прогоны записываются с `head_sha` = head-коммит
PR (проверено: прогон `event=pull_request` имеет `head_sha=266b774a…`,
коммит с одним родителем — это head PR, не merge-коммит). Для `push` —
`github.sha`. Прогонов `merge_group` в репозитории нет (`total_count=0`) →
семантику подтвердить эмпирически нельзя.

## 4. Факт: обязательные workflow на HEAD красные

| Workflow | Conclusion на HEAD |
|---|---|
| lint.yml | failure |
| test.yml | failure |
| type.yml | success |
| security.yml | failure |
| sbom.yml | success |
| stubs-drift.yml | success |
| image.yml | failure |
| release-gate.yml | failure |

Корневые причины (из логов CI): отсутствующий драйвер `psycopg` (extra
`sources-cdc` не установлен в CI-окружении) → падает
`tests/unit/core/config/external_databases/test_connection_safety.py`;
в `security.yml` — `Path does not exist: bandit.sarif` и
`pip_audit … invalid requirements input: dist/audit-requirements.txt`;
в `image.yml` — `could not parse reference: .` (trivy получает пустой ref образа).

## 5. План волны (ограниченной, без расширения scope)

| Этап | Работа | Критерий закрытия |
|---|---|---|
| 1 | Политика кэша в `response_cache.py` | `no-store` endpoint'а сохраняется; `public` только по явному opt-in и только для анонимных; аутентифицированные — `private`/`no-store`; политика 304 == политика 200 |
| 2 | Streaming в `response_cache.py` | SSE/не-JSON/потоковые ответы не буферизуются; первый чанк уходит до завершения producer'а; лимит тела для ETag; порядок чанков и ASGI-контракт сохранены |
| 3 | Release gate | workflow-specific endpoint + фильтр по `head_sha`; различение `missing`/`in_progress`/`failed`/`api-error`; ожидание с дедлайном; диагностика не глушится |
| 4 | Консистентность tenant | один контракт impersonation; `state` == `ContextVar` == ORM/RLS == response-header; очистка контекста после исключения |
| 5 | Триаж красных CI | корневые причины подтверждены; точечные безопасные фиксы, если они не маскируют проблему |

**Условие остановки.** После закрытия этапов 1-5 — независимое ревью, регрессия
и финальный вердикт (`READY_RC` / `BLOCKED`). Новые волны «улучшений» без новых
доказательств не запускаются.

**Вне scope (осознанно):** переработка DI, `RouteBuilder`, plugin framework,
новые протоколы, дробление модулей по LOC, изменение lock-файлов.

---

## 6. Что изменено в волне 2026-11-20

| Файл | Суть правки |
|---|---|
| `src/backend/entrypoints/middlewares/response_cache.py` | Политика кэша пересчитывается одной функцией для 200 и 304: `public` — только явный opt-in endpoint'а **и** анонимный запрос; персонализированный запрос → `private`; `Set-Cookie` → `no-store`; политика endpoint'а сохраняется. Решение «кэшировать или passthrough» принимается на `http.response.start`; потоковый ответ (`more_body=True`) и тело больше лимита (`max_body_size`, 1 MiB) идут без буферизации и без ETag. В 304 сохраняются заголовки представления (`Vary`/`Expires`/`Content-Location`, RFC 7232 §4.1) |
| `src/backend/entrypoints/middlewares/tenant.py` | Контракт impersonation определён однозначно: capability **переключает** effective tenant (state → ContextVar → ORM/RLS → response-заголовок `X-Tenant-ID`) + WARNING-аудит; fail-closed сохранён (невалидная capability или несовпадение target → 403 `tenant_mismatch`) |
| `src/backend/core/auth/auth_context_helpers.py` | Единый разбор capability — `resolve_impersonation_target()` (строка / whitelist / fail-closed). Общий источник истины: иначе слои решают capability по-разному и effective tenant расходится между ними |
| `src/backend/entrypoints/middlewares/request_context.py` | `RequestContext.tenant_id` учитывает capability: раньше оставался auth-tenant при target'е в state/ContextVar, а DSL-движок берёт tenant именно из `RequestContext` первым источником |
| `src/backend/entrypoints/middlewares/tenant_resource_isolation.py` | ownership-checker получает effective tenant (target при capability); раньше impersonated-запрос к resource-URL отклонялся 403 |
| `src/backend/entrypoints/middlewares/gzip_compression_excluding.py` | Ветка «body too small» шла **только последним** сообщением — накопленные чанки терялись; потоковые ответы теперь не сжимаются и не буферизуются (сжатие требует полного тела) |
| `src/backend/entrypoints/middlewares/brotli_compression.py` | То же: потоковый ответ (`more_body=True`) пробрасывается без буферизации |
| `src/backend/entrypoints/middlewares/audit_log.py` | `replay_receive` больше **не фабрикует** `http.disconnect`: после replay тела вызывается настоящий `receive`. Starlette (`StreamingResponse.listen_for_disconnect`) трактует фабрикованный disconnect как «клиент отвалился» и отменял поток ответа |
| `src/backend/entrypoints/middlewares/audit_replay.py` | `replay_receive` после первого replay возвращает событие настоящего `receive` (повтор `http.request` по кругу не наступал disconnect'ом и крутил цикл ожидания) |
| `tools/checks/release_gate_check.py` (новый) | Агрегация статусов обязательных workflow: workflow-specific endpoint + клиентская фильтрация по `head_sha` и пути workflow-файла; состояния `success`/`failed`/`in_progress`/`missing`/`error`; ожидание завершения до дедлайна; grace-период для гонки «прогон ещё не создан»; коды возврата 0/1/2 |
| `tools/checks/http_contract_smoke.py` (новый) | HTTP-контракт на **живом** uvicorn-сервере с реальной цепочкой middleware: поднимает сервер, проверяет настоящим HTTP-клиентом политику кэша, условный GET, инкрементальную доставку SSE, целостность сжатого тела, пропуск больших ответов мимо кэша и отклонение несовпадения tenant (10 проверок) |
| `tools/checks/skb_mock_e2e.py` (новый) | Детерминированный mock-E2E бизнес-workflow'а СКБ: mock внешнего сервиса (pending → completed, идемпотентность, PDF) + приложение с реальным SKB-роутером → «создать заказ → получить id → дождаться результата → скачать документ» + recovery после «перезапуска» клиента (10 проверок) |
| `tools/checks/release_evidence.py` (новый) | Машинно-читаемый manifest о готовности (этап 6): SHA + признак грязного дерева, image digest, профиль, состав проверок (`test_scope`), коды возврата и длительность команд, sha256 артефактов, внешние блокеры, вычисленный вердикт `READY_RC`/`BLOCKED`. Логи команд пишутся отдельно, в manifest попадает только их sha256 — секреты из вывода в отчёт не попадают. `READY_RC` невозможен без выполненных проверок, без `test_scope`, на грязном дереве или при блокере |
| `src/backend/core/enums/skb.py` | Нормализация типа ответа `response_type_value()`: enum-член / строка / объект с `.value` → `"JSON"`/`"PDF"` единообразно |
| `src/backend/services/integrations/skb.py` | PDF-ветка `get_response_by_order` сравнивала enum со строкой → документ не отдавался никогда |
| `src/backend/entrypoints/api/v1/endpoints/skb.py` | Та же ошибка в `build_skb_result_response` (enum vs строка) |
| `ops/compose/smoke_egrn.py` | Исправлен контракт функционального скрипта: `response_type=JSON`, чтение `order_uuid` из конверта `data`, шаг скачивания документа с контрольной суммой |
| `tests/smoke/test_http_contract_smoke.py` (новый) | Автотест CI для smoke: скрипт поднимает сервер в фоновом потоке и проверяет контракт |
| `tests/smoke/test_skb_mock_e2e.py` (новый) | Автотест CI для бизнес-workflow'а |
| `tests/unit/tools/test_release_evidence.py` (новый) | 13 тестов на manifest: вердикт READY/BLOCKED по правилам, sha256 артефактов, логи команд, dirty-дерево, отсутствие `test_scope`, подстановка интерпретатора |
| `make/quality.mk` | Цели `http-contract-smoke`, `skb-mock-e2e` и `release-evidence` — запуск проверок одной командой |
| `.github/workflows/test.yml` | Шаг «Release evidence (manifest + локальные проверки)» + выгрузка `artifacts/release/` как артефакта CI: проверки контракта и бизнес-workflow'а выполняются внутри manifest'а, их логи сохраняются рядом |
| `.github/workflows/release-gate.yml` | Гейт вызывает скрипт; SHA вычисляется явно (`pull_request.head.sha \|\| github.sha`); `timeout-minutes` 5 → 45 (ожидание не обрывается); добавлен `workflow_dispatch`; диагностика не глушится |
| `.github/workflows/{lint,test}.yml` | `uv sync --locked --extra sources-cdc` — в CI отсутствовал драйвер `psycopg` (extra `sources-cdc`), из-за чего падали юнит-тесты, admin-эндпоинт конфигурации и сбор статистики мутаций |
| `.github/workflows/security.yml` | Bandit: код 1 («находки MEDIUM+») больше не роняет шаг до сборки SARIF; падение самого скана ловится проверкой непустого `bandit.json`; блокирующий HIGH-гейт сохранён |
| `.github/workflows/image.yml` | Устранены несуществующий выход `steps.meta.outputs.image` и неверный вход trivy `image` (заменён на `image-ref`); добавлен шаг `Resolve primary image ref`; образ пересобирается локально в job'е сканирования |
| `make/security.mk` | Новая цель `audit-requirements` (единая подготовка `dist/audit-requirements.txt`); `sbom-diff-gate` и `audit-deps` зависят от неё → «invalid requirements input» больше не возникает; свежесть отчёта гарантируется `rm -f` + `test -s` |

## 7. Новые находки, вскрытые при исправлении

Их не было в исходном аудите — они стали видны только после того, как
`ResponseCacheMiddleware` перестал буферизовать потоковые ответы:

1. **Потеря тела в gzip** — ветка «body too small» отправляла только
   последний `http.response.body`, а накопленные чанки терялись. Ответ
   приходил пустым (`assert 0 == 5` в `test_streaming_passthrough.py`).
2. **Сжатие убивало streaming** — оба compression-middleware копили тело
   целиком: SSE-события не доставлялись, пока поток не заканчивался
   (для бесконечного producer'а — никогда).
3. **Фабрикованный disconnect в `audit_log`** — `replay_receive` возвращал
   `http.disconnect`; Starlette отменял поток ответа → SSE обрывался
   после первого чанка.
4. **Бесконечный replay в `audit_replay`** — `replay_receive` возвращал
   `http.request` по кругу: цикл ожидания disconnect никогда не
   завершался (и не давал точку ожидания event loop).
5. **Расхождение слоёв при impersonation** — `RequestContextMiddleware`
   и `TenantResourceIsolationMiddleware` не знали про capability: первый
   оставался с auth-tenant (а state/ContextVar — с target'ом), второй
   отклонял impersonated-запрос к ресурсу с 403. Инвариант «tenant один и
   тот же на всех слоях» рушился именно там, где capability и должна
   действовать. Capability в production-коде не выдаётся → для обычных
   запросов поведение не изменилось.
6. **Документ по заказу СКБ не отдавался никогда** — `response_type` из
   query-параметра FastAPI разбирается в enum-член
   `ResponseTypeChoices`, а сервис сравнивал его со строкой `"PDF"`
   (`response_type_str == "PDF"` → `False`) → ветка «bytes» не
   срабатывала, клиент получал JSON вместо документа. Вторая такая же
   ошибка была в `build_skb_result_response`: даже готовые байты
   возвращались как JSON. Это дефект шага «отдать документ» из этапа 5
   плана — функциональный прогон 19.11.2026 не мог его пройти.
7. **Функциональный скрипт `ops/compose/smoke_egrn.py` был сломан по
   контракту** — `response_type=json` (регистр важен: допустимы только
   `JSON`/`PDF`, иначе 422) и поиск `order_uuid` на верхнем уровне
   ответа, тогда как полезная нагрузка лежит в `data` (конверт
   HTTP-клиента). Поэтому шаг «получение результата» был пропущен даже
   при успешном создании заказа.

## 8. Доказательства (локальный прогон)

| Команда | Результат |
|---|---|
| `pytest tests/unit/entrypoints/middlewares/ -q` | **736 passed**, 3 skipped, 1 xfailed |
| `pytest tests/unit/entrypoints/ -q` | **1825 passed**, 23 skipped, 7 xfailed, 3 xpassed |
| `pytest tests/unit/entrypoints/ tests/unit/core/auth/ tests/unit/core/tenancy/ tests/unit/core/test_request_context.py tests/unit/tools/test_release_gate_check.py tests/unit/tools/test_ci_workflow_failure_modes.py -q` | **2577 passed**, 24 skipped, 7 xfailed, 3 xpassed |
| `pytest tests/unit/tools/test_release_gate_check.py -q` | **15 passed** |
| `pytest tests/unit/tools/test_ci_workflow_failure_modes.py tests/tools/test_cve_gate_runtime_only.py -q` | 31 passed (один сетевой тест — ENV_BLOCKED, см. ниже) |
| `pytest tests/unit/entrypoints/middlewares/test_response_cache_policy.py` на **HEAD-реализации** | 16 failed / 4 passed — тесты действительно ловят старый дефект |
| `pytest tests/unit/entrypoints/middlewares/test_tenant_impersonation_layers.py` на **HEAD-реализации** | 2 failed / 7 passed — тесты ловят расхождение слоёв |
| `python tools/checks/http_contract_smoke.py` (живой uvicorn) | **10/10 OK**: `cache-control` не `public`; `no-store` endpoint'а сохранён; условный GET → 304 с тем же ETag; SSE — первое событие через **0.01 с** при producer'е, работающем 0.8 с (поток 1.21 с); сжатое тело после gzip-декодирования совпадает с несжатым (2 097 163 байта); 2 MiB JSON без ETag (лимит кэша → passthrough); несовпадение tenant → 403 `tenant_mismatch` |
| тот же smoke на **HEAD-реализации** `response_cache.py` | **5 проверок FAIL**: `public, max-age=60` вместо приватной политики; `no-store` endpoint'а потерян; SSE — первое событие через 1.21 с (== конец потока, буферизация); ETag посчитан для 2 MiB тела |
| `make http-contract-smoke` | exit 0 |
| `python tools/checks/skb_mock_e2e.py` (mock СКБ + реальный роутер) | **10/10 OK**: справочник видов; `create-request` → `Result: true` + `order_uuid`; первый опрос → `processing`, второй → `completed` с данными; документ отдан как `application/pdf`, sha256 совпал с ожидаемым; повторный `create-request` с тем же `Id` → тот же `order_uuid` (второй заказ не создан); после «перезапуска» клиента результат и документ по тому же заказу доступны; `api-key` передан внешнему сервису |
| тот же mock-E2E на **HEAD-реализации** `services/integrations/skb.py` и `endpoints/skb.py` | документ не отдавался: `content-type=application/json`, checksum не совпал |
| `pytest tests/unit/services/integrations/test_skb.py tests/unit/entrypoints/api/v1/endpoints/test_skb_endpoint.py` на **HEAD-реализации** | 2 failed / 16 passed — тесты ловят PDF-дефект |
| `pytest tests/smoke/ tests/unit/core/enums/test_skb.py tests/unit/services/integrations/test_skb.py tests/unit/entrypoints/api/v1/endpoints/test_skb_endpoint.py tests/unit/entrypoints/middlewares/ -q` | **762 passed**, 3 skipped, 1 xfailed |
| `pytest tests/unit/entrypoints/ tests/unit/services/ tests/unit/core/enums/ tests/unit/tools/test_release_gate_check.py tests/unit/tools/test_ci_workflow_failure_modes.py tests/unit/tools/test_release_evidence.py tests/smoke/ -q` (после правок по ревью) | **4973 passed**, 71 skipped, 8 xfailed, 3 xpassed; 6 падений — pre-existing/ENV (см. ниже) |
| `pytest tests/unit/tools/test_release_evidence.py -q` | **13 passed** |
| `python tools/checks/release_evidence.py` (демо) | manifest собран: SHA `bd707471…`, профиль, 2 проверки с кодами 0 и sha256 логов, 1 внешний блокер → вердикт **BLOCKED** с двумя причинами (грязное дерево, блокер) |
| тот же manifest без блокеров на чистом дереве (временный git-репозиторий в тестах) | вердикт **READY_RC** — только при выполненных проверках, нулевых кодах, чистом дереве и заполненном `test_scope` |
| `ruff check` + `ruff format --check` по 20 изменённым файлам | All checks passed / 20 files already formatted |
| `python tools/check_docstrings.py` | Total: **0 missing** docstrings (2599 файлов) |

**ENV_BLOCKED / NOT_RUN:**

- `tests/tools/test_cve_gate_runtime_only.py::test_make_cve_gate_passes` —
  падает по сети (`requests.exceptions.ReadTimeout` к pypi.org), к волне
  отношения не имеет;
- положительный бизнес-E2E (заказ → результат → документ) — нет доступа
  к СКБ/внешнему сервису;
- прогон `merge_group` — в репозитории нет ни одного такого прогона
  (`total_count=0`), семантику `head_sha` подтвердить нечем;
- `tests/smoke/test_granian_runtime.py` (4 теста) и
  `tests/smoke/test_websocket_endpoints.py` (1 тест) — падают и на HEAD
  (проверено подменой изменённых файлов на HEAD-версии): `granian` не
  установлен, websocket-тест отдаёт `WebSocketDisconnect`. К волне
  отношения не имеют;
- `tests/unit/services/ops/test_processor_health_checks.py::test_vault_not_configured_ok_true`
  — падает из-за состояния окружения (в песочнице Vault сконфигурирован,
  тест ждёт «not configured»); файлы теста и сервиса волной не менялись;
- реальные CI-прогоны после правок не выполнялись (ветка не запушена) —
  состояние ниже относится к HEAD- Baseline.

## 9. Независимое ревью волны

Волна проверена отдельным агентом со «свежими глазами» (read-only ревью
диффа: безопасность кэша, streaming, сжатие, tenant, SKB, release gate,
CI-правки, новые инструменты). Ревью подтвердило основные выводы фактчека
и нашло 2 MAJOR и 10 MINOR — все закрыты в этом же проходе, кроме двух
осознанно оставленных решений.

| Находка | Решение |
|---|---|
| MAJOR-1: `merge_group` не запускал ни один из 7 обязательных workflow → гейт структурно красный на merge queue | **Исправлено:** `merge_group:` добавлен в `on:` всех семи workflow; гейт принимает для merge_group два SHA события (head-коммит группы и временный merge-коммит) — чужой коммит не принимается |
| MAJOR-2: 304 терял `x-request-id` / `x-correlation-id` / `x-tenant-id` | **Исправлено:** в 304 переносятся все заголовки ответа, кроме описывающих тело (`content-length`, `content-encoding`, `transfer-encoding`) — корреляция логов и заголовок tenant'а сохранены |
| MINOR-1: `scope['state']['auth']` читался на входе, когда auth-middleware ещё не отработал → источник персонализации недостижим | **Исправлено:** персонализация вычисляется лениво, в момент формирования ответа |
| MINOR-2: `s-maxage` (директива общего кэша) сохранялся для персонализированного ответа | **Исправлено:** для персонализированного запроса `s-maxage` выбрасывается, `private` добавляется при необходимости |
| MINOR-3: `skb_mock_e2e.py` захватывал синглтон ПОСЛЕ подмены → восстановление было no-op, глобальное состояние утекало в pytest-сессию | **Исправлено:** захват до подмены |
| MINOR-4: gzip-проверка сравнивала длины, а не байты | **Исправлено:** сравнение байт |
| MINOR-5: brotli не досылал накопленные чанки в потоковой ветке (асимметрия с gzip) | **Исправлено:** буфер досылается, как в gzip |
| MINOR-6: `replay_receive` уходит в настоящий `receive()` без таймаута | **Осознанно оставлено.** Таймаут здесь сломал бы SSE: `StreamingResponse.listen_for_disconnect` ждёт disconnect циклом, и таймаут привёл бы к отмене потока ответа (ровно тот дефект, который устранён). Одиночный вызов `receive()` вне cancel-scope — редкий случай; Starlette использует для этого отменяемую scope (`Request.is_disconnected`) |
| MINOR-7: скан проверял пересобранный образ, а не тот, что уходит в registry | **Частично исправлено:** образ сохраняется артефактом (`docker save` + upload) и сканируется ровно тот артефакт, который собран; push остаётся buildx-сборкой (provenance), побайтовая идентичность scan/push потребовала бы `docker push` из артефакта ценой provenance — решение за владельцем pipeline |
| MINOR-8: facade-ветка `base_external_api._request` возвращала «сырой» payload вместо конверта → ветка PDF СКБ падала с `AttributeError` | **Исправлено:** facade-ветка возвращает тот же конверт `status_code/data/headers/...`, что и обычная |
| MINOR-9: grace-период гейта не покрывал гонку «прогонов ещё нет» → ранний выход делал гейт структурно красным | **Исправлено:** grace применяется всегда; «прогона не будет» определяется по его истечении |
| MINOR-10: мёртвый аккумулятор `state.size` | **Исправлено:** размер считается по фактически накопленному |
| MINOR-11: возможна гонка за свободный порт; «TCPTransport closed» при переходе между приложениями | **Исправлено (частично):** первое приложение не останавливается до старта второго — общий DI-пул HTTP-клиента не закрывается между фазами |
| MINOR-12: правки `release_evidence.py` и `test.yml` появились во время ревью | **Устранено:** вынесены в §6 и §8 этого отчёта; дублирование прогонов smoke-скриптов в CI убрано (проверки выполняются внутри manifest'а) |

Ревью также зафиксировало уточнения к формулировкам отчёта: «потеря тела
в gzip» была **прод-дефектом** (при `Accept-Encoding: gzip` любой JSON-ответ
меньше 500 байт приходил пустым), а «фабрикованный disconnect» ломал любой
SSE-ответ в проде, а не только в тестах. Оба учтены в отчёте ниже.

## 10. Вердикт

**BLOCKED до подтверждения в CI.** Кодовая часть волны закрыта и
проверена локально (включая независимое ревью), но вердикт «готов к
проду» на текущем срезе необоснован по трём причинам:

1. **Обязательные workflow на HEAD красные** (lint, test, security,
   image) — причины найдены и исправлены, но результат исправлений
   подтверждён только кодом, а не прогоном CI на этом SHA;
2. **Положительный бизнес-E2E против РЕАЛЬНОГО СКБ не подтверждён**
   (ENV_BLOCKED): нет доступа к стенду. Детерминированная локальная часть
   закрыта полностью — `tools/checks/skb_mock_e2e.py` прогоняет workflow
   «заказ → id → результат → документ» (с контрольной суммой,
   идемпотентностью и recovery) на mock'е внешнего сервиса с реальным
   SKB-роутером, а `tools/checks/http_contract_smoke.py` — HTTP-контракт
   на живом сервере. Mock доказывает корректность сборки и контракта,
   но не поведение реального СКБ-Техно; кроме того, при прогоне против
   mock'а найден и исправлен дефект, из-за которого документ не отдавался
   никогда (enum vs строка);
3. **14 новых advisory** в `uv audit` (13×PYSEC-2026-43xx,
   GHSA-5cjw-f85j-cv6r) вне allowlist — исправление требует изменения
   lock-файла, то есть отдельного согласования.

Условие перевода в `READY_RC`: зелёный прогон всех семи обязательных
workflow на том же SHA + подтверждённый бизнес-E2E + решение по advisory
(обновить или оформить allowlist с обоснованием и сроком).

Механика фиксации этого состояния готова: `tools/checks/release_evidence.py`
собирает машинный manifest (SHA, профиль, image digest, состав проверок,
коды возврата, sha256 артефактов, внешние блокеры) и вычисляет вердикт
`READY_RC`/`BLOCKED` по правилам — зелёный вердикт невозможен без
выполненных проверок, без `test_scope`, на грязном дереве или при
блокере. В CI manifest собирается на каждом прогоне `test.yml` и
выгружается артефактом. Не хватает только самого прогона CI на этом SHA
и digest'а собранного образа (требует сборки образа).
