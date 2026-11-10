# ADR-0437 — Версии промптов: реестр + HTTP-поверхность + Prompt Lab

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0425 (контракт путей портала)
* Затрагивает: `src/backend/services/ai/prompt_registry.py`, `src/backend/core/di/providers/prompts.py`, `src/backend/entrypoints/api/v1/endpoints/admin_prompts.py`, `src/frontend/streamlit_app/pages/48_Лаборатория_промптов.py`

## Контекст

Панель «Prompt Lab» в портале была выключена: эндпоинтов не существовало, а
`PromptRegistry` умел только `register`/`get`/`get_compiled` — ни списка версий,
ни активации, ни сравнения.

## Решение

* Реестр: `list_prompts`, `list_versions`, `active_version`, `activate`,
  `compare` (diff шаблонов; `metric_diffs` — при наличии метрик Langfuse).
* HTTP: `GET/POST /api/v1/admin/prompt-versions`,
  `GET /api/v1/admin/prompt-versions/{name}`,
  `POST .../{name}/activate`, `GET .../{name}/compare?a=&b=`.
* DI-провайдер `get_prompt_registry_provider()` (singleton + test-override).
* Портал переведён на живые пути.

## Последствия

* A/B-сравнение версий доступно из портала; создание версии — с
  auto-increment номера.
* Метрики версий остаются внешними (Langfuse) — без них показывается diff
  шаблонов.
