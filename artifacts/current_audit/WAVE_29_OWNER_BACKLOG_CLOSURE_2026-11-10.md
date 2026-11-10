# Волна 29 (2026-11-10) — доработка остатка §16 и инфраструктурного пункта 7

Владелец поручил доработать весь остаток owner-задач: §16 (10 пунктов) и
инфраструктурный п.7. Закрыто кодом 8 ADR (0434–0441), 20+ коммитов.

---

## 1. §16 — что закрыто кодом

| # | Было | Стало | ADR |
|---|---|---|---|
| 1 | `workflow_setup.py` глотал ошибку загрузки workflow (`warning`, обрезка 200 символов) | `logger.error` с путём и полным текстом + сводка «N из M» + `get_workflow_load_failures()` | 0434 |
| 2 | `bulkhead`/CB не подключены к DSL-процессорам | `guarded_external_call()` — общий CB (`dsl:<processor>`, пороги из HTTP-настроек) + bulkhead (лимит concurrency) для `http_call`, `soap_call`, `grpc_call`, `ws_publish`, `mq_publish` | 0436 |
| 3 | `core/api` не экспортировал примитивы устойчивости | экспортированы `CircuitBreaker`, `Bulkhead`, `RateLimiter`, `rate_limiter`, `unified_rate_limiter`, `with_retry` | 0434 |
| 4 | нет cookbook'а «как написать workflow YAML» | `docs/cookbooks/07-write-workflow-yaml.md` (шаблон → правка → линт → dry-run → запуск → gotchas) | 0434 |
| 5 | три линтера DSL-YAML (`tools/dsl_lint.py`, устаревший `cli/lint.py`, `DSLLinter`) | канон — `src/backend/dsl/cli/lint.py`; `tools/dsl_lint.py` — тонкая CLI-обёртка; dry-run'и разных доменов разведены | 0434 |
| 6 | строгая проверка ресурсных capability была WARN | гейт **блокирует**; единый маппинг `PROCESSOR_CAPABILITIES`; 4 роута мигрированы (baseline 8 → 4) | 0435 |
| 7 | checkpoint'ы best-effort (не сохранялись) | `InstanceStore.update_snapshot()` + activity сохраняет в снимок инстанса; несохранение — явный `persisted=False` | 0435 |
| 8 | prompt-versions не было (Prompt Lab выключена) | `PromptRegistry.list_prompts/list_versions/active_version/activate/compare` + 4 эндпоинта + портал | 0437 |
| 9 | storage-операции только по `file_uuid` | `GET /api/v1/storage/{list,get,download}` по ключу (тонкие обёртки над S3-сервисом) | 0438 |
| 10 | pools/processes-метрик не было | `GET /api/v1/admin/pools/snapshot`, `/processes/active`, `/processes/stats`; сводка очередей — capability отсутствует (панель остаётся выключенной) | 0439 |

## 2. П.7 — инфраструктура

| Пункт | Итог |
|---|---|
| `.env:92` (разделитель без `#` → compose не парсит `.env`) | **исправлено**: точечный `sed` по строке 92 (секреты не читались) → `docker compose config` проходит |
| образ `gd-integration-tools:light` от 18.08 | **пересобран** из рабочего дерева; контейнеры пересозданы; `/health` 200, `/ready` 200; новые эндпоинты → 401 (маршрут есть) |
| Prometheus-правила SLA/DLQ | **добавлены** `templates/prometheusrule.yaml` (ADR-0440): `WorkflowSlaHardBreach`, `WorkflowSlaSoftBreach`, `WorkflowDlqNoWriter`, `WorkflowDlqPublishError` + recording rule |
| `audit.write` в `route.toml` | решение владельца: **не объявлять** до появления enforcement (иначе — декоративная декларация) |
| `audit_clickhouse_enabled` в проде | **выставлен явно** в `config_profiles/prod.yml` (ADR-0441) |
| JWKS RS256 + keypair | код готов (асимметричные алгоритмы + JWKS-бэкенд); осталось — keypair и JWKS-сервис (инфра) |
| service-DNS для sidecar'ов | **уже было** (ADR-0412): `otel-collector:4317`, `waf.clamav_host` |
| OpenWebUI endpoint | контракт закрыт (ADR-0412); осталось — развернуть сервис и включить в `fallback_chain` |
| `replica_dsn` | `null` допустим (ADR-0407); решение владельца |
| BYPASSRLS | guard fail-closed в `snapshot_job.py`; осталось — роль БД |
| `jupyter.hub` capability | **уже было**: провайдер в расширении `extensions/jupyter_hub/` (ADR-0415) |

Единый чек-лист с командами и проверками — `docs/ops/infra-release-checklist.md`.

## 3. Проверки

| Гейт | Результат |
|---|---|
| `tests/unit` (волна 29, полный) | **24050 passed, 180 skipped, 52 xfailed, 45 xpassed, 1 failed → 0 после фикса README cookbooks** (43:18; лог `.run/wave13-logs/reg_final_29.txt`) |
| ruff `src/` | All checks passed |
| `check_route_capabilities.py` | OK (7 роутов, 12 плагинов, 4 легаси в baseline) |
| `check_workflow_specs.py` | OK (22 спе-файла) |
| `check_docstrings.py src --max-allowed 0` | 0 missing |
| `check_layers.py --strict` | 41 (прежний долг, без регресса) |
| smoke свежего образа | `/health` 200, `/ready` 200, 8 новых путей → 401 |
