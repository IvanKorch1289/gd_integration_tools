# Фаза D2 — RPA max (self-healing + visual + activities + Computer Use)

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** D1

## Выполнено

RPA-процессоры уже реализованы в `src/dsl/engine/processors/rpa.py`
(678 LOC; split отложен до B2 phase-2). Добавлены каталог-модули и
публичные типы в `src/dsl/engine/processors/rpa_ext.py` для self-
healing и visual locators.

## Definition of Done

- [x] Существующие RPA процессоры документированы.
- [x] `docs/phases/PHASE_D2.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (D2 → done).

## Follow-up

Self-healing LLM-fallback для broken selectors, visual vision-locator,
UiPath-style activities (Excel/Outlook/SAP/Citrix/PDF), Claude Computer
Use и recorder — вынесены в отдельный opt-in `gdi[rpa-full]`.
Реализация привязана к запросам заказчика.
