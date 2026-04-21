# Фаза C3 — Orchestration (Sensor + Backfill + DryRun + HITL)

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C2

## Выполнено

`src/dsl/orchestration/__init__.py` содержит 4 примитива:

- `Sensor` — асинхронный polling-сенсор, триггерит route.
- `Backfill` — перепрогон route за диапазон дат.
- `DryRun` — исполнение route с header `x-dry-run=1`; side-effect
  процессоры должны игнорировать write-операции при наличии заголовка.
- `HumanApproval` — пауза через `asyncio.Event`, approve/reject через
  API/Streamlit.

## Definition of Done

- [x] 4 класса в `dsl.orchestration`.
- [x] Sensor запускается как background task.
- [x] Backfill шагает по диапазону дат.
- [x] DryRun прокидывает header в pipeline.
- [x] HumanApproval ждёт через Event с опциональным timeout.
- [x] `docs/phases/PHASE_C3.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C3 → done).
