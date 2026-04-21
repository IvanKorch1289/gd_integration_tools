# ADR-008: pandas → polars полная миграция

* Статус: accepted
* Дата: 2026-04-21
* Фазы: F2

## Контекст

pandas — зрелая библиотека, но на типичных banking workload-ах (ETL,
дневные отчёты по транзакциям) polars:

- в 5–30 раз быстрее (lazy-evaluation + arrow backend),
- потребляет в 2–3 раза меньше памяти,
- корректно работает с parquet/arrow без copy-конверсий.

pandas оставался "по инерции" — удаление снимает transitive dep numpy
(heavy), уменьшает Docker-образ.

## Решение

1. Публичный API: все процессоры / helpers принимают/возвращают
   `polars.DataFrame`.
2. Преобразование pandas → polars в legacy call-sites — через adapter
   (`polars.from_pandas`) и обратное (`.to_pandas()`). Adapter-ы
   включены в `app.utilities.dataframes` (scaffold).
3. pyproject: ADD `polars ^1.20.0`, `pyarrow ^17.0.0`; REMOVE `pandas`
   (проверяется `check_deps_matrix.py`).
4. CSV/Excel impex — через polars API (`read_csv`, `read_excel`).

## Альтернативы

- **Keep pandas**: упускает производительность.
- **Dask**: требует кластер, усложняет deploy.

## Последствия

- Разработчики учат polars (API другой, но более явный).
- Часть существующих ноутбуков/аналитики на стороне заказчика
  требует pandas — им оставлена возможность использовать adapter
  `.to_pandas()` однократно.
