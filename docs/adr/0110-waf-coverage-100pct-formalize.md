# ADR-0110 — WAF Coverage 100% (formalize Sprint 41 #4 met)

* Статус: Accepted (Sprint 41 W4, 2026-06-09)
* Связано с: PLAN.md §5 (Sprint 41 #4 — WAF coverage); ADR-0050, ADR-0053.

## Контекст

Sprint 41 DoD #4: "WAF coverage — 100%". `make check-waf-coverage-strict зелёный`.

Существующие ADR по теме:
- **ADR-0050** — net WAF strict single entry (K1)
- **ADR-0053** — WAF phase2 migration (single httpx gateway)

Check: `tools/check_waf_coverage.py` (V15 S1):
- Сканирует `src/backend` на прямые `httpx.AsyncClient/Client` usage.
- Allowlist: `tools/check_waf_coverage_allowlist.txt`.
- `--strict` mode: ignore allowlist, blocking gate.

## Проверка

```bash
$ python tools/check_waf_coverage.py
WAF coverage OK: 0 violations

$ python tools/check_waf_coverage.py --strict
WAF coverage OK: 0 violations
```

**Оба режима** (regular + --strict) = **0 violations**. WAF coverage = 100%
по всем путям, без allowlist exceptions.

## Решение

Formalize: Sprint 41 DoD #4 уже закрыт в рамках существующего
WAF single-entry architecture (ADR-0050 + ADR-0053). Никакого
нового кода не требуется.

CI gate `make check-waf-coverage-strict` рекомендуется как blocking
check для PR'ов, чтобы предотвратить regression.

## Альтернативы

| Альтернатива | За | Против | Решение |
|---|---|---|---|
| Расширить coverage на extensions/ | Полнее покрытие | extensions/ — per-plugin sandbox; не в core | Отклонено (out of scope) |
| Добавить runtime check в middleware | Ловит bypasses at runtime | Уже есть в WAF middleware; check is static-analysis | Отклонено (duplicate) |
| **Formalize existing met state** | Зеркалит реальность; ADR audit-trail | — | **Принято** |

## Последствия

* **Позитивные**:
  * Sprint 41 DoD #4 = **closed** без нового кода.
  * CI gate `check-waf-coverage-strict` рекомендован как blocking.
  * ADR audit-trail для будущих maintainer'ов: "WAF coverage 100% —
    не новый work item, а maintainable invariant".
* **Риски**:
  * Если новый код введёт `httpx.AsyncClient` напрямую — check поймает,
    но нужен PR review для блокировки bypass attempts.
  * Митигация: pre-commit hook + `make check-waf-coverage-strict` в CI.

## Ссылки

* Check: `tools/check_waf_coverage.py` (V15 S1).
* Allowlist: `tools/check_waf_coverage_allowlist.txt` (не используется
  при `--strict`).
* Architecture: ADR-0050 (net WAF strict), ADR-0053 (WAF phase2).
* Pre-prod: `tools/checks/pre_prod_check.py` gate #14 (WAF coverage strict).
