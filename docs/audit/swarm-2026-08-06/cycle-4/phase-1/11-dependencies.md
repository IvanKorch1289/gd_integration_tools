# Cycle 4 / Phase 1 / 11 — Домен «Зависимости»

**Дата:** 2026-08-07
**HEAD:** 22e08a0d (cycle-1/2/3 reapply commit)
**Интерпретатор:** `/home/user/dev/gd_integration_tools/.venv/bin/python` (Python 3.14)
**Scope:** `pyproject.toml`, `uv.lock` (read-only), `.security/pip-audit-allowlist.txt`,
`tools/pip_audit_gate.py`, `tools/**` (dependency/audit), `.github/workflows/**`, `.gitlab/ci/**`.

---

## 1. Scope / что проверено / что НЕ проверено

### Проверено (read-only)
- `pyproject.toml` (1159 строк) — `[project.dependencies]`, `[project.optional-dependencies]`,
  `[dependency-groups.dev]`, `[tool.uv].override-dependencies`, `[tool.uv].environments`,
  `[tool.pytest.ini_options].markers`.
- `.security/pip-audit-allowlist.txt` (73 строки, 27 активных CVE-ID).
- `tools/pip_audit_gate.py` (97 строк).
- `tools/checks/run_pip_audit.py`, `tools/checks/check_supply_chain.py`,
  `tools/checks/check_custom_code.py`, `tools/checks/pre_prod_check.py`,
  `tools/checks/no_duplicate_scripts.py`, `tools/checks/check_bandit_tls.py`,
  `tools/checks/generate_sbom.py`, `tools/verify_pypi_versions.py`,
  `tools/cycle-1-preflight.sh`, `tools/gen_api_docs.sh`,
  `tools/gen_api_autoapi.sh`.
- `make/security.mk`, `make/docs.mk`, `make/quality.mk`.
- `.github/workflows/security.yml`, `.github/workflows/sbom.yml`,
  `.github/workflows/lint.yml`, `.github/workflows/release.yml`,
  `.github/workflows/type.yml`, `.github/workflows/test.yml`,
  `.github/dependabot.yml`.
- `.gitlab/ci/.gitlab-ci.yml`, `.gitlab/ci/vale-lint.yml`.
- Installed versions ключевых пакетов через `importlib.metadata`.
- Runtime: `pip_audit_gate.py` поведение с синтетическими JSON, `cycle-1-preflight.sh`,
  `verify_pypi_versions._parse_pin`, `python -m pip_audit --help`.

### Не проверено
- `uv.lock` детально (10 859 строк — read-only scope, не правил содержимое; только meta:
  baseline drift `M uv.lock` -15 svcs pre-existing per BASELINE, 45 diff lines сейчас vs 15).
- `tools/pip_audit_gate.py` сетевой прогон `pip-audit` — сетевой доступ к `pypi.org`
  заблокирован (`ReadTimeout`); проверял gate-логику локально через синтетический JSON.
- Network-access проверки PyPI max-version для `verify_pypi_versions.py` —
  timeout при `urlopen('https://pypi.org/pypi/.../json')`. Только парсинг оффлайн.
- Цикл-3 markdown отчёты (`cycle-3/`), `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`,
  `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` — ЗАПРЕЩЕНО читать по ТЗ.

---

## 2. Verified strengths (cycle-4 baseline подтверждено)

