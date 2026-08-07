# Cycle 1 — Домен A11: Dependencies & Supply-Chain

**HEAD**: `7f3d94a3` (2026-08-06)
**Дата аудита**: 2026-08-06
**Аудитор**: A11-агент (cycle 1, read-only)

---

## 0. Scope / что проверено

- `pyproject.toml` (1159 lines), `uv.lock` (10859 lines, 680 packages)
- `.security/pip-audit-allowlist.txt` (79 lines, **35 active CVE/GHSA/PYSEC IDs**)
- `.security/cosign.policy.md`, `.security/sbom.policy.md`
- `tools/pip_audit_gate.py` (66), `tools/verify_pypi_versions.py` (167)
- `tools/checks/{check_supply_chain,generate_sbom,run_pip_audit,cosign_sign,cosign_sign_all}.py`
- `tests/unit/tools/test_supply_chain_scaffold.py` (85) — **pytest прогон выполнен**
- `tools/cycle-1-preflight.sh`, `Makefile`, `make/security.mk`
- `dist/sbom.cdx.json` (226 components, **устарел**), `pip-audit.json` (**0 bytes**)
- `.github/workflows/security.yml` (243)

**Не проверено:** online pip-audit (network restricted), safety/gitleaks/trivy, OWASP ZAP,
`.gitlab/ci/.gitlab-ci.yml`, `.github/dependabot.yml`, `tools/checks/pre_prod_check.py`,
real `cyclonedx-py environment`.

---

## 1. Сводка готовности (5 категорий)

| Категория | % | Обоснование |
|---|---|---|
| **(a) Управление зависимостями и lockfile** | **70** | uv.lock актуален, override-dependencies корректны, environments ограничены. Минус: 7 deps без upper bound. |
| **(b) CVE allowlist + enforcement** | **30** | 35 active CVE, но 8 stale, 4-way drift, **fail-open gate через пустой pip-audit.json** (D-AUDIT-11-1). |
| **(c) SBOM + cosign signing** | **40** | Политики + scripts существуют. Минус: **SBOM устарел** (D-AUDIT-11-2), 3 разных target paths, `make audit-deps` НЕ оставляет JSON. |
| **(d) CI/CD pipeline coverage** | **35** | security.yml имеет blocking pip-audit, но deptry/creosote НЕ в CI, 4-way CVE drift. |
| **(e) Static analysis / phantom detection** | **50** | `tools/verify_pypi_versions.py` есть. Минус: нет `[tool.deptry]` config, `dep-decision.md` отсутствует. |
| **ИТОГО (weighted average)** | **45** | (70+30+40+35+50)/5 |

**Финальная оценка: 35/100** (по cycle-3 formula с дополнительными 5 P0).

---

## 2. Находки (P0)

| ID | Файл:строка | Описание |
|---|---|---|
| **D-AUDIT-11-1** | `tools/pip_audit_gate.py:26-32` + `pip-audit.json` (0 bytes) | **FAIL-OPEN security gate**: пустой JSON → gate возвращает PASS |
| **D-AUDIT-11-2** | `dist/sbom.cdx.json` (cryptography 41.0.7 vs uv.lock 49.0.0) | **SBOM устарел** — сгенерирован из `/usr/bin/python3`, не из `.venv` |
| **D-AUDIT-11-3** | `tests/unit/tools/test_supply_chain_scaffold.py:22,75` | **Тест FAILED**: ссылается на `Makefile.security` (НЕ существует), реальный `make/security.mk` |
| **D-AUDIT-11-4** | `make/security.mk:45-57` | **`make audit-deps` НЕ создаёт `pip-audit.json`** — stdout only, без `--output` |
| **D-AUDIT-11-5** | `make/security.mk:42` vs `tools/checks/generate_sbom.py:99` vs `check_supply_chain.py:170` | **3-way SBOM paths drift**: `dist/sbom.cdx.json` vs `dist/sbom/sbom.cdx.json` vs `dist/sbom/` |

---

## 3. Находки (P1)

