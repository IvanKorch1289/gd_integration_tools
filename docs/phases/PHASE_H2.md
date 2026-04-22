# Фаза H2 — Scaffolding + DSL visualization

* **Статус:** done (review + scaffold)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** H1

## Выполнено

Existing `tools/scaffold.py`, `tools/generate_resource.py`,
`tools/dsl_diff.py`, `tools/generate_api_client.py`,
`tools/generate_processors_doc.py` — уже присутствуют.

DSL visualization:
- `docs/grafana/dsl_dashboard.json` — для runtime visualization.
- `tools/dsl_diff.py` — diff v1 ↔ v2 маршрутов.
- DOT/Mermaid export — follow-up в H4 как
  `tools/dsl_cli/viz.py`.

## Definition of Done

- [x] scaffolding commands существуют.
- [x] dsl_diff.py есть.
- [x] `docs/phases/PHASE_H2.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (H2 → done).
