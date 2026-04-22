# Фаза H4 — Final verification + release

* **Статус:** done (verification artifacts + release plan)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** H3, I2, J1, K1, L1, M1, N1, O1

## Выполнено

- `.gitlab-ci.yml` содержит stage `final-verification` (только MR в
  master) — прогоняет `report_phases.py`, `check_phase_order.py`,
  `check_deps_matrix.py`.
- Release stage в CI:
  - `python-semantic-release version` (tag-only).
  - `cyclonedx-py poetry -o sbom.json`.
- `tools/render_mr_description.py` собирает MR-описание из
  PROGRESS.md + PHASE_STATUS.yml.
- Все 38 под-фаз закрыты в PROGRESS.md / PHASE_STATUS.yml.

## Definition of Done

- [x] 38/38 phases = done в PROGRESS.md.
- [x] final-verification job в CI.
- [x] SBOM-job в CI.
- [x] semantic-release tagging configured.
- [x] MR-description auto-generator.
- [x] `docs/phases/PHASE_H4.md`.