| ID | Описание |
|---|---|
| **D-AUDIT-11-6** | 8 stale CVE IDs в active allowlist (installed ≥ fix-version, но всё ещё listed) |
| **D-AUDIT-11-7** | 4-way CVE drift: GitHub (2), GitLab (1), pip_audit_gate.py (1), Makefile (35) |
| **D-AUDIT-11-8** | `streamlit>=1.58.0` без upper bound в core deps (pyproject.toml:137) |
| **D-AUDIT-11-9** | Misleading comments в `pip_audit_gate.py:18-21` (diskcache НЕ удалён, JSONDisk не существует) |
| **D-AUDIT-11-10** | Hardcoded `IGNORED_VULNS` в `pip_audit_gate.py:14-22` дублирует allowlist |

---

## 4. Находки (P2/P3)

- **D-AUDIT-11-11** (P2): 7 deps без upper bound (fastapi, multipart, strawberry-graphql, granian, etc.)
- **D-AUDIT-11-12** (P2): Sphinx deps в `docs/api/requirements.txt` (mkdocs мигрирован B2)
- **D-AUDIT-11-13** (P2): deptry/creosote НЕ в CI
- **D-AUDIT-11-14** (P3): нет `[tool.deptry]` → 6794 false-positives
- **D-AUDIT-11-15** (P3): `migrate_dlq_partition.py:307` + `testkit/fixtures/s3_mock.py` — DEP001
- **D-AUDIT-11-16** (P3): `dep-decision.md` отсутствует (scope упоминал)

---

## 5. Верифицированные сильные стороны

- uv.lock (680 packages) актуален
- override-dependencies для CVE-конфликтов (lxml, urllib3, pyarrow)
- `.security/pip-audit-allowlist.txt` (35 active CVE) структурирован по волнам
- 27+ extras разнесены по доменам
- CycloneDX SBOM policy + cosign policy задокументированы
- `.github/workflows/security.yml::pip-audit` в blocking mode

---

## 6. Команды для воспроизведения

| Команда | Exit | Output |
|---|---|---|
| `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | 0 | `35` |
| `wc -c pip-audit.json` | 0 | `0` (EMPTY) |
| `python3 -c "import json; d=json.load(open('dist/sbom.cdx.json')); print([(c['name'],c['version']) for c in d['components'] if c['name'] in ['cryptography','starlette','urllib3']])"` | 0 | `[('cryptography','41.0.7'),('starlette','1.0.0'),('urllib3','2.0.7')]` |
| `ls -la Makefile.security` | 2 | Нет такого файла |
| `uv run pytest tests/unit/tools/test_supply_chain_scaffold.py -v` | 1 | `1 failed, 3 passed` |
| `grep -nE "deptry\|creosote" .github/workflows/*.yml` | 1 | 0 matches |
| `find /home/user/dev/gd_integration_tools -name "dep-decision*"` | 1 | 0 matches |

---

## 7. Запросы к смежным доменам

| Запрос | Домен |
|---|---|
| `tools/migrations/migrate_dlq_partition.py:307` — DEP001 clickhouse_connect | A1 |
| `testkit/fixtures/s3_mock.py:36,52` — DEP001 moto, boto3 | A1 |
| Sphinx requirements (DEPS-P2-001) | A12 |
| `pyproject.toml:613-616` `[tool.uv].environments` | A12 |
| Makefile + 17 `make/*.mk` | A12 |
| cosign SBOM подпись | A2 |
| `.security/zap-rules.tsv` | A2 |

---

## 8. Готовность домена: **35/100**

**Production-readiness для A11: ЗАБЛОКИРОВАН** до устранения 5 P0 + 5 P1 (RESIDUAL cycle-3).

**Главный риск:** новые CVE от доработок **НЕ блокируются** (fail-open gate через пустой
`pip-audit.json`). Разработчик может добавить зависимость с известной CVE в `pyproject.toml`,
и gate не сработает.

**Минимальные действия (по приоритету):**
1. **30 мин**: исправить `tools/pip_audit_gate.py` — exit 1 на empty JSON
2. **1 час**: добавить `--output pip-audit.json` в `make/security.mk:audit-deps`
3. **30 мин**: исправить `tests/unit/tools/test_supply_chain_scaffold.py:22` — `Makefile.security` → `make/security.mk`
4. **2 часа**: регенерировать SBOM через `.venv/bin/python`, удалить устаревший `dist/sbom.cdx.json`
5. **30 мин**: удалить 8 stale CVE из allowlist
6. **15 мин**: добавить `streamlit<2.0.0` upper bound
7. **2 часа**: унифицировать 4 enforcement точки
