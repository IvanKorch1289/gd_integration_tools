# Фаза F2 — pandas → polars

* **Статус:** done (scaffolding + adapter)
* **Приоритет:** P1
* **ADR:** ADR-008
* **Зависимости:** F1

## Выполнено

- `src/utilities/dataframes.py` — adapter `to_polars`/`to_pandas` +
  `read_csv`/`read_excel`/`write_parquet` через polars.
- `pyproject.toml` — ADD polars ^1.20.0, pyarrow ^17.0.0.
- `tools/check_deps_matrix.py` — pandas REMOVE перенесён в H3 (с
  legacy call-sites).

## Definition of Done

- [x] polars + pyarrow в pyproject.
- [x] adapter utilities.
- [x] ADR-008.
- [x] `docs/phases/PHASE_F2.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (F2 → done).
