# PHASE A1 — Baseline inventory + pre-commit + guardrails

**Статус:** in-progress. **Приоритет:** P0. **Зависимости:** —.

## Цель

Зафиксировать текущее состояние проекта и настроить всю anti-forget-инфраструктуру
до начала содержательных работ: Progress Ledger, Phase Status Registry, шаблон ADR,
лог deprecation, pre-commit hooks, self-audit-скрипт, набор CLI-утилит `tools/`.
Без A1 последующие фазы невозможно закрыть — merge-gate в GitLab CI (фаза A5)
будет падать.

## Что реализовано

- `docs/PROGRESS.md` — чек-лист из 38 под-фаз (A1..H4 базовая часть, I1..O1 расширения).
- `docs/adr/PHASE_STATUS.yml` — машиночитаемая версия чек-листа с зависимостями
  между фазами, списком артефактов и обязательных ADR.
- `docs/adr/TEMPLATE.md` — MADR-шаблон ADR на русском.
- `docs/DEPRECATIONS.md` — журнал shim-ов (пустой на старте, заполняется в A3/A4/...).
- `docs/phases/PHASE_A1.md` — эта документация фазы.
- `scripts/audit.sh` — локальный и CI-скрипт `scripts/audit.sh <phase-id>`.
- `tools/update_progress.py` — pre-commit hook (commit-msg stage), обновляет статус
  в `PROGRESS.md` и `PHASE_STATUS.yml` из префикса `[phase:<ID>]` в commit-message.
- `tools/check_phase_commit.py` — pre-commit hook (commit-msg stage), валидирует
  commit-format.
- `tools/check_adr_link.py` — pre-commit hook, требует ADR-<NNN> в commit-body
  для фаз из таблицы соответствия.
- `tools/check_no_tests.py` — hard-block: не даёт добавить `tests/`, `test_*.py`,
  `*_test.py`, `conftest.py` и импорты `pytest`/`pytest_asyncio`/`hypothesis`/
  `mutmut`/`testcontainers`/`pact`. Требование заказчика — тесты не пишутся.
- `tools/check_phase_order.py` — hard-block: нельзя закрыть фазу, пока
  её `depends_on` не в статусе `done`.
- `tools/check_deps_matrix.py` — сверка `pyproject.toml` с таблицами
  Dependency Matrix плана (ADD/REMOVE/REPLACE/KEEP).
- `tools/render_mr_description.py` — автоген описания MR из PROGRESS+STATUS.
- `tools/report_phases.py` — CLI-отчёт по статусу фаз.
- `.pre-commit-config.yaml` — расширен новыми hook-ами + bandit + creosote
  manual-stage.
- `.secrets.baseline` — базовый файл detect-secrets.
- `Makefile` — добавлены цели `audit`, `progress`, `phases`, `mr-description`.
- `pyproject.toml` — добавлены dev-deps: `vulture`, `pydeps`, `bandit`, `pyyaml`.

## Decision Record

ADR для фазы A1 не требуется — фаза организационная.

## Definition of Done

- [x] 16 файлов-артефактов созданы.
- [x] `docs/PROGRESS.md` содержит ровно 38 строк фаз.
- [x] `docs/adr/PHASE_STATUS.yml` валиден YAML.
- [x] `tools/*.py` имеют shebang и executable bit.
- [x] `scripts/audit.sh` executable.
- [ ] `pre-commit run --all-files` зелёный (первый прогон — baseline).
- [ ] Commit `[phase:A1] baseline inventory + anti-forget mechanics` создан.
- [ ] Запись в `PROGRESS.md` для A1 переведена в `done`.

## Как проверить

```sh
make audit PHASE=A1
make progress
make phases
poetry run pre-commit run --all-files
```

## Следующий шаг

Фаза **A2 Security hardening** — закрытие P0 security-дыр:
CORS + gRPC TLS + MQTT mTLS + IMAP via Vault + yaml whitelist + Makefile fix +
argon2 + удаление `passlib`/`psycopg2`/`async-timeout`/`aioboto3`.
