# TECH DEBT — общий ledger технического долга

> **Append-only** ledger техдолга, видимый обоим агентам (Claude Code + Kimi Code).
> Заполняется постепенно по мере обнаружения проблем. **НЕ удалять** закрытые записи
> в течение 30 дней (для ретроспективы).

## Формат

```
## [YYYY-MM-DD HH:MM] <agent> — <slug>
**Status:** open | accepted | rejected | superseded | closed
**Severity:** low | medium | high | critical
**Location:** <file:line или модуль>
**Description:** <короткое описание проблемы>
**Impact:** <что ломается / замедляется / падает>
**Workaround:** <как обходить если есть>
**Plan:** <как планируется починить>
**Owner:** <когда будет чиниться>
**Related:** <ссылки на ADR / issues / commits>
```

## Open

<!-- append below -->

## [2026-06-02 17:45] ivan (gap analysis) — vault-cipher-dead-code
**Status:** open
**Severity:** low
**Location:** `src/backend/core/security/vault_cipher.py` (94 stmts) + `vault_cipher_sqlalchemy.py` (57 stmts)

**Description:** Оба файла имеют 0% coverage. Audit (T-P0.1.12 prep) показал
что они импортируются ТОЛЬКО друг другом, нет ни одного external usage
в `src/backend/`. Canonical implementation — `secret_rotation.py` (100% coverage,
используется в production).

**Impact:** 151 stmts мёртвого кода в core/security. Coverage `core/security`
занижен на ~14% (1045 строк → 284 miss, из них 151 = dead code).

**Workaround:** Не писать тесты для dead code (бессмысленно). При coverage
check игнорировать эти 2 файла через `# pragma: no cover` или coverage
exclude_patterns в pyproject.toml.

**Plan:** Удалить файлы в V23 cleanup (P15) после проверки dynamic imports
(`grep -r vault_cipher src/ tests/ docs/`). До удаления — добавить
`pragma: no cover` markers.

**Owner:** Ivan. V23 cleanup task.
**Related:** T-P0.1.12 (rpa_policy audit, side discovery).

## [2026-06-02 15:30] ivan (gap analysis) — pre-prod-check-coverage-timeout
**Status:** open
**Severity:** medium
**Location:** `tools/checks/pre_prod_check.py` gate 01 → `make coverage-gate` (pytest --cov)

**Description:** `make pre-prod-check` таймаутит на gate 01 (coverage ≥75%).
`make coverage-gate` запускает pytest с coverage instrumentation, не укладывается
в 600s (10 мин) timeout. Exit code 2.

**Impact:** Pre-prod-check baseline (38/38) недостижим в текущей среде. S38
не может использовать pre-prod-check как regression gate для T1.3+ рефакторингов.
V22.10.2 closeутверждал 38/38, но фактический запуск не подтверждает.

**Workaround:** Использовать `make lint && make type-check && make test` (без coverage)
как альтернативный gate. Coverage не regression-detector в S38.

**Plan:** Разобраться отдельно (возможно coverage instrumentation медленная, или
test suite больше чем ожидалось). Не блокер для S38 (альтернативный gate есть).

**Owner:** Ivan. Решение отложено в S39 (или раньше, если будет время).
**Related:** S38_V23_PLAN.md, V9_VS_V22_GAP.md, TECH_DEBT.md запись
`python-version-doc-drift`.

## [2026-06-02 14:00] ivan (gap analysis) — python-version-doc-drift
**Status:** open
**Severity:** low
**Location:**
- `pyproject.toml::project.description` ("Python 3.14")
- `pyproject.toml::project.requires-python` ("\>=3.13,\<3.14")
- `AGENTS.md:12`, `CLAUDE.md:11,349`, `ARCHITECTURE.md:5,258` ("Python 3.14+")
- `README.md`, `.claude/rules/{online-research,refactoring,dependency-decision}.md`
- `.claude/{DECISIONS,KNOWN_ISSUES}.md`, `.claude/agents/system-analyst.md`
- `src/frontend/streamlit_app/pages/04_Onboarding.py:37`
- `src/frontend/streamlit_app/pages/05_Architecture_Map.py:86`
- `src/frontend/static/js/architecture_graph.js:8`
- `scripts/pip_audit_gate.py:19`
- `tests/unit/core/ai/policy/test_enforcer.py:296`
- `vault/session-2026-05-22-1824-summary.md`
- `vault/session-2026-05-26-S27-P0-AI-Hardening-W345-summary.md`
- `vault/archive-plan-v21.md`

**Description:** Расхождение между `pyproject.toml::requires-python = ">=3.13,<3.14"`
(проект исполняется на Python 3.13) и 20+ местами в документации/rules/UI,
которые говорят "Python 3.14+".

**Impact:** Вводит в заблуждение. Документы могут предполагать совместимость
с Python 3.14 (wheel, синтаксис, type hints), которой нет в CI/dev_light.
Низкий риск — все CLI/CI запускаются на 3.13.

**Workaround:** Не предпринимать до принятия решения.

**Plan:** Решение требуется от Ivan. Варианты (см. `.shared/context/V9_VS_V22_GAP.md`):
- A) `>=3.13,<3.14` → фиксить 20+ файлов документации
- B) `>=3.14,<3.15` → фиксить pyproject.toml (риск совместимости)
- C) `>=3.13,<3.15` → расширить window, документы OK
- D) Оставить как есть (текущее решение)

**Owner:** Ivan. Решение отложено в S39 (после S37 W1 closure).
**Related:** v9 §Часть II (Python 3.14 compatibility), `.shared/context/V9_VS_V22_GAP.md`,
`.hermes/plans/S38_V23_PLAN.md` §W0 T0.1

## Closed (за последние 30 дней)

<!-- append below -->
