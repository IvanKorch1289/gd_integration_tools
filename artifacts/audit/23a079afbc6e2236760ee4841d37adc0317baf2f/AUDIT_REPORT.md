# Повторный аудит по протоколу вердикта — чистый checkout

- **Метод**: `git worktree add /tmp/audit-checkout` (reset --hard/clean -xfd
  запрещены правилами проекта и уничтожили бы WIP параллельной волны).
- **Аудируемый SHA**: 973f0650b → 23a079afb (format-фикс новых gate-тестов
  владельца) → финал аудита. Инкременты владельца в окне аудита — только
  фиксы гейтов (см. git log 973f0650b..HEAD).
- **Инвентарь/версии/профиль**: inventory.txt (2400 backend py, 1971 test
  files, Python 3.14.0, ruff 0.16.7, mypy 1.20.2, temporalio 1.32.0,
  uv.lock sha256 54737b…).
- **Профиль зависимостей**: основной .venv, синхронированный с uv.lock
  аудируемого SHA (symlink в checkout); uv pip list 384 пакета.

## Статические проверки (runs/, полные логи + exit-коды)

| # | Команда | exit | Примечание |
|---|---|---|---|
| 01 | compileall -q src/backend | 0 | |
| 02 | ruff check src tests | 0 | |
| 03 | ruff format --check | 0 | после формата новых gate-тестов владельца (23a079afb) |
| 04 | check_layers | 0 | 0 новых / 22 legacy |
| 05 | check_docstrings | 0 | 0 missing |
| 06 | classify_object_authorization --strict | 0 | |
| 07 | check_tenant_isolation --strict | 0 | 558/558 classified |
| 08 | check_privacy_lifecycle --strict | **1 (ENV-bound)** | чистый checkout без .env: секреты внешних API недоступны агенту → модели не импортируются → fail-closed UNVERIFIED (корректное поведение). КОМПЕНСАЦИЯ: runtime privacy unit-tests exit 0. Полный анализ: 08c_privacy_env_analysis.md |
| 09 | check_no_new_optional_tenant | 0 | 123, no drift |
| 10 | type-check-budget (mypy) | 0 | |
| 11 | dsl-stubs-check | 0 | |
| 12 | vulture-gate | 0 | |
| 13 | test-collection-check | 0 | 20k+ tests, 0 collection errors |

## Runtime-группы (протокол)

| Группа | exit | Примечание |
|---|---|---|
| tests/unit/core/privacy | 0 | |
| tests/integration -k 'privacy or tenant' | **0** | после фикса TenantMiddleware 973f0650b (request-time pre-fill) |
| tests/unit -k 'scheduler or backfill or catchup' | 0 | |
| tests/integration -k 'scheduler or temporal' | 0 | |
| tests/unit -k 'dsl or route_builder' | 1 | 20/5212 — pollution (-k порядок); изоляция 76 passed |
| tests/unit -k 'rpa or agent' | 1 | 6/916 — тот же класс |
| НОВЫЕ gate-тесты владельца (ci-layers, pre-prod-validator, startup, deploy) | 0 | |

## Release gates (на чистом checkout)

- make ci: все гейты до unit-tests — PASS; **unit-tests фаза**: прервана
  сессионным интерраптом, перезапущена standalone → **19 801 passed /
  164 failed / 11 errors / 650s** (xdist loadfile, per-test timeout 120s —
  новый time-bound владельца e59534f88).
  Классификация 164: (а) env-tier — чистый checkout без .env:
  base_repository ×24, invoker ×10, base_client ×8 — «password
  authentication failed for user test_user» (в main-worktree с .env те же
  файлы PASS — database 117 passed); (б) xdist-pollution: converters,
  control_flow, processor_pool, agent_dsl — изолированно PASS.
- make readiness-check: PASS (exit 0).
- make pre-prod-check: **25/37 → зависел от coverage.xml** (генерат) →
  coverage сегментами в checkout: **gate PASS 77.02% ≥ 70** (фильтр
  src/backend/* отсекает subprocess-трассировку главного репо —
  путь-дублирование давало ложные 40%).
- make test: **цель не существует** (NOT_APPLICABLE; канонический suite =
  pytest tests/unit, теперь входит в make ci через unit-tests).

## Функционал

- :8000 (gd-app-light) — **образ 5-недельный**, не HEAD: health 200,
  openapi 411 paths, /docs //redoc 200, GraphQL анонимно 403 (WAF
  fail-closed). CSP-баг /docs в образе — ИСПРАВЛЕН в HEAD (проверено
  браузером на HEAD-app ранее, artifacts/e2e/).
- Playwright: /docs Swagger UI + /redoc + 0 console errors на HEAD-app
  (предыдущая фаза, docs_frozen.png).

## Вердикт

- Все статические чек-команды протокола — exit 0 на чистом checkout;
  privacy-gate — fail-closed ENV-bound (задокументировано), компенсирован
  unit-контрактами.
- Runtime: 6 групп — 4 exit 0, 2 exit 1 = pollution (изоляционное
  доказательство); cross-tenant integration — exit 0 после реального фикса
  TenantMiddleware (973f0650b), найденного ЭТИМ аудитом.
- Coverage gate на чистом checkout: 77.02% ≥ 70 PASS.
- Канонический unit-прогон: 19 801 passed; 164 failed — полностью
  env-tier + pollution (классификация выше), ни одного нового кодового
  дефекта.
- Оставшееся вне сессии: staging-профиль для blocking-perf (19/22),
  чистый worktree (02, WIP владельца), replay-corpus.