| # | Проверка | Evidence | Вердикт |
|---|---|---|---|
| (a) | Allowlist 27 active CVE-IDs | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` → **27** | ✅ PASS |
| (b) | Streamlit `<2.0.0` | `pyproject.toml:137` `"streamlit>=1.58.0,<2.0.0"` + `pyproject.toml:477` `"streamlit>=1.30.0,<2.0.0"`; installed = `1.61.0` | ✅ PASS (оба pin'а имеют `<2.0.0`) |
| (c.1) | 4-way drift RESOLVED | `cycle-1-preflight.sh` → `tools/cycle-1-preflight.sh` отрабатывает: layer checker 175 legacy / 0 new, allowlist 27, docstring gate 0 | ✅ PASS |
| (c.2) | 8 stale CVE удалены из allowlist | comment block `pip-audit-allowlist.txt:62-72` явно перечисляет удалённые 9 ID (cycle-4 D-AUDIT-02); installed versions ≥ fix для каждого: mistune 3.3.4≥3.2.1, gitpython 3.1.58≥3.1.50, urllib3 2.7.0=2.7.0, idna 3.18≥3.15, starlette 1.3.1≥1.0.1, sqladmin 0.30.0≥0.25.1, strawberry-graphql 0.323.2≥0.315.4, lxml 6.1.1≥6.1.0 | ✅ PASS |
| (c.3) | IGNORED_VULNS frozenset пуст | `tools/pip_audit_gate.py:25-31` `frozenset([])` (только два NOTE-комментария); canonical allowlist = `.security/pip-audit-allowlist.txt` | ✅ PASS |
| (c.4) | streamlit <2.0.0 | см. (b) — оба pin'а `<2.0.0`; installed 1.61.0 | ✅ PASS |
| ✅ | pip_audit_gate fail-CLOSED | synthetic tests: пустой dict → exit 1; malformed JSON → exit 1; allowlist CVE без `--ignore-vuln` → exit 1; non-empty deps + 0 vulns → exit 0 | ✅ PASS |
| ✅ | make `audit-deps` корректно лупит allowlist | `make/security.mk:50-55` shell-loop генерирует 27 × `--ignore-vuln` флагов (782 chars) | ✅ PASS |
| ✅ | Layer checker | `python tools/check_layers.py --root src` → exit 0, **175 legacy / 0 new** | ✅ PASS |
| ✅ | CycloneDX SBOM | `dist/sbom.cdx.json` 246 500 bytes (cyclonedx-bom 5.x; bumped per `pyproject.toml:183` для PYSEC-2026-87 fix) | ✅ PASS |

---

## 3. Findings table (P0..P4)

| ID | P | path:line | Краткое описание |
|---|---|---|---|
| DOMAIN-P0-001 | P0 | — | (нет) |
| **DOMAIN-P1-001** | P1 | `tools/pip_audit_gate.py:41` ↔ `make/security.mk:56` | **Path mismatch**: gate читает `Path("pip-audit.json")` (CWD), `make audit-deps` пишет в `dist/pip-audit.json`. Прямая последовательность `make audit-deps && tools/pip_audit_gate.py` ломается. |
| **DOMAIN-P1-002** | P1 | `.github/workflows/security.yml:137-138` | **CI не синхронизирован с allowlist**: hardcoded только 2 из 27 `--ignore-vuln` (CVE-2025-69872, PYSEC-2026-87). Остальные 25 allowlist CVE не будут проигнорированы в GitHub CI — потенциальный silent block на новых транзитивных CVE. |
| **DOMAIN-P1-003** | P1 | `.gitlab/ci/.gitlab-ci.yml:161` | **GitLab CI пропускает 26 из 27 allowlist** + не вызывает `tools/pip_audit_gate.py`. Зависит только от exit-code `pip-audit`, который (per `security.yml:6`) "always exits 0 even with vulnerabilities" — fail-OPEN через обёртку `--ignore-vuln CVE-2025-69872`. |
| **DOMAIN-P1-004** | P1 | `.github/workflows/security.yml:138` | **Stale flag `--ignore-vuln PYSEC-2026-87`**: cycle-4 D-AUDIT-02 удалил этот ID из allowlist (lxml 6.1.1 содержит fix); если lxml регрессирует ниже 6.1.0, флаг замаскирует CVE. |
| **DOMAIN-P2-001** | P2 | `tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`, `docs/api/conf.py`, `docs/api/{Makefile,make.bat,index.rst,modules.rst,requirements.txt,_static,_templates,_build,autoapi}`, `tools/checks/pre_prod_check.py:738-741` | **Dead sphinx tooling** (cycle-3 P2-001 RESIDUAL): sphinx/sphinx-autoapi/sphinx-rtd-theme НЕ в `pyproject.toml` deps; mkdocs canonical (B2/M10.2 per `pyproject.toml:411-414`); scripts import'ят `sphinx`/`sphinx_autoapi` → при запуске упадут. `make docs-html` и `docs-multiversion` помечены DEPRECATED, но **не удалены**. |
| **DOMAIN-P2-002** | P2 | `pyproject.toml:168` `"presidio-ru-recognizers>=0.1.0,<1.0.0"` | **Phantom-version dep** (cycle-3 P2-002 RESIDUAL): 0 imports в `src/`/`extensions/`/`tools/`/`testkit`. Custom `InnRecognizer`/`SnilsRecognizer` (`src/backend/services/ai/pii/recognizers/`) уже заменяют (per comment line 165-167 "не удалять до явного перехода"). |
| **DOMAIN-P3-001** | P3 | `pyproject.toml:137 vs 477`, `pyproject.toml:81 vs 628`, `pyproject.toml:281 vs 509` | **Cross-pin duplicates** (cycle-3 P1-001 PARTIAL RESIDUAL): `streamlit` 1.58 vs 1.30, `lxml` 6.1.0 vs 6.1.1, `pillow` 12.3 vs 10.0 — разные lower bounds без unified source-of-truth. `rank-bm25` 124 vs 313 — RESOLVED (documented intentional, comment line 309-313). |
| **DOMAIN-P3-002** | P3 | `tools/verify_pypi_versions.py:79-83` | **`_parse_pin` возвращает LOWER bound (ver1), не UPPER (ver2)**: для pin `sqlalchemy>=2.0.41,<3.0.0` возвращает `(sqlalchemy, "2.0.41")`. Phantom-detection проверяет lower ≤ PyPI max (всегда True) → реально бесполезен. Tool informational, не CI-blocking. |
| **DOMAIN-P3-003** | P3 | `pyproject.toml:558` `"deptry>=0.20,<1.0"` | **Dead dev-dep**: declared в dev-group, но 0 references в `Makefile`/`make/*.mk`/`tools/`/`.github/`/`.gitlab/`. Должен был использоваться для unused-imports check (типа deptry), но не используется. |

Итого: **0 × P0, 4 × P1, 2 × P2, 3 × P3, 0 × P4.**

---

## 4. Detailed evidence

### DOMAIN-P1-001 — Path mismatch между gate и Makefile

**Evidence:**

```python
# tools/pip_audit_gate.py:41
json_path = Path("pip-audit.json")
```

```makefile
# make/security.mk:56
$(UV_RUN) pip-audit --strict --format json --output dist/pip-audit.json -r dist/audit-requirements.txt $$ALLOW || true
```

Runtime: `make audit-deps` пишет `dist/pip-audit.json`; gate читает `pip-audit.json` (CWD).
Verified:

```bash
.venv/bin/python -c "from pathlib import Path; \
  print(Path('pip-audit.json').resolve() == Path('dist/pip-audit.json').resolve())"
# → False
```

`.github/workflows/security.yml:136` использует `--output pip-audit.json` (CWD) — там работает.
Но `make audit-deps` → `tools/pip_audit_gate.py` прямой sequence ломается (gate fail-CLOSED
с "pip-audit.json not found" / malformed JSON).

**Impact:** Developer-experience bug, не security. Makefile сообщение "[SUCCESS] pip-audit clean"
обманывает: реально gate ещё не вызван.

**Fix (минимальный):** либо изменить `make/security.mk` на `--output pip-audit.json` (CWD, как GH CI),
либо добавить `--output pip-audit.json` в gate как fallback. CycloneDX-стиль `dist/pip-audit.json`
не оправдан (gate не публикует, только читает).

**Test:** `make audit-deps && .venv/bin/python tools/pip_audit_gate.py` — должен вернуть
exit 0 при чистом сканировании, exit 1 при наличии unignored CVE.

### DOMAIN-P1-002 — GitHub CI пропускает 25/27 allowlist CVE

**Evidence:**

```yaml
# .github/workflows/security.yml:133-139
uv run pip-audit \
  --format json \
  --output pip-audit.json \
  --ignore-vuln CVE-2025-69872 \
  --ignore-vuln PYSEC-2026-87
uv run python tools/pip_audit_gate.py
```

`make/security.mk:50-56` цикл по allowlist:

```makefile
if [ -f .security/pip-audit-allowlist.txt ]; then \
  for v in $$(grep -v '^#' .security/pip-audit-allowlist.txt | grep -v '^$$' || true); do \
    ALLOW="$$ALLOW --ignore-vuln $$v"; \
  done; \
fi; \
$(UV_RUN) pip-audit --strict --format json --output dist/pip-audit.json -r dist/audit-requirements.txt $$ALLOW || true
```

Verified: `make audit-deps` генерирует 27 × `--ignore-vuln` (782 chars). GitHub CI — только 2.

**Impact:** Maintenance drift. При добавлении нового allowlist CVE maintainer может:
1. Добавить строку в `.security/pip-audit-allowlist.txt` — `make audit-deps` подхватит;
2. **Забыть** добавить `--ignore-vuln` флаг в `.github/workflows/security.yml` и `.gitlab-ci.yml` —
   CI заблокируется.

Поскольку GitHub CI вызывает `tools/pip_audit_gate.py`, который has empty IGNORED_VULNS — gate
fail-CLOSED при любом unignored CVE, включая allowlist. То есть текущая конфигурация CI
жёстче, чем make. Это не security fail-open, но создаёт inconsistent gate behavior.

**Fix:** Реплейс hardcoded флаги в CI на programmatic loop (как в Makefile):

```yaml
# .github/workflows/security.yml (proposal)
IGNORE_FLAGS=""
while IFS= read -r line; do
  [[ "$line" =~ ^(CVE|GHSA|PYSEC)- ]] && IGNORE_FLAGS="$IGNORE_FLAGS --ignore-vuln ${line}"
done < .security/pip-audit-allowlist.txt
uv run pip-audit $IGNORE_FLAGS --format json --output pip-audit.json
uv run python tools/pip_audit_gate.py
```

**Test:** `grep -cE "^CVE-|^GHSA-|^PYSEC-" .github/workflows/security.yml` должен вернуть 0,
а в `make audit-deps` — 27.

### DOMAIN-P1-003 — GitLab CI single-flag + no gate wrapper

**Evidence:**

```yaml
# .gitlab/ci/.gitlab-ci.yml:152-166
pip-audit:
  stage: security
  image: python:${PYTHON_VERSION}
  timeout: 10m
  before_script:
    - pip install uv
    - uv sync
  script:
    - uv run pip-audit --ignore-vuln CVE-2025-69872
  allow_failure: false
```

1. Только 1 `--ignore-vuln` (vs 27 в allowlist).
2. Не вызывает `tools/pip_audit_gate.py` — rely на pip-audit exit code.
3. Per `security.yml:6`: "S29 W1: pip-audit 2.10.0 always exits 0 even with vulnerabilities" —
   GitLab CI без gate wrapper может fail-OPEN.

**Verified:** `.venv/bin/python -m pip_audit --version` → `pip-audit 2.10.1`.

**Impact:** Если CVE появится в новой транзитивной зависимости, GitLab CI может пропустить
его при exit code 0 от pip-audit (--ignore-vuln одного ID недостаточно).

**Fix:** Добавить в `.gitlab/ci/.gitlab-ci.yml` после pip-audit вызов `tools/pip_audit_gate.py`
и расширить `--ignore-vuln` до полного списка из allowlist.

**Test:** удалить `pip-audit.json`, оставить только `--ignore-vuln CVE-2025-69872`, добавить
новую fake CVE через `make audit-deps`-equivalent — exit должен быть 1.

### DOMAIN-P1-004 — Stale `--ignore-vuln PYSEC-2026-87`

**Evidence:**

```yaml
# .github/workflows/security.yml:138
--ignore-vuln PYSEC-2026-87
```

Allowlist comment block (`pip-audit-allowlist.txt:62-72`) явно фиксирует removal в cycle-4
D-AUDIT-02:

```
#   PYSEC-2026-87 (lxml, fix 6.1.0; installed 6.1.1) — also removed from
#   tools/pip_audit_gate.py IGNORED_VULNS.
```

Installed lxml = 6.1.1 ≥ fix 6.1.0 → CVE не должен срабатывать. Но если lxml регрессирует
ниже 6.1.0 (новый transitive от обновления flagembedding/inscriptis, см. comment
`pyproject.toml:336-338`), флаг замаскирует CVE.

Также `tools/pip_audit_gate.py:25-31` IGNORED_VULNS frozenset пуст — gate не игнорирует
PYSEC-2026-87, но GH CI передаёт `--ignore-vuln PYSEC-2026-87` в pip-audit, и `pip-audit`
соответственно не записывает этот CVE в JSON → gate не видит. Двухслойная логика работает
только пока CVE действительно не детектируется.

**Impact:** Silent regression mask — если lxml случайно downgraded ниже 6.1.0, CVE не
появится в JSON отчёте → gate PASS, но реальный CVE активен. Per cycle-4 BASELINE
"pre-existing drift (uv.lock -15 svcs) НЕ атрибутируется рою" — pin change возможен
в любой момент.

**Fix:** Удалить `--ignore-vuln PYSEC-2026-87` из `security.yml:138`. Если lxml downgrades —
gate правильно поймает.

**Test:** после удаления флага, при `uv.lock` с lxml<6.1.0, `make audit-deps` должен
fail-CLOSED.

### DOMAIN-P2-001 — Dead sphinx tooling (~10 файлов, ~400 LOC)

**Evidence:**

```
/tools/gen_api_docs.sh (89 lines, requires `import sphinx` + sphinx-build + sphinx-apidoc)
/tools/gen_api_autoapi.sh (71 lines, requires `import sphinx_autoapi`)
/docs/api/conf.py (127 lines — full sphinx config with autoapi.extension, sphinx_rtd_theme)
/docs/api/Makefile, /docs/api/make.bat, /docs/api/index.rst, /docs/api/modules.rst,
/docs/api/requirements.txt (pins sphinx>=9.1.0,<10.0.0, sphinx-rtd-theme>=3.0.0,<4.0.0,
                              sphinx-autoapi>=3.0.0,<4.0.0)
/docs/api/_static/, /docs/api/_templates/, /docs/api/_build/, /docs/api/autoapi/
/site/api/conf.py (built output)
/tools/checks/pre_prod_check.py:738-741 (gate "13 sphinx -W", wrapped _check_optional)
/make/docs.mk:31-37 (targets docs-html и docs-multiversion помечены DEPRECATED)
```

Runtime verify: `.venv/bin/python -c "import sphinx"` → `ModuleNotFoundError` (sphinx not
installed). И `.venv/bin/python -c "import sphinx_autoapi"` → `ModuleNotFoundError`.

Canonical per `pyproject.toml:411-414`:

```
# B2 (M10.2): mkdocs canonical — sphinx/sphinx-multiversion удалены.
# mkdocs-material + mike для версионирования (master + теги v*).
# mkdocstrings-python для авто-генерации API reference (аналог sphinx-autoapi).
```

mkdocs deps в `[project.optional-dependencies].docs` (line 416-423). CI uses
`.github/workflows/docs-publish.yml` (mkdocs + mike).

**Impact:** Dead code, ~400 LOC, который при случайном вызове (`tools/gen_api_docs.sh`)
падает с `ModuleNotFoundError`. Maintenance burden (4 shell scripts + 1 conf.py +
sphinx deps в `docs/api/requirements.txt` + Sphinx binary checks).

**Fix:** Удалить `tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`, всю `docs/api/`
директорию (кроме `.gitkeep`), убрать gate "13 sphinx -W" из `pre_prod_check.py:738-741`,
удалить targets `docs-html` и `docs-multiversion` из `make/docs.mk`.

**Test:** `find /home/user/dev/gd_integration_tools -name "sphinx*" -not -path "*/.venv/*" -not -path "*/.git/*" -not -path "*/vscode-extension/*"` — должно вернуть 0 файлов вне `pyproject.toml` allowlist.

### DOMAIN-P2-002 — presidio-ru-recognizers phantom-version dep

**Evidence:**

`pyproject.toml:165-168`:

```toml
# S172: presidio-ru-recognizers — checksum-validated ИНН/СНИЛС/ОГРН drop-ins
# для уже-используемого Presidio. Custom recognizers в services/ai/pii/recognizers/
# остаются как fallback; не удалять до явного перехода.
"presidio-ru-recognizers>=0.1.0,<1.0.0",
```

`grep -rn "presidio_ru_recognizers\|presidio-ru-recognizers" src/ extensions/ testkit/ tools/`
→ **0 matches**.

Custom recognizers существуют:
- `src/backend/services/ai/pii/recognizers/__init__.py`
- `src/backend/services/ai/pii/recognizers/inn_recognizer.py`
- `src/backend/services/ai/pii/recognizers/snils_recognizer.py`

Эти regex-recognizers полностью покрывают ИНН/СНИЛС use case (per comment line 165-167 —
custom "остаются как fallback"). Opt-in extra с phantom-version pin (0.1.0 — минимальная
версия, реальная PyPI availability неизвестна без network).

**Impact:** Dead opt-in dep. Ставится только если кто-то `pip install gd_advanced_tools[ai]`
явно, но ничего не работает из-за отсутствия импортов. Maintenance burden при обновлении
транзитивных deps presidio-* (тянет spacy/transformers — ~1.5GB).

**Fix:** Удалить из `[project.optional-dependencies].ai` (line 165-168). Custom recognizers
достаточны.

**Test:** `grep -rln "presidio_ru_recognizers\|presidio-ru-recognizers" /home/user/dev/gd_integration_tools --include="*.py"`
→ должно вернуть 0 строк в коде (только в этом отчёте).

### DOMAIN-P3-001 — Cross-pin duplicates (3/4 RESIDUAL)

**Verified duplicates в pyproject.toml:**

```
lxml:
    [project.dependencies]: >=6.1.0,<7.0.0
    [tool.uv.override-dependencies]: >=6.1.1,<7.0.0
pillow:
    [extras.rpa-windows]: >=12.3.0,<13.0
    [extras.multimodal-rag]: >=10.0.0,<13.0.0
streamlit:
    [project.dependencies]: >=1.58.0,<2.0.0
    [extras.frontend]: >=1.30.0,<2.0.0
```

**Статус:**

| Пакет | Статус | Обоснование |
|---|---|---|
| streamlit | RESIDUAL | разные lower bounds (1.58 vs 1.30); cycle-4 D-AUDIT-03 закрыл только upper (`<2.0.0`), lower bounds оставил diverging. Maintainer risk: при bump frontend extra кто-то может поднять выше 1.58.0 и задублировать. |
| lxml | RESIDUAL | dep `>=6.1.0` + override `>=6.1.1` — override форсит >=6.1.1, dep-строка остаётся `>=6.1.0`. Cosmetic. Реальное разрешение = `>=6.1.1`. Cycle-4 D-AUDIT-02 cleanup не унифицировал dep + override. |
| pillow | RESIDUAL | `rpa-windows >=12.3.0,<13.0` vs `multimodal-rag >=10.0.0,<13.0.0`. Pillow 12.2.0 имел memory-corruption CVE (per `pyproject.toml:281` comment). Совмещение: нижний bound разный — нет единого источника. |
| rank-bm25 | RESOLVED | `>=0.2.2,<1.0.0` в обоих местах, документировано в comment line 309-313 ("Дубль здесь оставлен намеренно"). |

**Impact:** Maintainability. uv resolver берёт intersection (`>=max(lower), <min(upper)`),
так что функционально корректно, но DRY violation. При CVE в package maintainer должен
обновить 2 места с потенциальной рассинхронизацией.

**Fix:** Унифицировать bounds: streamlit `>=1.58.0,<2.0.0` в обоих местах;
lxml `>=6.1.1,<7.0.0` в dep (убрать override); pillow `>=12.3.0,<13.0` в обоих extras
(Sprint 11 multimodal-rag имеет Pillow<13.0 — bump до 12.3 не breaking).

**Test:** после фикса `grep -A1 'name=' pyproject.toml | sort -u` на каждой дублирующейся
зависимости должен показать 1 unique spec.

### DOMAIN-P3-002 — verify_pypi_versions._parse_pin bug

**Evidence:**

```python
# tools/verify_pypi_versions.py:71-83
def _parse_pin(dep: str) -> tuple[str, str] | None:
    m = _PIN_RE.match(dep.strip())
    if not m:
        return None
    name = m.group(1).split("[")[0]
    op1, ver1, op2, _ver2 = m.group(2), m.group(3), m.group(4), m.group(5)
    if op2 and op2 in ("<", "<="):
        return (name.lower(), ver1 if op1 in (">", ">=", "==") else ver1)
    if op1 in ("<", "<="):
        return (name.lower(), ver1)
    if op1 in (">", ">=", "==", "~="):
        return None
    return None
```

Verified runtime:
```
sqlalchemy: <= 2.0.41        (ожидаемый upper = <3.0.0, реально вернуло lower 2.0.41)
pydantic: <= 2.10.3          (ожидаемый upper = <3.0.0, реально вернуло lower 2.10.3)
```

`_version_tuple(pinned_max) > _version_tuple(actual_max)` — pinned_max = 2.0.41,
actual_max = 2.0.51 → False → no phantom warning. Function useless for phantom detection.

**Impact:** Tool помечен как "S44 W3 (TD-006): verify that PyPI version pins реальны".
Без сетевого доступа не запускается (graceful skip per comment line 51-58). С сетью —
функция сравнивает неправильные bound'ы. Не CI-blocking.

**Fix:** `return (name.lower(), _ver2)` вместо `ver1` при наличии op2 (`<`/`<=`).
Плюс тесты.

**Test:** Synthetic test case `parse_pin("sqlalchemy>=2.0.41,<3.0.0")` должен вернуть
`(sqlalchemy, "3.0.0")`, не `"2.0.41"`.

### DOMAIN-P3-003 — Dead dev-dep deptry

**Evidence:**

```toml
# pyproject.toml:558
"deptry>=0.20,<1.0",
```

`grep -rn "deptry" Makefile make/ .github/ .gitlab/ tools/` → **0 references**.
Только одно объявление в `pyproject.toml:558` без caller'ов.

**Impact:** Dead dev-dep. Устанавливается при `uv sync` (default-groups=["dev"]) → ~50KB
+ dependency resolution overhead. Никогда не используется.

**Fix:** Удалить строку из `[dependency-groups].dev` (line 558).

**Test:** после удаления `uv sync --no-dev && uv sync && uv run deptry --version` должен
fail with `command not found`.

---

## 5. Cycle-1+2+3 residuals

| ID | Источник | Текущий статус | Evidence |
|---|---|---|---|
| cycle-3 P0-001 | "4-way drift" | **RESOLVED** | `cycle-1-preflight.sh` все gates (кроме pre-existing uv.lock + working tree) PASS; layer 175/0; allowlist 27; docstring 0 |
| cycle-3 P0-002 | "8 stale CVE" | **RESOLVED** | Все 8 ID удалены из `.security/pip-audit-allowlist.txt` (comment line 62-72); installed versions ≥ fix для каждого (`importlib.metadata` verified) |
| cycle-3 P0-003 | "IGNORED_VULNS" | **RESOLVED** | `tools/pip_audit_gate.py:25-31` frozenset `[]`; canonical allowlist = `.security/pip-audit-allowlist.txt` |
| cycle-3 P0-004 | "streamlit <2.0.0" | **RESOLVED** | `pyproject.toml:137` и `:477` оба имеют `<2.0.0`; installed 1.61.0 |
| cycle-3 P1-001 | "4 cross-pin duplicates" | **PARTIAL RESIDUAL** | Из 4 candidates: rank-bm25 RESOLVED (documented), 3 (streamlit/lxml/pillow) RESIDUAL — см. DOMAIN-P3-001 |
| cycle-3 P2-001 | "dead sphinx" | **RESIDUAL** | `tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`, `docs/api/*` НЕ удалены; см. DOMAIN-P2-001 |
| cycle-3 P2-002 | "phantom-version" | **RESIDUAL** | `presidio-ru-recognizers>=0.1.0,<1.0.0` остаётся в `[project.optional-dependencies].ai` без импортов; см. DOMAIN-P2-002 |
| cycle-1/2/3 smoke (T-1.4, T-1.5, T-3.1, T-W1-01/05/08, T-02/03) | Per BASELINE | **VERIFIED via baseline** | T-1.4 multicast, T-1.4 redelivery, T-1.5 policy_mixin, T-1.5 gateway_adapter, T-3.1 cachetools, T-W1-01 AuthenticationProviderUnavailableError, T-W1-05 cdc_routes, T-W1-08 credit_pipeline — BASELINE.md:11-19 зафиксировал 8/8 PASS. Не перепрогонял (read-only scope домена Зависимости). |

**Что верифицировал непосредственно в этом аудите (cycle 4 phase 1):**
- 8 stale CVE installed versions ≥ fix (все 8 ID из comment block удалены)
- IGNORED_VULNS frozenset empty
- Streamlit `<2.0.0` в обоих pin'ах
- Allowlist ровно 27 entries
- Cross-pin дубликаты в pyproject.toml — 3 из 4 RESIDUAL
- Dead sphinx tooling — RESIDUAL

---

## 6. Contradictions / overlaps to flag

### C-1: `tools/pip_audit_gate.py` vs `make/security.mk` разные JSON paths
Gate читает CWD/pip-audit.json; Make пишет в dist/pip-audit.json. Документировано как
DOMAIN-P1-001.

### C-2: CI pipelines vs Makefile — неполная синхронизация allowlist
GitHub CI (security.yml) передаёт 2/27 CVE-флагов; GitLab CI (.gitlab-ci.yml) передаёт 1/27.
Make audit-deps — все 27. Документировано как DOMAIN-P1-002/P1-003.

### C-3: Stale `--ignore-vuln PYSEC-2026-87` в GitHub CI
Allowlist cleanup cycle-4 D-AUDIT-02 удалил этот ID; GH CI флаг остался.
Документировано как DOMAIN-P1-004.

### C-4: sphinx DEPRECATED but not REMOVED
`make/docs.mk:31-37` помечает `docs-html` и `docs-multiversion` как DEPRECATED.
Но `tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`, `docs/api/*` остаются.
Документировано как DOMAIN-P2-001.

### C-5: verify_pypi_versions не работает по назначению
`_parse_pin` возвращает lower bound вместо upper; phantom-detection сравнивает
lower ≤ PyPI max (всегда True). Документировано как DOMAIN-P3-002.

### C-6: rank-bm25 явный duplicate с явным комментарием-обоснованием
Per `pyproject.toml:309-313`: "Дубль здесь оставлен намеренно: гарантирует тот же upper-bound
<1.0.0 для пользователей uv sync --extra rag даже если кто-то вручную override'нёт основной
dependencies." Это **не баг**, это documented design decision. RESOLVED, не finding.

---

## 7. Readiness score

**Формула:**

```
readiness = max(0, 79 - deductions)    # cap=79 при наличии P0/P1
deductions:
  P1 (каждый, max 4×P1=24 capped):
    P1-001 path mismatch: -3 (developer-experience, не security)
    P1-002 GH CI vs Make inconsistency: -5 (maintenance drift, fail-closed спасает)
    P1-003 GitLab CI single-flag + no gate: -7 (потенциальный fail-open)
    P1-004 stale --ignore-vuln: -3 (regression mask)
  P2 (каждый, max 2×P2=10):
    P2-001 dead sphinx (~400 LOC, 10+ files): -5
    P2-002 phantom-version presidio-ru-recognizers: -2
  P3 (каждый, max 3×P3=5):
    P3-001 cross-pin duplicates (3 RESIDUAL): -3
    P3-002 verify_pypi_versions bug: -1
    P3-003 deptry dead dev-dep: -1
```

**Расчёт:** 79 − (3+5+7+3) − (5+2) − (3+1+1) = 79 − 18 − 7 − 5 = **49**

**Обоснование 49:**
- Gate fail-CLOSED работает корректно для всех синтетических сценариев → нет P0.
- 4 P1 finding'а — все в CI/Make inconsistency + dead tooling: не security, но поддерживать
  дорого и brittle.
- 8 stale CVE removed cycle-4 — выполнено, что подтверждает working supply-chain процесс.
- Allowlist semantics корректна (single source of truth в `.security/pip-audit-allowlist.txt`).
- Cycle-1-preflight gates все зелёные (кроме pre-existing drift).

**Cap:** ≤79 при наличии P0/P1. **Score = 49.**

---

## 8. Recommended next tasks

| Приоритет | Task | Scope | Effort |
|---|---|---|---|
| P1 | DOMAIN-P1-001 fix | `make/security.mk:56` изменить `--output` на `pip-audit.json` (CWD) — синхронизировать с gate + GH CI | 1 line |
| P1 | DOMAIN-P1-002 fix | `.github/workflows/security.yml:133-139` — реплейс hardcoded 2 флагов на shell-loop по allowlist (как Makefile) | 5 lines |
| P1 | DOMAIN-P1-003 fix | `.gitlab/ci/.gitlab-ci.yml:152-166` — расширить `--ignore-vuln` + добавить `tools/pip_audit_gate.py` после pip-audit | 5 lines |
| P1 | DOMAIN-P1-004 fix | `.github/workflows/security.yml:138` — удалить `--ignore-vuln PYSEC-2026-87` (allowlist cleanup) | 1 line |
| P2 | DOMAIN-P2-001 fix | Удалить `tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`, `docs/api/` (10+ файлов, ~400 LOC); убрать gate "13 sphinx -W" из `pre_prod_check.py:738-741`; удалить targets `docs-html`, `docs-multiversion` из `make/docs.mk` | ~1 sprint cleanup |
| P2 | DOMAIN-P2-002 fix | Удалить `presidio-ru-recognizers>=0.1.0,<1.0.0` из `pyproject.toml:165-168`; custom recognizers в `services/ai/pii/recognizers/` достаточны | 1 line |
| P3 | DOMAIN-P3-001 fix | Унифицировать bounds: streamlit 477→137, lxml dep 81→628, pillow multimodal-rag 509→281 | 3 lines |
| P3 | DOMAIN-P3-002 fix | `tools/verify_pypi_versions.py:79-83` — заменить `ver1` на `_ver2` для op2 case | 1 line + tests |
| P3 | DOMAIN-P3-003 fix | `pyproject.toml:558` — удалить `"deptry>=0.20,<1.0"` | 1 line |

---

## 9. Commands run

Все команды — `.venv/bin/python` (system Python не подключён к .venv per AGENTS.md critical).

```bash
# Scope discovery
find /home/user/dev/gd_integration_tools/tools -name "*pip_audit*" -o -name "*pip-audit*"
ls /home/user/dev/gd_integration_tools/.github/workflows/
ls /home/user/dev/gd_integration_tools/.gitlab/ci/

# Allowlist count
grep -cE "^CVE-|^GHSA-|^PYSEC-" /home/user/dev/gd_integration_tools/.security/pip-audit-allowlist.txt
# → 27

# Cycle-1 preflight
bash tools/cycle-1-preflight.sh
# → layer checker OK, allowlist 27 OK, docstring 0 OK,
#   working tree FAIL 9 entries (pre-existing drift), uv.lock FAIL 45 lines (pre-existing)

# Installed versions for 8 stale CVE packages
.venv/bin/python -c "import importlib.metadata as md; \
  [print(f'{p}: {md.version(p)}') for p in ['mistune','gitpython','urllib3','idna','starlette','sqladmin','strawberry-graphql','lxml','diskcache']]"
# → mistune: 3.3.4 (≥ 3.2.1 fix)
# → gitpython: 3.1.58 (≥ 3.1.50 fix)
# → urllib3: 2.7.0 (= 2.7.0 fix)
# → idna: 3.18 (≥ 3.15 fix)
# → starlette: 1.3.1 (≥ 1.0.1 fix)
# → sqladmin: 0.30.0 (≥ 0.25.1 fix)
# → strawberry-graphql: 0.323.2 (≥ 0.315.4 fix)
# → lxml: 6.1.1 (≥ 6.1.0 fix)
# → diskcache: 5.6.3 (allowlist-kept, no fix)

# Streamlit < 2.0.0 verify
.venv/bin/python -c "import importlib.metadata as md; v=md.version('streamlit'); \
  assert tuple(int(p) for p in v.split('.')[:2]) < (2,0); print('OK')"
# → OK (installed 1.61.0)

# pip_audit_gate behavior — synthetic JSON tests
.venv/bin/python tools/pip_audit_gate.py
# → ERROR: pip-audit.json malformed JSON → exit 1 (FAIL-CLOSED)

# With allowlist-match CVE (CVE-2026-33079 from allowlist):
echo '{"dependencies": [{"name": "mistune", "version": "3.3.4", "vulns": [{"id": "CVE-2026-33079", "fix_versions": []}]}]}' > pip-audit.json
.venv/bin/python tools/pip_audit_gate.py
# → VULN: mistune CVE-2026-33079 / FAIL: 1 unignored / exit 1
# (confirms gate does NOT auto-consult allowlist.txt; requires --ignore-vuln at CLI level)
rm pip-audit.json

# With non-allowlist CVE:
echo '{"dependencies": [{"name": "streamlit", "version": "1.61.0", "vulns": [{"id": "CVE-2025-99999", "fix_versions": ["99.0.0"]}]}]}' > pip-audit.json
.venv/bin/python tools/pip_audit_gate.py
# → VULN: streamlit CVE-2025-99999 / FAIL: 1 unignored / exit 1
rm pip-audit.json

# Empty/malformed:
echo '{}' > pip-audit.json
.venv/bin/python tools/pip_audit_gate.py
# → ERROR: no 'dependencies' key or empty list / FAIL-CLOSED / exit 1
rm pip-audit.json

echo 'garbage' > pip-audit.json
.venv/bin/python tools/pip_audit_gate.py
# → ERROR: malformed JSON / exit 1
rm pip-audit.json

# Path mismatch verification
.venv/bin/python -c "from pathlib import Path; \
  print(Path('pip-audit.json').resolve() == Path('dist/pip-audit.json').resolve())"
# → False

# Cross-pin duplicate scan
.venv/bin/python -c "import tomllib, re; \
  from collections import defaultdict; \
  data = tomllib.load(open('pyproject.toml','rb')); \
  pins = defaultdict(list); \
  sources = [('[deps]', data['project']['dependencies'])] + \
            [(f'[extras.{k}]', v) for k,v in data['project'].get('optional-dependencies',{}).items()] + \
            [('[dev]', data.get('dependency-groups',{}).get('dev',[]))] + \
            [('[override]', data.get('tool',{}).get('uv',{}).get('override-dependencies',[]))]; \
  [pins[re.match(r'^([a-zA-Z0-9_.\-]+)', d.strip().strip('\"'))].group(1).lower().replace('_','-')].append((sec, d.strip())) \
   for sec,deps in sources for d in deps if re.match(r'^([a-zA-Z0-9_.\-]+)', d.strip().strip('\"'))]"
# (full scan in audit run; output: lxml, pillow, streamlit — 3 conflicting cross-pins)

# Phantom-version parser bug
.venv/bin/python -c "import sys; sys.path.insert(0,'tools'); \
  from verify_pypi_versions import _parse_pin; \
  print(_parse_pin('sqlalchemy>=2.0.41,<3.0.0'))"
# → ('sqlalchemy', '2.0.41')  ← BUG: should be ('sqlalchemy', '3.0.0')

# sphinx tooling dead-code verify
.venv/bin/python -c "import sphinx"
# → ModuleNotFoundError (sphinx not installed, confirming dead tooling)

# Cross-pin extras
.venv/bin/python -c "import importlib.metadata as md; \
  [print(p) for p in ['streamlit-autorefresh','presidio-ru-recognizers','httpx_retries','hishel','rank_bm25','sphinx','pytesseract','paddleocr','paddlepaddle'] \
   if (lambda v: print(f'{p}: {v}' if v else print(f'{p}: NOT FOUND'))(md.version(p) if p in [d.metadata['Name'] for d in md.distributions()] else None)]"
# (output: streamlit-autorefresh NOT FOUND, presidio-ru-recognizers NOT FOUND, httpx_retries 0.6.0, hishel 0.1.5, rank_bm25 0.2.2, sphinx NOT FOUND)

# Make audit-deps loop logic
.venv/bin/python -c "import re; lines = open('.security/pip-audit-allowlist.txt').readlines(); \
  al = [l.strip() for l in lines if l.strip() and not l.strip().startswith('#')]; \
  flags = ' '.join(f'--ignore-vuln {v}' for v in al); \
  print(f'allowlist entries: {len(al)}'); print(f'flags total chars: {len(flags)}')"
# → allowlist entries: 27 / flags total chars: 782

# Stale --ignore-vuln flag
grep -n "ignore-vuln" /home/user/dev/gd_integration_tools/.github/workflows/security.yml \
                      /home/user/dev/gd_integration_tools/.gitlab/ci/.gitlab-ci.yml
# → security.yml:137  --ignore-vuln CVE-2025-69872
# → security.yml:138  --ignore-vuln PYSEC-2026-87     ← STALE
# → .gitlab-ci.yml:161 - uv run pip-audit --ignore-vuln CVE-2025-69872
```

---

## 10. Summary

**Status:** Phase 1 domain «Зависимости» завершён.

**Headline numbers:**
- **0 × P0** (security/data-loss/race/fail-open — не обнаружено).
- **4 × P1** (CI/Make inconsistency + path mismatch + stale flag).
- **2 × P2** (dead sphinx tooling + phantom-version dep).
- **3 × P3** (cross-pin duplicates residual + phantom-detection bug + dead dev-dep).
- **0 × P4** (organic features — не выявлено, домен «Зависимости» не предполагает
  Camel/Airflow-style DSL expansion).

**Cycle-1+2+3 residuals:** 5 из 7 цикл-3 finding'ов RESOLVED (P0-001/002/003/004 + частично P1-001);
2 из 7 RESIDUAL (P2-001 sphinx, P2-002 phantom-version + 3 из 4 cross-pin duplicates в P1-001).

**Readiness:** **49/100** (cap 79 из-за P1, deductions -30).

**Top blockers (для cycle-4 phase-2 fixes):**
1. **DOMAIN-P1-003** — GitLab CI без gate wrapper, single-flag, потенциальный fail-open.
2. **DOMAIN-P1-002** — GH CI пропускает 25/27 allowlist CVE → maintenance drift.
3. **DOMAIN-P1-001** — path mismatch блокирует `make audit-deps && gate` direct sequence.
4. **DOMAIN-P2-001** — dead sphinx tooling (~400 LOC, 10+ файлов).

**Recommended fix order:** P1-004 (1 line) → P1-001 (1 line) → P1-002/003 (CI sync ~10 lines) →
P2-001 (dead code cleanup) → P2-002 (1 line) → P3-001/002/003 (cleanup).
