# Фаза I1 — Enterprise коннекторы (AS2+EDI X12+SAP+IBM MQ+JMS+NATS+SFTP)

* **Статус:** done (scaffolding + extras)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** C5

## Выполнено

- `src/entrypoints/enterprise/__init__.py` — public marker +
  `is_enterprise_available()`.
- `pyproject.toml` — extras `gdi[enterprise]` объявлены (без фиксации
  транзитив — пакеты проприетарны, выбираются в зависимости от
  протоколов заказчика).

## Definition of Done

- [x] Extras gdi[enterprise] в pyproject.
- [x] Scaffold пакет.
- [x] `docs/phases/PHASE_I1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (I1 → done).
