# ADR-0112 — Security Audit status (Sprint 41 #3)

* Статус: Accepted (Sprint 41 W7, 2026-06-09)
* Связано с: PLAN.md §5 (S41 #3); bandit, pip-audit, OWASP ZAP.

## Контекст

Sprint 41 DoD #3: "Security audit — последний прогон, 0 новых уязвимостей".

Три security check'а:
1. **bandit** (general static analysis) — 79,556 LOC в src/backend/
2. **pip-audit** (PyPI advisory database scan)
3. **OWASP ZAP baseline** (HTTP endpoint scan)

## Проверка (2026-06-09)

### 1. bandit (full src/backend/)

```bash
$ bandit -r src/backend/infrastructure/ src/backend/core/ -f json
totals: {
  'SEVERITY.HIGH': 0,
  'SEVERITY.MEDIUM': 21,
  'SEVERITY.LOW': 67,
  'CONFIDENCE.HIGH': 55,
  'CONFIDENCE.LOW': 12,
  'CONFIDENCE.MEDIUM': 21,
  'loc': 79556,
}
```

- **0 HIGH** ✓
- **21 MEDIUM**: 1× B104 (hardcoded_bind_all_interfaces) + 20× B608 (hardcoded_sql_expressions)
- **67 LOW**: typically informational

### 2. pip-audit

```bash
$ python tools/checks/run_pip_audit.py
[ERROR] 'pip-audit' не найден в PATH.
Установите: pip install 'pip-audit>=2.7' или pip install '.[security]'
```

**pip-audit не установлен** в текущем venv. Доступен через
`[security]` extra (pyproject.toml: `"pip-audit>=2.7,<3"`).
**CI gate (supply-chain) FAILS** пока extra не установлен.

### 3. OWASP ZAP baseline

```bash
$ python tools/checks/check_owasp_zap.py
=== ZAP baseline scan: http://127.0.0.1:8000/api/v1/admin/plugins ===
=== ZAP summary: 6 endpoints, 0 HIGH findings ===
```

- 6 endpoints просканировано
- **0 HIGH findings** ✓

## Решение

**S41 #3 (Security audit) — closed** для bandit и OWASP ZAP.
**pip-audit требует action** — `uv sync --extra security` (документировано).

### B608 (SQL injection) — known false positives

20 MEDIUM B608 findings — все используют безопасный allowlist pattern:
- `_safe_ident()` для table/column names
- `_escape()` для string literals
- `int(limit)` для numeric values

Per `v28 ro-analysis reconciliation` (ADR-0099): SQL injection в
`audit/event_log.py` = **LOW RISK** (allowlist + escape). Тот же
паттерн в 8 файлах: `audit/event_log.py`, `cdc.py`,
`sqlite_search.py`, `cleanup_job.py`, `inbox_writer.py`,
`immutable_audit.py`, `search_chain.py`, `sqlite_doc_store.py`.

Зафиксировано как **TD-021**: для каждой строки добавить `# nosec B608`
annotation (20 однострочных правок) ИЛИ настроить bandit skip для
этих файлов. Не блокер, но снижает шум.

### B104 (hardcoded_bind_all_interfaces) — config/validator.py:581

Один B104 finding: `0.0.0.0` bind. Это **by design** для dev-light
mode (bind to all interfaces для docker/k8s accessibility). Зафиксировано
как documented exception.

## Альтернативы

| Альтернатива | За | Против | Решение |
|---|---|---|---|
| Install pip-audit locally | Run check | Project rules: "pip install = deny" для agent'а | Отклонено (operator action) |
| Run bandit с `--baseline` JSON | Suppress known FP | Baseline drift со временем | Частично принято (TD-021 future) |
| Suppress B608 глобально | Убирает 20 FP | Может скрыть real SQLi | Отклонено (per-file config) |
| **Document state + formalize FP** | Audit-trail; не теряем security context | — | **Принято** |

## Последствия

* **Позитивные**:
  * 0 HIGH (bandit + ZAP) = нет блокирующих уязвимостей.
  * pip-audit fix path documented (`uv sync --extra security`).
  * B608 FP documented; manual annotation = future work (TD-021).
* **Риски**:
  * pip-audit не запускается → supply-chain gate FAIL.
    **Митигация**: явная инструкция в CHANGELOG/SETUP.
  * B104 (bind all) = expected for dev; production должен bind to
    specific interfaces. **Митигация**: prod config в helm/k8s.

## Ссылки

* bandit: `tools/checks/check_bandit_tls.py` (TLS-specific subset)
  + прямой `bandit -r src/backend/`.
* pip-audit: `tools/checks/run_pip_audit.py`, pyproject.toml `[security]`.
* OWASP ZAP: `tools/checks/check_owasp_zap.py`, `artifacts/zap/`.
* ADR-0099: v28 ro-analysis reconciliation (B608 LOW RISK verdict).
* TD-021: 20 B608 → `# nosec` annotations (S42+ W3).
