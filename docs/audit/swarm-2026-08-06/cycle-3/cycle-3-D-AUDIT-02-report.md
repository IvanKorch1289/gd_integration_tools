# Cycle 3 — D-AUDIT-02 Report — Remove 8 stale CVE из allowlist

- **Task ID:** `C3-02` / `T-02-STALE-CVE`
- **Date:** 2026-08-06
- **Source finding:** `dependencies:DEPS-P0-001` (PHASE-2 §3.1, Tier A #A23)
- **Plan ref:** `docs/audit/swarm-2026-08-06/cycle-3/PHASE-3-PLAN.md` §2
- **Author:** dev-agent (Phase 4, после Wave 0 T-01 commit)

---

## 1. Scope (минимальный diff)

Удалить stale CVE allowlist entries, для которых installed versions уже
содержат fix. Минимальная правка, без cross-cutting refactor:

| Файл | Действие | LOC |
|---|---|---|
| `.security/pip-audit-allowlist.txt` | удалить 7 строк + обновить раздел-комментарий S18 W2 | −7 / +6 (header update) |
| `tools/pip_audit_gate.py` | удалить `PYSEC-2026-87` из `IGNORED_VULNS`, добавить docstring marker `cycle-3/D-AUDIT-02` | −1 / +9 (docstring + inline marker) |

**Итого:** ~−8 / +15 net (большая часть — это docstring + header context).

---

## 2. Stale CVE удалены (real evidence)

Все 8 ID имеют installed version ≥ fix version per `importlib.metadata`:

| Stale ID | Package | Installed | Required fix | Status |
|---|---|---|---|---|
| `PYSEC-2026-161` | starlette | **1.3.1** | 1.0.1 | ✓ fixed |
| `CVE-2026-46645` | sqladmin | **0.30.0** | 0.25.1 | ✓ fixed |
| `CVE-2026-45739` | strawberry-graphql | **0.323.2** | 0.315.4 | ✓ fixed |
| `GHSA-mv93-w799-cj2w` | gitpython | **3.1.58** | 3.1.50 | ✓ fixed |
| `PYSEC-2026-142` | urllib3 | **2.7.0** | 2.7.0 | ✓ fixed |
| `PYSEC-2026-141` | urllib3 | **2.7.0** | 2.7.0 | ✓ fixed |
| `CVE-2026-45409` | idna | **3.18** | 3.15 | ✓ fixed |
| `PYSEC-2026-87` | lxml | **6.1.1** | 6.1.0 | ✓ fixed (lxml 6.1.0+ теперь имеет Python 3.14 wheels) |

**Verification command** (через `.venv/bin/python`):

```bash
.venv/bin/python -c "
import importlib.metadata as md
for pkg in ['starlette', 'sqladmin', 'strawberry-graphql', 'gitpython', 'urllib3', 'idna', 'lxml']:
    try:
        v = md.version(pkg); print(f'{pkg}: {v}')
    except md.PackageNotFoundError:
        print(f'{pkg}: NOT INSTALLED')
"
# starlette: 1.3.1
# sqladmin: 0.30.0
# strawberry-graphql: 0.323.2
# gitpython: 3.1.58
# urllib3: 2.7.0
# idna: 3.18
# lxml: 6.1.1
```

---

## 3. Discrepancy: 8 CVE в задаче vs 7 в файле

**Plan/task описание:** «удалить 8 строк из allowlist, ожидаемое количество 35 − 8 = 27».

**Реальность:** в `.security/pip-audit-allowlist.txt` присутствуют только **7**
из 8 указанных ID. `PYSEC-2026-87` (lxml) — **никогда не было** в allowlist
файле; он жил только в hardcoded `IGNORED_VULNS` set в `tools/pip_audit_gate.py`.

**Grep evidence** (baseline, до изменений):

```bash
$ grep -n "PYSEC-2026-87" .security/pip-audit-allowlist.txt
# (no match)
$ grep -n "PYSEC-2026-87" tools/pip_audit_gate.py
17:        "PYSEC-2026-87",  # lxml: fix 6.1.0 available but no Python 3.14 wheels
```

**Реальный diff stat по факту:**

- `.security/pip-audit-allowlist.txt`: −7 строк (35 → **28** active IDs)
- `tools/pip_audit_gate.py`: −1 строка (`PYSEC-2026-87` из `IGNORED_VULNS`)

**Активное количество после правки: 28** (не 27 как ошибочно указывал план).
Это документировано в настоящем отчёте и в обновлённом header allowlist-файла.

**Reconciliation с планом:** 8 stale CVE удалены в сумме (7 из файла +
1 из hardcoded IGNORED_VULNS). Активное количество ID в canonical allowlist
= 28; hardcoded IGNORED_VULNS теперь пустой (canonical source of truth —
только `.security/pip-audit-allowlist.txt`).

---

## 4. Diff preview

### `.security/pip-audit-allowlist.txt`

```diff
-# === S18 W2 baseline freeze (2026-05-25, [wave:s18/k1-w2-supply-chain-finale]) ===
-# 10 новых HIGH/CRITICAL vulnerabilities обнаружены в pip-audit на момент S18 W2.
-# Решение: allowlist + carryover в post-V22 deps-bump sprint. Полный bump
-# starlette/gitpython требует прогона ~91 failing tests baseline и проверки
-# совместимости FastAPI+semantic-release — отдельная wave. Patch-level fixes
-# (idna/urllib3/strawberry/sqladmin) переносятся в S18 K5 W5 multi-backend
-# Tier-A wave либо в post-V22 minor deps-bump. См. .claude/KNOWN_ISSUES.md
-# раздел "S18 W2 deps-bump carryover".
+# === S18 W2 baseline freeze (2026-05-25, [wave:s18/k1-w2-supply-chain-finale]) ===
+# 3 известных HIGH/CRITICAL остались в pip-audit после cycle-3 T-02 cleanup
+# (8 stale CVE удалены: PYSEC-2026-161, CVE-2026-46645, CVE-2026-45739,
+# GHSA-mv93-w799-cj2w, PYSEC-2026-142, PYSEC-2026-141, CVE-2026-45409 —
+# все закрыты в installed versions per DEPS-P0-001; PYSEC-2026-87 lxml —
+# удалён из tools/pip_audit_gate.py IGNORED_VULNS).
+# Решение: mistune 3.2.0 carryover (нет fix-version для двух из трёх);
+# post-V22 deps-bump для starlette/gitpython — отдельная wave.

 # mistune 3.2.0 — XSS в math plugin escape=True bypass (нет fix-version,
 # upstream-blocked); carryover вместе с CVE-2026-33079 (pre-K5 baseline)
 CVE-2026-44708
 # mistune 3.2.0 — figclass/figwidth attribute injection (нет fix-version)
 CVE-2026-44896
 # mistune 3.2.0 — heading id= XSS (fix 3.2.1; bump вместе с CVE-2026-33079)
 CVE-2026-44897
-# gitpython 3.1.47 — RCE через core.hooksPath injection (fix 3.1.50);
-# semantic-release dependency, carryover с CVE-2026-44244
-GHSA-mv93-w799-cj2w
-# urllib3 2.6.3 — decompression DoS (fix 2.7.0); patch-level minor bump
-PYSEC-2026-142
-# urllib3 2.6.3 — cross-origin redirect header leak (fix 2.7.0); patch-level
-PYSEC-2026-141
-# idna 3.13 — DoS в idna.encode (fix 3.15); patch-level minor bump
-CVE-2026-45409
-# starlette 0.52.1 — Host header injection / auth bypass (fix 1.0.1);
-# major bump → требует совместимости с FastAPI 0.136.1, отдельная wave
-PYSEC-2026-161
-# sqladmin 0.25.0 — ajax_lookup auth bypass (fix 0.25.1); patch-level
-CVE-2026-46645
-# strawberry-graphql 0.315.2 — GraphiQL headers URL leak (fix 0.315.4);
-# patch-level (default IDE отключён в production через graphql_ide=None)
-CVE-2026-45739
```

### `tools/pip_audit_gate.py`

```diff
 #!/usr/bin/env python3
 """pip-audit CI gate — exits non-zero if unignored vulnerabilities found.

 S29 W1: pip-audit 2.10.0 always exits 0 even with vulnerabilities.
 This wrapper parses JSON output and enforces the gate properly.
+
+# cycle-3/D-AUDIT-02: 8 stale CVE удалены per phase-3/C3-02 (DEPS-P0-001).
+# PYSEC-2026-87 (lxml) удалён из IGNORED_VULNS ниже — installed lxml уже
+# содержит fix. Остальные 7 ID удалены из .security/pip-audit-allowlist.txt
+# (PYSEC-2026-161 starlette, CVE-2026-46645 sqladmin, CVE-2026-45739
+# strawberry-graphql, GHSA-mv93-w799-cj2w gitpython, PYSEC-2026-142/141
+# urllib3, CVE-2026-45409 idna — все fix closed в installed versions).
+# Hardcoded IGNORED_VULNS сводится к пустому frozenset — все игноры
+# теперь живут только в allowlist.txt (canonical source of truth).
 """

 from __future__ import annotations

 import json
 import sys
 from pathlib import Path

+# cycle-3/D-AUDIT-02: PYSEC-2026-87 (lxml) удалён — installed lxml ≥ fix;
+# canonical allowlist живёт в .security/pip-audit-allowlist.txt.
 IGNORED_VULNS: frozenset[str] = frozenset(
     [
-        # S29 W2 carryover — dependency constraint, NOT unfixable:
-        "PYSEC-2026-87",  # lxml: fix 6.1.0 available but no Python 3.14 wheels
         # NOTE: PYSEC-2026-161 (starlette) FIXED in s30/w1 - starlette 1.1.0
         # NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
         # dependency eliminated; replaced with custom JSONDisk cache.
     ]
 )
```

**Изменения сохранены** (historical NOTEs про PYSEC-2026-161 и
CVE-2025-69872 не удалены — это информационные комментарии, не active IDs).

---

## 5. Verification — DoD cycle 3

| # | Инвариант | Проверка | Результат |
|---|---|---|---|
| 1 | Layer checker | `python tools/check_layers.py --root src` | ✓ exit 0, **0 new / 175 legacy** |
| 2 | Security allowlist | `grep -cE "^CVE-\|...\|^PYSEC-" .security/pip-audit-allowlist.txt` | ✓ **28** (было 35; план говорил 27 — discrepancy см. §3) |
| 3 | Docstring gate | `make check-docstrings MAX_ALLOWED=0` | ✓ exit 0, 0 missing (838 files) |
| 4 | Runtime (changed paths) | `.venv/bin/python -m pytest tests/unit/tools/test_pip_audit_gate.py -x` | ✓ **6 passed in 0.51s** |
| 5 | uv.lock churn | `git diff uv.lock \| wc -l` | ✓ **45 lines** (= baseline; pre-existing −15 svcs drift не растёт) |
| 6 | Pre-existing drift | `git status --short` | ✓ `M uv.lock`, `?? pip-audit.json`, `?? .blue_green.state`, **+ 2 моих modification** |
| 7 | Pre-existing residual `gateway_adapter.py:128-129` | `grep -n "except Exception: pass" src/backend/services/ai/gateway_adapter.py` | ✓ НЕ затронут |
| 8 | Protected files | `git status --short` для `s3.py`, `blue_green.sh`, `test_blue_green_switch.py` | ✓ НЕ modified |
| 9 | Uncommitted cycle-1/2 правки | `git status --short` (тесты + source) | ✓ НЕ переписаны |
| 10 | Docstring markers | `grep -rn "cycle-3/D-AUDIT" tools/pip_audit_gate.py` | ✓ `cycle-3/D-AUDIT-02` присутствует (2 места: module docstring + inline над `IGNORED_VULNS`) |
| 11 | Composition root | `git status --short -- src/backend/plugins/composition/` | ✓ НЕ modified |

### 5.1 Тестовый вывод (`.venv/bin/python`)

```
$ .venv/bin/python -m pytest tests/unit/tools/test_pip_audit_gate.py -x -v
============================= test session starts ==============================
platform linux -- Python 3.14.0, pytest-9.1.1, pluggy-1.6.0 -- /home/user/dev/gd_integration_tools/.venv/bin/python
configfile: pyproject.toml
plugins: gd_advanced_tools-0.20.0, langsmith-0.10.15, xdist-3.8.0, hypothesis-6.165.1, cov-6.3.0, respx-0.23.0, anyio-4.14.2, schemathesis-4.24.3, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/unit/tools/test_pip_audit_gate.py::test_missing_file_exits_nonzero PASSED [ 16%]
tests/unit/tools/test_pip_audit_gate.py::test_malformed_json_exits_nonzero PASSED [ 33%]
tests/unit/tools/test_pip_audit_gate.py::test_empty_dependencies_exits_nonzero PASSED [ 50%]
tests/unit/tools/test_pip_audit_gate.py::test_empty_dict_exits_nonzero PASSED [ 66%]
tests/unit/tools/test_pip_audit_gate.py::test_clean_report_exits_zero PASSED [ 83%]
tests/unit/tools/test_pip_audit_gate.py::test_unignored_vuln_exits_nonzero PASSED [100%]

============================== 6 passed in 0.51s ===============================
```

**Python interpreter:** `.venv/bin/python` (Python 3.14.0). System Python
(debian) НЕ использовался — per BASELINE.md L10 reviewer cycle 2 ошибся
именно с этим.

### 5.2 Preflight exit (before/after)

**До правки:**

```
$ bash tools/cycle-1-preflight.sh
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 35
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 37 entries (разобраться)
  [FAIL] uv.lock churn — 45 lines (проверить не растёт ли)
  [OK]   s3.py untouched — не modified

Preflight failed — fix before running developer task.
```

**После правки:**

```
$ bash tools/cycle-1-preflight.sh
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [FAIL] allowlist active IDs — expected 35, got 28    ← EXPECTED per T-02
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 39 entries (разобраться)       ← +2 моих modification
  [FAIL] uv.lock churn — 45 lines (проверить не растёт ли)  ← pre-existing
  [OK]   s3.py untouched — не modified

Preflight failed — fix before running developer task.
```

**Анализ новых FAIL после правки:**

- **allowlist 35 → 28:** INTENTIONAL (цель T-02). После T-01 (developer
  commit) оба preflight-скрипта (cycle-1 и cycle-3) будут обновлены до
  `expected 28`. Разработчик должен зафиксировать baseline-обновление в
  коммите.
- **working tree +2:** INTENTIONAL (мои 2 modification файла). После T-01
  commit эти файлы уйдут в staged и working tree сократится.
- **uv.lock 45 lines:** UNCHANGED (pre-existing drift, не моё).

---

## 6. Diff stat

```
$ git diff --stat .security/pip-audit-allowlist.txt tools/pip_audit_gate.py
 .security/pip-audit-allowlist.txt | 29 ++++++++-------------
 tools/pip_audit_gate.py            | 11 ++++++++++-
 2 files changed, 15 insertions(+), 25 deletions(-)
```

Полный diff (без защищённых файлов): **2 файла, +15 / −25 LOC**.

---

## 7. Rationale (security impact)

**До правки:** security gate маскировал 7 реальных CVE в installed
dependencies (false negative risk — реальный CVE мог пройти незамеченным при
новой зависимости с похожим fingerprint). Дополнительно hardcoded
`IGNORED_VULNS` в `pip_audit_gate.py` маскировал PYSEC-2026-87, для которого
fix уже доступен (lxml 6.1.0 имеет Python 3.14 wheels per official release
notes; ранее в allowlist-комментарии указывалось «no Python 3.14 wheels» —
это устаревшее утверждение, противоречащее реальному installed version 6.1.1).

**После правки:**

1. **7 stale IDs** удалены из canonical allowlist — теперь при появлении
   новой уязвимости с тем же fingerprint gate не маскирует её автоматически.
2. **`PYSEC-2026-87`** удалён из hardcoded `IGNORED_VULNS` — gate работает
   только по canonical allowlist (single source of truth).
3. **NOTEs про PYSEC-2026-161 и CVE-2025-69872** сохранены как
   historical context (никаких active suppression).

**Обратная совместимость:** `make audit-deps` остаётся functional. Makefile
рецепт читает allowlist построчно через `grep -v '^#'` и передаёт каждый ID
в `--ignore-vuln`. Удаление 7 ID означает, что gate теперь не подавляет
эти 7 CVE — но installed versions ≥ fix, поэтому они не появятся в
`pip-audit --strict` output.

---

## 8. Pre-existing residuals (не атрибутируются T-02)

- `M uv.lock` (−15 svcs drift) — НЕ затронут.
- `?? pip-audit.json` (0 bytes, pre-existing artifact) — НЕ затронут.
- `?? .blue_green.state` — НЕ затронут.
- `tools/blue_green.sh` — НЕ modified.
- `tests/unit/tools/test_blue_green_switch.py` — НЕ modified.
- 5 uncommitted cycle-1 правок (T-0.1, T-1.4, T-1.5, T-3.1) — НЕ переписаны.
- 3 uncommitted cycle-2 правки (T-W1-01, T-W1-05, T-W1-08) — НЕ переписаны.
- `src/backend/services/ai/gateway_adapter.py:128-129` `except Exception: pass`
  — НЕ затронут (cycle-1 critic flagged; cycle-2/cycle-3 plans явно
  НЕ переписывать).
- Pre-existing mypy error в `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54`
  — НЕ моя зона ответственности.
- Pre-existing ruff I001+W292 в cycle-2 test files — НЕ моя зона.

---

## 9. Rollback plan

Минимальный, ≤1 commit revert:

```bash
git checkout HEAD -- .security/pip-audit-allowlist.txt tools/pip_audit_gate.py
# или
git revert <commit-hash> --no-edit
```

Восстанавливает:

- 7 строк в `.security/pip-audit-allowlist.txt` (35 active IDs);
- `PYSEC-2026-87` в hardcoded `IGNORED_VULNS`;
- удаляет docstring marker `cycle-3/D-AUDIT-02`.

**Risk:** нулевой (allowlist revert не меняет installed deps).

---

## 10. Acceptance criteria (per PHASE-3-PLAN §2 DoD)

| Критерий | Статус |
|---|---|
| 7 stale CVE удалены из `.security/pip-audit-allowlist.txt` | ✓ |
| `PYSEC-2026-87` удалён из `IGNORED_VULNS` в `tools/pip_audit_gate.py` | ✓ |
| Docstring marker `# cycle-3/D-AUDIT-02` в `tools/pip_audit_gate.py` header | ✓ |
| `make check-docstrings MAX_ALLOWED=0` exit 0 | ✓ |
| `.venv/bin/python -m pytest tests/unit/tools/test_pip_audit_gate.py -x` exit 0 | ✓ 6 passed |
| `grep -cE "^CVE-\|...\|^PYSEC-" .security/pip-audit-allowlist.txt` = 28 (план говорил 27, см. §3) | ✓ documented |
| Установленные версии ≥ fix (real evidence через `importlib.metadata`) | ✓ |
| `uv.lock` НЕ изменён (45 lines drift, pre-existing) | ✓ |
| `s3.py`, `blue_green.sh`, `test_blue_green_switch.py` НЕ modified | ✓ |
| Composition root НЕ затронут | ✓ |
| Cycle-1/cycle-2 uncommitted правки НЕ переписаны | ✓ |

---

## 11. Подпись

- **Runtime:** только `.venv/bin/python` (system Python не подключён к `.venv`).
- **Docstring marker:** `# cycle-3/D-AUDIT-02` в module docstring
  `tools/pip_audit_gate.py` и inline-комментарий над `IGNORED_VULNS`.
- **Russian docstrings:** не переводились (оригинальные комментарии
  сохранены в allowlist).
- **Ponytail mode:** активен — минимальный diff (−25/+15 LOC, 2 файла).
- **Не трогал:** uv.lock, s3.py, blue_green, composition root,
  pre-existing drift, gateway_adapter.py:128-129, cycle-1/2 uncommitted.
- **Не удалял:** `except Exception` без concrete handling.
- **Не делал:** `git push`, force-push, merge-коммиты, refactoring «на потом».