# Фаза A5 — GitLab CI (merge-gates без test-stage)

* **Статус:** done
* **Приоритет:** P0
* **Связанные ADR:** —
* **Зависимости:** A4

## Цель

Поднять production-ready GitLab CI pipeline без test-stage (политика
«no-tests» зафиксирована в A1 через `tools/check_no_tests.py`). Pipeline
обеспечивает все merge-gates раздела 5.5 плана.

## Выполнено

`.gitlab-ci.yml` собран и содержит следующие stages:

- **lint** — `ruff check` + `ruff format --check`.
- **type-check** — `mypy -p app` (`allow_failure: true` на baseline,
  blocking после фаз B1/B2).
- **security** — `bandit`, `detect-secrets`, `creosote`.
- **build** — Docker multi-stage + Trivy scan (severity HIGH/CRITICAL).
- **docs** — `sphinx-build -W` + HTML artifact.
- **progress-gate** — парсит `docs/PROGRESS.md`, падает при
  незакрытых фазах в MR на master.
- **phase-gate** — проверяет commit-format `[phase:<ID>]` по коммитам
  ветки относительно `origin/master`.
- **regression-grep** — запрещённые импорты (`_FallbackRegistry`,
  `CircuitBreakerMiddleware`, `passlib`, `async_timeout`, `psycopg2`).
- **no-tests-gate** — hard-block на test infrastructure (путь, файлы).
- **release (tag-only)** — `python-semantic-release` + cyclonedx-py SBOM.
- **final-verification** — только для MR в master: прогоняет
  `report_phases.py`, `check_phase_order.py`, `check_deps_matrix.py`.

Branch protection на `master` в GitLab (настраивается вручную/через
terraform): все перечисленные jobs — required.

## Definition of Done

- [x] `.gitlab-ci.yml` содержит 10 stages.
- [x] Нет test-stage (политика заказчика).
- [x] `no-tests-gate` hard-блок на `tests/`, `test_*.py`, `conftest.py`.
- [x] `progress-gate` в MR на master требует 0 незакрытых фаз.
- [x] `phase-gate` проверяет commit-format.
- [x] `regression-grep` блокирует запрещённые импорты.
- [x] `security` включает bandit, detect-secrets, creosote.
- [x] `build` включает Trivy scan.
- [x] `release` стадия собирает SBOM.
- [x] `docs/phases/PHASE_A5.md` (этот файл).
- [x] PROGRESS.md / PHASE_STATUS.yml (A5 → done).

## Как проверить вручную

```bash
# Локально эмулируем merge-gate:
poetry run ruff check . && poetry run ruff format --check .
poetry run bandit -c pyproject.toml -r src/
poetry run detect-secrets scan --baseline .secrets.baseline
python3 tools/report_phases.py
python3 tools/check_phase_order.py
python3 tools/check_deps_matrix.py
```

## Follow-up

- После закрытия Group 2 (B1, B2) сделать `type-check:mypy` blocking.
- В H4 подключить schema-based тесты (schemathesis) как
  `allow_failure: true` — не тесты, а контрактная валидация OpenAPI.
