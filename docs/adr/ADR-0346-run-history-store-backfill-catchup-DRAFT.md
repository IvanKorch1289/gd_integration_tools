# ADR-0346 (DRAFT): Run-history store для backfill/catchup scheduler-триггеров

- **Статус**: DRAFT
- **Дата**: 2026-09-24
- **Контекст**: V5 §4 P3-13 (backfill/catchup для scheduler-триггеров).
  Текущий `SchedulerFacade` (services/scheduler/facade.py, 74 LOC) — тонкая
  обёртка над APScheduler (`add_job/remove_job`, триггеры cron/interval/date)
  БЕЗ истории запусков: невозможно определить пропущенные запуски
  (catchup) и нет материала для backfill.

## Контекст проблемы

Airflow-семантика требует:
- **catchup=True/False**: при старте/рестарте — догонять ли пропущенные по
  расписанию запуски (interval между last_scheduled_run и now).
- **backfill(date_from, date_to)**: явный перезапуск периода истории.

Обе механики требуют **run-history**: per-job записи
`(job_id, scheduled_for, started_at, finished_at, status)`.

## Options

### A. Своя таблица `scheduler_run_history` (PostgreSQL, alembic-миграция)
- ✅ Полный контроль, общий пул соединений, tenant_id колонка из коробки
  (tenant-aware для будущей ретроспективной фильтрации).
- ❌ +1 таблица и миграция; дублирует часть APScheduler jobstore.

### B. APScheduler jobstore (SQLAlchemy) как источник истории
- ✅ Ноль новой схемы (APScheduler хранит next_run_time/... ).
- ❌ Jobstore хранит СОСТОЯНИЕ job'ов, а не ИСТОРИЮ исполнений;
  пропущенные запуски APScheduler всё равно не материализует —
  catchup всё равно требует своего ledger'а. Отклонено как неполное.

### C. Outbox-паттерн (event `scheduler.run.missed` через outbox)
- ✅ Единый механизм с W11 (outbox crash matrix уже покрыт тестами).
- ❌ Решает доставку события, но не «догоняющее исполнение» job'а;
  нужен поверх A. Отклонено как база, оставлено как дополнение.

## Decision (DRAFT — к утверждению владельцем scheduler-домена)

**A + C гибрид**: таблица `scheduler_run_history` (PK: job_id+scheduled_for;
status: pending/running/missed/done/failed; tenant_id; correlation_id) +
fan-out догоняющих запусков через существующий outbox (reuses W11 crash
semantics). Catchup-флаг per-job в `route.toml`/job-опциях
(`catchup: false` — дефолт для новых job'ов: не догонять ретроактивно).

## Consequences

- +1 alembic-миграция (SQLite-compatible: без CONCURRENTLY — гейт
  `check_alembic_migrations` следит).
- +`BackfillService(date_from, date_to, job_ids)` — materialize недостающие
  строки истории в статусе missed → последовательный запуск.
- Нагрузка: длина бэктест-окна ограничена конфигом
  (`scheduler.backfill_max_window_days`, default 31).
- Тесты: contract (insert missed → catchup → done), negative
  (catchup=false → пропуск, статус missed остаётся), crash между
  materialize и run (outbox semantics).

## Status of this ADR

DRAFT — требует: (1) согласования владельца scheduler-домена, (2) решения
per-job флаг storage (route.toml vs job-options), (3) оценки объёма
догоняющих запусков при первом старте с catchup=true.
