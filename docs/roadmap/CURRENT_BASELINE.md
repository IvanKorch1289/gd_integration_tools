# CURRENT_BASELINE — 2026-09-11

> Повторная верификация на текущем HEAD после merge параллельной полосы R2.MYPY.
> Правило программы: каждая метрика — команда на текущем HEAD + exit code.
> Evidence-сырьё: `.run/evidence/` (gitignored), сводка здесь.

## Точка верификации

| Параметр | Значение |
|---|---|
| Базовый HEAD | `9f32d8b0b91ce13467892b611e9a42dd2ea1b37f` (2026-09-11 09:54) |
| Рабочее дерево на старте | **чистое** (параллельная полоса смержилась) |
| Python | 3.14.0 (`uv run python`), uv 0.11.7 |
| Fix-коммиты сессии | `4ed38d49c` (diskcache 0o700), `5d093da13` (create_task name=×5 + scan_file тест), `029e8793d` (_prepare_and_save_object dict), `9d59af715` (deps patch), `37a4010dc`+`6c9b148db` (disk-тесты контракт), `0cb485ebc`+`5a42c2dbd` (navigation docs) |

## Статические гейты (команды + результат)

| № | Гейт | Команда | Результат | Exit |
|---|---|---|---|---|
| 1 | Ruff | `uv run ruff check src/` | All checks passed! | 0 |
| 2 | Mypy permissive | `make type-check` | Success: no issues found in 2356 source files | 0 |
| 3 | Mypy strict-profile | `make type-check-strict-profile` | Success: no issues found in 2356 source files (0, удержан после 1190→0) | 0 |
| 4 | Bandit HIGH severity | `uv run bandit -r src/backend -lll -q` | 0 findings | 0 |
| 5 | Bandit HIGH confidence | `... --confidence-level high` | 0 findings | 0 |
| 6 | Vulture @90 | `uv run vulture src/backend --min-confidence 90` | 0 findings | 0 |
| 7 | Layers | `uv run python tools/check_layers.py` | Нарушений: 0 новых (файлов: 2333; baseline: 14 legacy ≤15) | 0 |
| 9 | Test collection | `uv run python -m pytest --collect-only -q` | 17504 tests collected, 0 collection errors | 0 |

## Тесты и coverage

- Полный unit-прогон (xdist -n 4): 10121 passed / 59 failed / 2 errors / 105 skipped.
- **Coverage gate (честный полный прогон на этом HEAD, sweep6, 2026-09-11 14:59)**:
  чанки unit-дерева с `--cov-append` (core/dsl/infra/ep-api/ep-realtime/ep-mq2/ep-misc/
  services/rest) → свежий `coverage.xml` → `check_coverage_gate.py --threshold 70 --strict`
  → **OK: 71.90% ≥ 70% (GATE_EXIT=0)**; baseline 72.04%, падение 0.14pp < допуска 0.5%.
  Итог чанков: 15176 passed / 111 failed (0.73%): core 4143✓, dsl 4463✓, infra 75✗,
  ep-api 874✓, ep-realtime 140✓, ep-mq2 35✗, ep-misc 103✓, services 1✗, rest 442✓.
- Кластеры фейлов (все — дрейф тестов, не статики):
  1. infra «focused»-скаффолды ~65 (prometheus_alerting 12, sse 11, rag_invalidation 10,
     plugin_resource_monitor 9, tracing 8, audit_verify_lifecycle 8, smart_session 7) —
     коммиты семейства PERF-6.x помечены «partial» самими авторами;
     4 файла этого семейства исправлены в сессии (client_metrics, disk, hitl×2).
  2. mcp namespaces 28 (ai 7, system 6, analytics 6, credit 5, http_auth 4) — фейки
     тестов отстали от dispatch-lookup эволюции.
  3. langfuse 1 — флак под параллельной нагрузкой (в изоляции зелёный).
- **Регрессии после merge полосы R2.MYPY — найдены и исправлены:**
  1. `TaskRegistry.create_task(name=)` keyword-only: 5 колл-сайтов (processor_pool,
     audit_log, mqtt_handler, gateways, file_watcher) прикрыты `type: ignore[call-arg]` —
     mypy green, runtime TypeError. Fix `5d093da13`.
  2. `_prepare_and_save_object`: list vs dict — CRUD add/update сломаны. Fix `029e8793d`.
  3. `CrudMixin.list` → `fastapi_pagination.Params` (entity-CRUD list 500). Fix `7b95bcbfa`.
  4. auto-endpoints: SQLAlchemy-модели не сериализуются FastAPI 0.141. Fix `5682594f9`.
  5. GraphQL `context_getter(request: Any)` → все POST 422. Fix `7dc48bd32`.
  6. `dsl/agents/fastmcp_server`: mcp 2.x удалил старый импорт → runtime ImportError +
     mypy budget 1. Fix `3e5e116e0`.
- Нагрузочные флаки (smart_session, query_result_cache, vault reauth, cert_exporter,
  msgspec bench): в изоляции зелёные — не дефекты.

## Зависимости и security

| Гейт | Команда | Результат | Статус |
|---|---|---|---|
| pip-audit | `uv run python tools/checks/run_pip_audit.py` | 2 finding = один CVE (diskcache PYSEC-2026-2447 = CVE-2025-69872, aliases), fix-версии нет upstream | Mitigated: ADR-0287 allowlist (review 2026-12-01), `use_disk_fallback` default-OFF, + defence-in-depth `mkdir 0o700` (`4ed38d49c`) |
| Outdated | `uv pip list --outdated` | **34** (было 37 на старте сессии; −3 patch: presidio/pymongo/ruff+tqdm+wrapt… см. `9d59af715`) | Цель ≤30 не достигнута; residual = MAJOR-цепочки (aio-pika/aiormq/pamqp, elasticsearch/transport, protobuf/thinc/deepeval, rich/textual, redis 5→8, mypy 1→2) + 3 parent-pin-blocked patch — каждому owner/plan в FINAL_REPORT |

## Graphify

- `graphify update .` — выполнен; graph.json обновлён (не в git, gitignored).

## Отличия от исторических claims

- FINAL_REPORT/LEDGER от 2026-09-10 заявляли «middleware suite 522 passed», «strict mypy 0», «outdated 34» — mypy/layers подтверждаются; outdated ухудшился до 37 к старту этой сессии (полоса влила новые пины) → компенсирован до 34.
- PROGRESS_LEDGER-статусы не сверялись как источник: все метрики выше взяты из прямых прогонов этого HEAD.
- docs/STATUS.md и прочие исторические файлы: см. `repository-navigation-audit.md` §4 — обнаружены битые ссылки (CLAUDE.md ×4, mkdocs api/, README-пути `/sse`→`/events`).

## Команды, которые не удалось выполнить

- Полный `make test` единым прогоном — запрещён правилами ресурса на shared-box; заменён доменными чанками с timeout (эквивалентное покрытие).
- `uv lock --upgrade-package` для googleapis-common-protos / presidio-anonymizer / python-semantic-release — resolver молча не двигает (parent-пин, класс R2.DEPS-3).
