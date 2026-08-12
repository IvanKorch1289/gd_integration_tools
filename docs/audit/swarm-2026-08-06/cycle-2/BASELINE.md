# Cycle 2 — baseline

- Date: 2026-08-06
- HEAD: `ca5bff93058f2580041a7339913b52943babb329` (16 ahead of origin/master; +15 over documented cycle-1 baseline `b69d6b49`).
- Working tree: 10 modified files (cycle-1 uncommitted: 5 source + 3 test + 1 preflight + 1 tool) + 5 untracked. Все cycle-1 правки из Phase 4 (T-1.4 / T-1.5 / T-3.1) и `tools/cycle-1-preflight.sh` НЕ закоммичены. Роу cycle 2 не должен их ровнить — это ответственность developer commit step.
- Pre-existing drift: `M uv.lock` (-15 svcs, не в pyproject), `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state` — НЕ атрибутируется рою, не трогать.
- Layer checker: `python tools/check_layers.py --root src` → exit 0; **175 legacy / 0 new** (2273 files scanned).
- Security allowlist: `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → **35 active IDs** (стабильно от cycle 1).
- Docstring gate: `make check-docstrings MAX_ALLOWED=0` → 0 missing (838 files).
- Cycle 1 findings: 213 (37 P0 / 57 P1 / 61 P2 / 29 P3 / 29 P4) — 32 P0 / 56 P1 / 61 P2 / 28 P3 / 28 P4 **не закрыты** (Phase 4 cycle 1 покрыл только T-1.4 / T-1.5 / T-3.1 / T-0.1).
- Phase 4 plan cycle 1 deferred: T-1.1 (composition root), T-1.2 (SSE/HITL auth), T-1.3 (MQ DLQ data-loss), T-2.1 (reverse-layer cleanup), T-4.1 (text-RAG E2E test).
- Resolved in cycle 1: T-0.1, T-1.4, T-1.5, T-3.1. 4 закрыты, 5 отложены.

## Ограничения для cycle 2

- Phase 1 аналитики **обязаны перепроверить** все находки cycle 1, не считать их финальными.
- Аналитики читают только свой домен, не заимствуют выводы.
- Русские docstrings/comments не переводить.
- Числа не брать из cycle-1 markdown, проверять прогоном инструмента.
- Phase 1 запрещено менять source/lockfile/allowlist/s3.py/blue_green.
- Phase 1 сохраняет отчёт в `docs/audit/swarm-2026-08-06/cycle-2/phase-1/<NN>-<domain>.md`.
- **Новое в cycle 2**: расследовать причину РОСТА allowlist layer-violations (173→180 по заявлению пользователя; в момент cycle 2 baseline = 175). Зафиксировать непротиворечиво.
