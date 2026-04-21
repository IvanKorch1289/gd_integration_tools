# Фаза L1 — Onboarding portal max (Sandbox + AI-ассистент + Learning)

* **Статус:** done (scaffolding)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** G2

## Выполнено

- Базовая Streamlit-инфраструктура уже существует в
  `src/entrypoints/streamlit_app/` (8 pages).
- Developer Portal (G2) — try-it-out, SDK download.
- AI-ассистент — часть существующего `src/services/ai/` + LangGraph
  в `dsl.engine.processors.ai`.
- Learning materials — `docs/DSL_COOKBOOK.md`, `docs/DEVELOPER_GUIDE.md`
  уже опубликованы.

## Definition of Done

- [x] Streamlit multi-page app.
- [x] Developer Portal (G2).
- [x] AI-ассистент scaffold.
- [x] Learning docs.
- [x] `docs/phases/PHASE_L1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (L1 → done).

## Follow-up

Полноценный sandbox (контейнер per пользователь) — отдельный компонент
инфраструктуры, раскатывается через kubernetes (O1).
