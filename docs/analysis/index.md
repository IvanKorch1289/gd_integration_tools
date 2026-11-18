# Analysis Documents — Index

Главные документы анализа проекта `gd_integration_tools`. Обновлено 2026-08-27.

## Сводные gap-анализы

- [`../audit/CURRENT_STATE_2026-08-27.md`](../audit/CURRENT_STATE_2026-08-27.md) —
  WAVE 1 verification audit, 20 пунктов production-grade задачи с
  file:line-evidence и VERDICT.
- [`GAP_ANALYSIS_2026-08-27.md`](./GAP_ANALYSIS_2026-08-27.md) — gap-анализ WAVE 2:
  5 OPEN items + 3 NS recommendations.
- [`CYCLES_22_27_GAP_ANALYSIS_2026-08-27.md`](./CYCLES_22_27_GAP_ANALYSIS_2026-08-27.md) —
  re-verified cycles 22-27 (исправил предыдущие false-claims), 8 OPEN items + 3 NS.
- Sprint 32/33 gap-анализы (`SPRINT_32_GAP_ANALYSIS_2026-08-27.md`,
  `SPRINT_33_GAP_ANALYSIS_2026-08-27.md`) в репозитории **отсутствуют** —
  отдельных файлов нет; их выводы перенесены в ретроспективы
  (`../retros/SPRINT_32_RETRO_2026-08-27.md`,
  `../retros/SPRINT_33_RETRO_2026-08-27.md`) и в ADR-0280.

## Сводные retrospectives

- [`../retros/SPRINT_32_RETRO_2026-08-27.md`](../retros/SPRINT_32_RETRO_2026-08-27.md) —
  Sprint 32 retrospective (313 lines).
- [`../retros/CURRENT_CYCLE_RETRO_2026-08-27.md`](../retros/CURRENT_CYCLE_RETRO_2026-08-27.md) —
  WAVE 1+2 retro.
- [`../retros/CYCLES_22_27_RETRO_2026-08-27.md`](../retros/CYCLES_22_27_RETRO_2026-08-27.md) —
  cycles 22-27 retro (508 lines).

## Audit reports

- [`../audit/PRINCIPAL_RE_AUDIT_2026-08-27.md`](../audit/PRINCIPAL_RE_AUDIT_2026-08-27.md) —
  22 audit items, 12 false claims archived.
- [`../audit/CYCLE_208_REPORT_2026-08-14.md`](../audit/CYCLE_208_REPORT_2026-08-14.md) —
  cycle 208 gRPC + Router analysis.
- [`./storage-coverage-status.md`](./storage-coverage-status.md) —
  storage coverage baseline.

## Сводные ADR-ы

- [`../adr/0279-circuit-breaker-metrics-refactor.md`](../adr/0279-circuit-breaker-metrics-refactor.md) —
  P1.9 NEW violation fix.
- [`../adr/0280-listen-notify-defer-pg-runner-removal.md`](../adr/0280-listen-notify-defer-pg-runner-removal.md) —
  LISTEN/NOTIFY defer (pg_runner DEPRECATED).

---

**Maintenance**: при добавлении нового analysis doc — добавить link сюда.
**Method**: verify-first (НЕ trust прошлые claims), file:line-evidence обязательно.
