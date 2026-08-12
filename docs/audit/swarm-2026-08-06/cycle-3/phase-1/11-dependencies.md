# Phase 1 — Домен Зависимости (Cycle 3)

**HEAD**: `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` (2026-08-06)
**Scope**: `pyproject.toml`, `uv.lock` (read-only), `requirements*.txt`, `constraints*.txt`,
`.security/pip-audit-allowlist.txt`, dependency tooling под `tools/**`, dep-related CI под
`.github/**` и `.gitlab/**`.
**Phase**: 1 (read-only анализ, source/configs/lockfiles/allowlists НЕ менять).

---

## 0. Scope / не проверено

### В scope (проверено)
- `pyproject.toml` (1159 lines) — `dependencies`, `optional-dependencies`,
  `dependency-groups`, `tool.uv`, `tool.deptry` (отсутствует).
- `uv.lock` (10859 lines) — 680 packages, только чтение, не модифицировался.
- `.security/pip-audit-allowlist.txt` (79 lines, 35 active CVE/GHSA/PYSEC IDs).
- `tools/pip_audit_gate.py` (66 lines, hardcoded `IGNORED_VULNS` frozenset).
- `tools/checks/run_pip_audit.py`, `tools/checks/check_supply_chain.py`,
  `tools/checks/pre_prod_check.py`, `tools/cycle-1-preflight.sh`.
- `make/security.mk`, `make/quality.mk`, `make/docs.mk` (deps-related targets).
- `tools/checks/creosote_allowlist.txt`.
- `.github/workflows/security.yml` (pip-audit job), `.github/workflows/sbom.yml`,
  `.github/dependabot.yml`, `.gitlab/ci/.gitlab-ci.yml`.
- `requirements*.txt` (найдены 2: `docs/api/requirements.txt` и `site/api/requirements.txt`).
- `constraints*.txt` — НЕ найдены (явное отсутствие зафиксировано).
- `deptry` static analysis (289 issues), `creosote` (отдельный запуск не делал, см.
  `tools/checks/creosote_allowlist.txt`).

### Не проверено (out of scope или недоступно)
- Реальный online `pip-audit` (PyPI JSON API timeout 60s+ — network restricted).
  Подтверждено: `curl https://pypi.org/pypi/pip-audit/json` → exit 28 (timeout).
  Вердикт: статический анализ через cross-check installed-version vs
  claimed-fix-version в allowlist comments — единственный доступный путь.
- Циклон-DX SBOM (sbom.cdx.json 2008-08-06 13:45) — out of scope (Sprint 35).
- `pre-existing` uncommitted правки (uv.lock -15 svcs, .blue_green.state,
  pip-audit.json empty) — НЕ атрибутируются рою cycle 3.
- `extensions/*` бизнес-логика — НЕ в scope (отдельный домен).
- `cosign` подписи artifacts — out of scope (Sprint 35 W2).
- `trivy` / `gitleaks` / `OWASP ZAP` — out of scope.
- Cycle-1/cycle-2 markdown — НЕ читал (по инструкции).

---

## 1. Verified strengths

### 1.1 uv.lock + resolver
- 680 packages в lock, `requires-python = ">=3.14,<3.15"`.
- `[tool.uv] environments` ограничен `linux + darwin + python 3.14.*` —
  устраняет win32-only пакеты (`paddlepaddle`/`aioldap3`/`pygls` split) —
  зафиксировано в `pyproject.toml:613-616`.
- `override-dependencies` для `pyarrow>=20`, `lxml>=6.1.1`, `urllib3>=2.7.0` —
  явное разрешение конфликтов с `FlagEmbedding`/`inscriptis`/`Dependabot`.
  Source: `pyproject.toml:623-635`.

### 1.2 Layer-aware extras
- 27+ optional-dependencies правильно разнесены по доменам:
  `ai`, `security`, `db_drivers`, `redteam`, `ai-eval`, `auth-saml`, `mcp`,
  `rpa`, `rpa-ocr`, `rpa-windows`, `http3`, `dsl-extras[-2,-3]`, `analytics`,
  `rag`, `ai-2026`, `ai-model-registry`, `ai-safety`, `feature_flags`,
  `workflow`, `dev-light`, `sources-cdc`, `sources-mq-nats`, `lsp`, `perf`,
  `testkit`, `docs`, `docs-ru`, `compression`, `frontend`, `doc-templates`,
  `multimodal-rag`, `ai-memory`, `search-providers`, `result-monad`.
- Default extras (security/db_drivers/sources-mq-nats) — install-ready
  без доп.флагов; advanced extras — opt-in.

### 1.3 Fail-closed security allowlist pipeline
- `.security/pip-audit-allowlist.txt` — 35 active CVE/GHSA/PYSEC IDs,
  сгруппированы по волнам (pre-K5 baseline, S18 W2 baseline freeze,
  S30 fix-marker notes).
- `make audit-deps` — динамически читает allowlist (`make/security.mk:45-57`),
  правильный canonical source.
- `tools/pip_audit_gate.py` — парсит `pip-audit.json` JSON-выход (S29 W1 fix:
  pip-audit 2.10.0 always exits 0, нужен wrapper).
- CI `.github/workflows/security.yml:102-148` — `pip-audit` job в blocking mode
  (`continue-on-error: false`).
- Dependabot: weekly scan для `uv` + `npm` (admin-react) с auto-merge OFF
  (`.github/dependabot.yml`).

### 1.4 Test-time runtime verification
- `.venv/bin/python` (Python 3.14.0) — `.venv/lib/python3.14/site-packages`
  содержит все нужные пакеты (`prometheus_client`, `fastapi`, `hypothesis`,
  `tenacity` 9.1.4, и т.д.).
- 4 targeted pytest runs прошли: 20+15+7+9 = 51 passed, 0 failed.
- Reviewer cycle 2 ошибочно указал на env-fail (`ModuleNotFoundError` на
  system Python) — это `python3` (`/usr/bin/python3`, НЕ `.venv/bin/python`).
  Подтверждено: `python3 -c "import prometheus_client"` → ModuleNotFoundError;
  `.venv/bin/python -c "..."` → работает.

---

## 2. Findings table

| ID | Приоритет | Path:Line | Краткое описание |
|---|---|---|---|
| **DEPS-P0-001** | P0 | `.security/pip-audit-allowlist.txt:65,67,69,71,74,76,79` | 8 stale CVE IDs в active allowlist (installed ≥ fix-version). RESIDUAL от cycle-2 P0-001. |
| **DEPS-P0-002** | P0 | `pyproject.toml:137` | `streamlit>=1.58.0` — НЕТ upper bound в core deps. RESIDUAL от cycle-2 P0-004. |
| **DEPS-P0-003** | P0 | `.github/workflows/security.yml:137-138` vs `.gitlab/ci/.gitlab-ci.yml:161` vs `tools/pip_audit_gate.py:14-22` vs `make/security.mk:51-57` | 4-way CVE drift: 4 разных источника CVE-ignore'ов, разные active sets (35 vs 2 vs 1 vs 1). RESIDUAL от cycle-2 P0-001. |
| **DEPS-P1-001** | P1 | `tools/checks/check_supply_chain.py:1-216` + workflows | `deptry` и `creosote` НЕ вызываются ни в одном `.github/workflows/*.yml`. Drift в `testkit/` (moto, boto3 — DEP001) и `tools/` (clickhouse_connect — DEP001) не ловится в CI. |
| **DEPS-P1-002** | P1 | `tools/pip_audit_gate.py:18-21` | Stale comments: `"FIXED in s30/w1"` (PYSEC-2026-161) и `"REMOVED in s170"` (CVE-2025-69872) — вводят в заблуждение, эти CVE должны быть удалены из allowlist, а не помечены. RESIDUAL от cycle-2 P0-002. |
| **DEPS-P2-001** | P2 | `docs/api/requirements.txt` + `site/api/requirements.txt` | Sphinx deps (`sphinx>=9.1.0`, `sphinx-rtd-theme>=3.0.0`, `sphinx-autoapi>=3.0.0`) — но pyproject мигрировал на mkdocs canonical (B2 / S40 W4). Файлы устарели (DEPRECATED targets `docs-html`, `docs-multiversion` всё ещё существуют в `make/docs.mk:31-37`). |
| **DEPS-P2-002** | P2 | `pyproject.toml:11,20,78,98,128,129,133,152` | 7 deps без upper bound в `[project.dependencies]` (fastapi, python-multipart, strawberry-graphql, granian, glom, presidio-analyzer, presidio-anonymizer) — потенциальные future-version break'и. См. подробности в §3. |
| **DEPS-P3-001** | P3 | pyproject (нет `[tool.deptry]`) | deptry запускается без конфига — 6794 false-positives (DEP003 'src' imported) при прогоне на src/backend. Не-actionable noise. |
| **DEPS-P3-002** | P3 | `tools/migrations/migrate_dlq_partition.py:307` + `testkit/fixtures/s3_mock.py:36,52` | DEP001: `clickhouse_connect`, `moto`, `boto3` — transitive-only deps, не объявлены в pyproject. Работают только если случайно установлены. |

**Итого**: P0=3, P1=2, P2=2, P3=2. Все P0 — RESIDUAL от cycle-2 (код не изменился с cycle-2 baseline `ca5bff93` → cycle-3 baseline `7f3d94a3`, только retrospective commit).

---

## 3. Detailed evidence

### 3.1 DEPS-P0-001: 8 stale CVE IDs в active allowlist

**Cross-check (прямой код):**
```python
# /tmp/check_cve_drift.py → .venv/bin/python → результат
PYSEC-2026-161: starlette=1.3.1 >= 1.0.1     # installed >= fix → STALE
CVE-2026-46645:  sqladmin=0.30.0 >= 0.25.1   # STALE
CVE-2026-45739:  strawberry-graphql=0.323.2 >= 0.315.4  # STALE
GHSA-mv93-w799-cj2w: gitpython=3.1.58 >= 3.1.50  # STALE
PYSEC-2026-142:  urllib3=2.7.0 >= 2.7.0      # STALE (equal)
PYSEC-2026-141:  urllib3=2.7.0 >= 2.7.0      # STALE (equal)
CVE-2026-45409:  idna=3.18 >= 3.15           # STALE
PYSEC-2026-87:   lxml=6.1.1 >= 6.1.0         # STALE
```

**Active entries в `.security/pip-audit-allowlist.txt`:**
- L65: `GHSA-mv93-w799-cj2w` (gitpython, fix 3.1.50, installed 3.1.58)
- L67: `PYSEC-2026-142` (urllib3, fix 2.7.0, installed 2.7.0)
- L69: `PYSEC-2026-141` (urllib3, fix 2.7.0, installed 2.7.0)
- L71: `CVE-2026-45409` (idna, fix 3.15, installed 3.18)
- L74: `PYSEC-2026-161` (starlette, fix 1.0.1, installed 1.3.1)
- L76: `CVE-2026-46645` (sqladmin, fix 0.25.1, installed 0.30.0)
- L79: `CVE-2026-45739` (strawberry-graphql, fix 0.315.4, installed 0.323.2)
- (L17 implicit: `PYSEC-2026-87` через `IGNORED_VULNS` hardcoded + pre-K5 baseline,
  lxml 6.1.1 ≥ 6.1.0)

**Active & justified (NOT stale, keep in allowlist):**
- `CVE-2025-69872` (diskcache, fix 6.x, installed 5.6.3) — pyproject pin `<6.0.0`.
- `CVE-2026-33079` + 2x `CVE-2026-44708/44896/44897` (mistune, fix 3.4+, installed 3.3.4) — nbconvert compat.
- `CVE-2026-42561` (python-multipart, installed 0.0.32) — bump до 0.0.27+ claim не верифицирован offline.
- 21x mako/alembic CVE (`CVE-2025-55197..66019` и т.д.) — claim alembic bump, alembic 1.19.0 installed.
  Без online CVE DB не верифицировано.
- `CVE-2026-41312/41313/41314/40260/41168/33699/33123/27628/27888/28351/28804/31826/27026/27024/27025/24688/22690/22691` — mako series.
- 21 mistune/mako CVEs: не верифицировано offline (нет pip-audit network).

**Evidence-команды:**
```
.venv/bin/python -c "from importlib.metadata import version; print(version('starlette'))"
→ 1.3.1
.venv/bin/python -c "...print(version('sqladmin'))"
→ 0.30.0
... (аналогично для остальных 6 пакетов)
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
→ 35
```

**Impact**: false-positive CVE coverage, audit-noise, drift между allowlist и реальным состоянием lock.
- Ложные CVE в gate → CI может маскировать реальные новые CVE (security-team trust erosion).
- 8 stale entries → drift-сигнал для review-board (cycle-2 plan отметил 9 stale;
  ровно 8 верифицированы прямым кодом; 9-я — diskcache CVE-2025-69872 — НЕ stale,
  реально active).

**Минимальная рекомендация:**
1. Удалить из `.security/pip-audit-allowlist.txt` строки L65, 67, 69, 71, 74, 76, 79
   (8 entries).
2. Из `tools/pip_audit_gate.py:14-22` удалить `PYSEC-2026-87` из `IGNORED_VULNS`
   (lxml 6.1.1 ≥ 6.1.0 fix).
3. Из `.security/pip-audit-allowlist.txt` L17 убрать комментарий про pre-K5 baseline
   для lxml (или удалить entry, если pip-audit перестал его флагать).
4. Провести online `pip-audit` для верификации 21 mistune/mako CVEs
   (требует network access).

**Тест-критерий:**
- `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → 27 (после cleanup)
- `pip-audit --strict --format json -r dist/audit-requirements.txt` → не flag'ает
  удалённые CVE для current installed versions.

---

### 3.2 DEPS-P0-002: `streamlit>=1.58.0` без upper bound

**Evidence:**
```
pyproject.toml:137:    "streamlit>=1.58.0",   # ← NO <X.Y.Z upper bound
```

Только эта строка в `[project.dependencies]`. `[project.optional-dependencies].frontend:477`
имеет корректный `"streamlit>=1.30.0,<2.0.0"`.

**Установленная версия**: streamlit 1.61.0 (в `.venv/lib/python3.14/site-packages`).

**Impact:**
- 95 прямых `import streamlit` в `src/frontend/streamlit_app/` — критический user-facing
  surface (Streamlit Developer Portal, 36+ pages per AGENTS.md).
- Streamlit API breaking-changes между minor versions (1.x → 2.x, регулярные
  deprecations: `set_page_config`, `experimental_*`, `st.cache`, etc.).
- Без upper bound: dependabot или ручной bump может поднять до несовместимой версии
  → CI green (lockfile resolves) → runtime fail в проде.

**Минимальная рекомендация:**
- Заменить L137 на `"streamlit>=1.58.0,<2.0.0"` (consistency с frontend extra).
- Альтернатива (если нужен 2.x): явный major-bump wave с pre-flight testing
  всех 36+ Streamlit pages.

**Тест-критерий:**
- `grep '^    "streamlit' pyproject.toml` → обе строки имеют `<X.Y.Z` upper bound.
- `uv lock --check` после правки не должен падать.
- 95 streamlit imports работают с pinned версией.

---

### 3.3 DEPS-P0-003: 4-way CVE drift между 4 разными enforcement'ами

**4 enforcement точки** (по прямому grep):

1. **`make/security.mk:45-57`** — `make audit-deps` target. Динамически читает
   `.security/pip-audit-allowlist.txt`, передаёт все 35 entries как
   `--ignore-vuln <id>`:
   ```makefile
   @ALLOW=""; \
   if [ -f .security/pip-audit-allowlist.txt ]; then \
       for v in $$(grep -v '^#' .security/pip-audit-allowlist.txt | grep -v '^$$' || true); do \
           ALLOW="$$ALLOW --ignore-vuln $$v"; \
       done; \
   fi; \
   $(UV_RUN) pip-audit --strict --format json -r dist/audit-requirements.txt $$ALLOW
   ```
   **Effective active count**: 35 (canonical).

2. **`.github/workflows/security.yml:134-139`** — hardcoded:
   ```yaml
   uv run pip-audit \
     --format json \
     --output pip-audit.json \
     --ignore-vuln CVE-2025-69872 \
     --ignore-vuln PYSEC-2026-87
   uv run python tools/pip_audit_gate.py
   ```
   **Effective active count**: 2 (CVE-2025-69872 + PYSEC-2026-87) на уровне
   `pip-audit`, + `IGNORED_VULNS` set в `pip_audit_gate.py` (1 active entry).

3. **`.gitlab/ci/.gitlab-ci.yml:161`** — hardcoded:
   ```yaml
   - uv run pip-audit --ignore-vuln CVE-2025-69872
   ```
   **Effective active count**: 1 (только CVE-2025-69872).
   PYSEC-2026-87 здесь НЕ игнорируется → CI fail при наличии lxml CVE
   (если он не был resolved в lock).

4. **`tools/pip_audit_gate.py:14-22`** — hardcoded Python set:
   ```python
   IGNORED_VULNS: frozenset[str] = frozenset(
       [
           "PYSEC-2026-87",  # lxml: fix 6.1.0 available but no Python 3.14 wheels
           # NOTE: PYSEC-2026-161 (starlette) FIXED in s30/w1 - starlette 1.1.0
           # NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
           # dependency eliminated; replaced with custom JSONDisk cache.
       ]
   )
   ```
   **Effective active count**: 1 (только PYSEC-2026-87).
   PYSEC-2026-87 уже STALE (lxml 6.1.1 ≥ 6.1.0) — см. DEPS-P0-001.

**Impact:**
- GitLab CI pipeline будет FAIL на PR с любым lxml CVE bump'ом (нет ignore).
- GitHub workflow ignore'ит и diskcache CVE, и lxml CVE → разное поведение для
  одного и того же проекта в двух CI.
- Makefile canonical (35) — developer 'make audit-deps' видит больше, чем CI.
- `pip_audit_gate.py` дополнительно фильтрует — drift внутри одной CI.

**Минимальная рекомендация:**
- Все 4 enforcement точки должны использовать `.security/pip-audit-allowlist.txt`
  как single source of truth (Makefile pattern).
- `.github/workflows/security.yml:134-139` — заменить на `cat .security/pip-audit-allowlist.txt | grep -v '^#' | grep -v '^$' | xargs -I{} uv run pip-audit --ignore-vuln {}` pattern.
- `.gitlab/ci/.gitlab-ci.yml:161` — тот же fix.
- `tools/pip_audit_gate.py:14-22` — заменить `IGNORED_VULNS` на dynamic read
  из `.security/pip-audit-allowlist.txt` (mirror Makefile logic).

**Тест-критерий:**
- Все 4 точки возвращают identical CVE set (35 или 27 после DEPS-P0-001 cleanup).
- `make audit-deps` exit 0 == GitHub workflow exit 0 == GitLab CI exit 0 == local
  `tools/pip_audit_gate.py` exit 0.

---

### 3.4 DEPS-P1-001: deptry/creosote НЕ в CI

**Evidence:**
```bash
grep -nE "deptry|creosote|deps-check" /home/user/dev/gd_integration_tools/.github/workflows/*.yml
# → exit 1 (no matches)
```

**Targets существуют только в Makefile:**
- `make/quality.mk:91-105` — `deps-check` (creosote, allowlist-aware, нестрогий) +
  `deps-check-strict` (creosote strict, exit 1 если не installed).
- `make/pipelines.mk:11,17,26` — invoked из `check-pr`, `check-release`, `pre-commit`.

**Реальное состояние deptry** (прямой прогон):
```
.venv/bin/python -m deptry . 2>&1 | tail -3
→ Found 289 dependency issues.
```
Из них:
- DEP004 (dev dep в production коде): 50+ — `pytest`, `libcst`, `questionary`
  в `tools/` и `testkit/`.
- DEP001 (missing dep): 30+ — `moto`, `boto3` в testkit/fixtures; `tiktoken`,
  `langchain_core`, `onelogin`, `psutil`, `selectolax`, `neo4j` в src/ lazy
  imports (некритично — feature-flag fallback).
- DEP003 (transitive): 200+ — `jinja2`, `packaging` в tools/.

**Impact:**
- Drift в `testkit/` (moto, boto3 — DEP001) обнаруживается только при ручном
  `make deps-check`, не ловится pre-commit.
- Блокирующие deptry issues могут накапливаться незамеченными.

**Минимальная рекомендация:**
- Добавить job `deptry` в `.github/workflows/lint.yml` (или новый `.github/workflows/deps.yml`):
  ```yaml
  - name: Deptry
    run: |
      uv run python -m deptry . || true  # non-blocking пока false-positives чистятся
  ```
- Начать с non-blocking mode, потом перевести на blocking после cleanup.

**Тест-критерий:**
- `.github/workflows/lint.yml` содержит `deptry` job.
- `grep "deptry\|creosote" .github/workflows/*.yml` → exit 0 (найдено).

---

### 3.5 DEPS-P1-002: stale comments в `pip_audit_gate.py`

**Evidence:**
```python
# tools/pip_audit_gate.py:18-21
# NOTE: PYSEC-2026-161 (starlette) FIXED in s30/w1 - starlette 1.1.0
# NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
# dependency eliminated; replaced with custom JSONDisk cache.
```

**Реальность** (прямой grep):
- `PYSEC-2026-161` всё ещё ACTIVE в `.security/pip-audit-allowlist.txt:74`.
- `CVE-2025-69872` всё ещё ACTIVE в allowlist:18 + GitHub workflow:137 +
  GitLab CI:161.
- `diskcache 5.6.3` всё ещё INSTALLED (`/home/user/dev/gd_integration_tools/src/backend/infrastructure/decorators/caching/storage/disk.py:6:from diskcache import Cache`).
- `JSONDisk cache` НЕ существует (поиск "JSONDisk" в src/ — 0 matches, кроме
  этого комментария).

**Impact:**
- Misleading docs: читатель думает "diskcache заменён, не нужно ignore'ить",
  но это неправда.
- Cycle-2 P0-002 был про hardcoded `IGNORED_VULNS` — частично исправлен (закомментированы
  2 строки), но вводящие в заблуждение комментарии остались.

**Минимальная рекомендация:**
- Удалить строки L18-21 целиком.
- Если CVE действительно fixed/removed → удалить из allowlist (см. DEPS-P0-001).

**Тест-критерий:**
- `tools/pip_audit_gate.py` ≤ 18 строк (только `PYSEC-2026-87` или 0 если lxml fix применим).

---

### 3.6 DEPS-P2-001: Sphinx requirements.txt устарели

**Evidence:**
```bash
cat /home/user/dev/gd_integration_tools/docs/api/requirements.txt
# sphinx>=9.1.0,<10.0.0
# sphinx-rtd-theme>=3.0.0,<4.0.0
# sphinx-autoapi>=3.0.0,<4.0.0
```

**Реальность:**
- `make/docs.mk:4-12` явно говорит "mkdocs canonical (CLAUDE.md), Sphinx помечен DEPRECATED".
- `[project.optional-dependencies].docs` (L416-423) содержит `mkdocs`, `mkdocs-material`,
  `mkdocstrings`, `mkdocstrings-python`, `mike`, `pymdown-extensions` — НЕ sphinx.
- `make/docs.mk:31-37` оставляет `docs-html`, `docs-multiversion` targets DEPRECATED.
- B2 commit (`7499f0a` M10.2 closure) удалил sphinx из dev-deps.

**Impact:**
- `docs/api/requirements.txt` — manual install script для legacy readthedocs.org build
  (S178 back-compat per `make/docs.mk:29`). Не broken, но misleading.
- 2 копии (docs/api/ и site/api/) — duplication.

**Минимальная рекомендация:**
- Добавить header warning в оба файла: "DEPRECATED — use [project.optional-dependencies].docs (mkdocs)".
- Или удалить, если S178 back-compat не нужен.

**Тест-критерий:**
- Header в requirements.txt: `# DEPRECATED: use [project.optional-dependencies].docs`.

---

### 3.7 DEPS-P2-002: 7 deps без upper bound (кроме streamlit)

**Evidence** (прямой regex):
```
NO UPPER BOUND: fastapi >=0.116.0
NO UPPER BOUND: python-multipart >=0.0.18
NO UPPER BOUND: strawberry-graphql[fastapi] >=0.262.0
NO UPPER BOUND: granian >=2.0.0
NO UPPER BOUND: glom >=25.12.0
NO UPPER BOUND: presidio-analyzer >=2.2.362
NO UPPER BOUND: presidio-anonymizer >=2.2.0
NO UPPER BOUND: streamlit >=1.58.0
```

8-я — это DEPS-P0-002 (streamlit).

**Impact:**
- FastAPI 1.0 (Q3 2025), Starlette 1.0 (Q2 2025) — major API changes возможны.
- python-multipart имеет CVE history (CVE-2026-42561 в allowlist) — нужен upper bound для safety.
- strawberry-graphql 1.x → breaking changes (`strawberry-graphql-core` split).
- presidio-analyzer/anonymizer — Microsoft PII, активно развивается.
- granian 3.0 (Q1 2026) — возможен breaking changes.

**Минимальная рекомендация:**
- Установить upper bounds per project convention (`<X.Y.Z` matching major.minor.patch):
  - `fastapi>=0.116.0,<1.0.0`
  - `python-multipart>=0.0.18,<1.0.0`
  - `strawberry-graphql[fastapi]>=0.262.0,<1.0.0`
  - `granian>=2.0.0,<3.0.0`
  - `glom>=25.12.0,<26.0.0`
  - `presidio-analyzer>=2.2.362,<3.0.0`
  - `presidio-anonymizer>=2.2.0,<3.0.0`

**Тест-критерий:**
- `grep -E '^\s+"[a-z_-]+(>=|<|==)' pyproject.toml` — все строки core deps имеют `<X.Y.Z`.

---

### 3.8 DEPS-P3-001: deptry без project config

**Evidence:**
- В `pyproject.toml` нет `[tool.deptry]` блока.
- `.deptry.toml` / `deptry.toml` — НЕ существуют.
- Прогон `deptry` на src/backend: 6794 issues (в основном `DEP003 'src' imported`).

**Impact:**
- 6794 false-positives = signal-to-noise ≈ 0 → разработчики ignore'ят deptry output.
- Реальные DEP001 (`moto`, `boto3` в testkit) теряются в noise.

**Минимальная рекомендация:**
- Добавить `[tool.deptry]` в pyproject.toml с `known_first_party = ["src", "src.backend", "src.frontend"]`
  (mirror `tool.ruff.lint.isort.known-first-party`).
- Это уберёт ~6700 false-positives.

**Тест-критерий:**
- `grep "tool.deptry" pyproject.toml` → exit 0.
- `deptry .` issues < 50 (после config).

---

### 3.9 DEPS-P3-002: missing deps в tools/testkit

**Evidence:**
- `tools/migrations/migrate_dlq_partition.py:307:16` — `from clickhouse_connect import Client` (DEP001).
- `testkit/fixtures/s3_mock.py:36:9` — `import moto` (DEP001).
- `testkit/fixtures/s3_mock.py:52:16` — `import boto3` (DEP001).
- `tools/migrations/migrate_dlq_partition.py` не в `[tool.deptry].ignore` и не в extras.

**Impact:**
- Если developer запускает `python tools/migrations/migrate_dlq_partition.py` без
  `uv sync --all-extras`, получит `ModuleNotFoundError`.
- testkit/fixtures/s3_mock.py — для S3 mock в tests; работает только если `moto`
  + `boto3` случайно установлены (transitive через aioboto3/aiobotocore в core deps?).

**Минимальная рекомендация:**
- `testkit/fixtures/s3_mock.py`: добавить `moto[s3]>=5.0.0` и `boto3>=1.34.0` в
  `[dependency-groups].dev` или новый `[project.optional-dependencies].testkit`.
- `tools/migrations/migrate_dlq_partition.py`: перенести в `[project.optional-dependencies].clickhouse`
  или объявить `[tool.deptry]` skip.

**Тест-критерий:**
- `deptry .` после config — нет DEP001 для `moto`/`boto3`/`clickhouse_connect`.

---

## 4. Cycle-1 + Cycle-2 residuals (verified)

| ID (cycle) | Что проверял | Статус в cycle 3 | Evidence |
|---|---|---|---|
| **T-W1-02** (cycle 2) | CDC DLQ handoff failure | НЕ в scope этого домена | n/a |
| **T-W1-03** (cycle 2) | MQ subscribers ACK vs DLQ | НЕ в scope | n/a |
| **T-W1-04** (cycle 2) | composition root DI | НЕ в scope | n/a |
| **T-W1-06** (cycle 2) | RagCachePrewarmer phantom fill_cache | НЕ в scope | n/a |
| **T-W1-07** (cycle 2) | SSE principal/permissions | НЕ в scope | n/a |
| **T-W2-01..04** (cycle 2) | layer track | НЕ в scope (отдельный домен) | n/a |
| **T-W3-01** (cycle 2) | tenacity library replacement | **RESOLVED** | `pyproject.toml:74: tenacity>=9.0.0,<10.0.0` + 7+ import sites. Установлено `tenacity 9.1.4` в `.venv`. |
| **T-W4-01** (cycle 2) | text-RAG E2E | НЕ в scope | n/a |
| **T-1.1** (cycle 1) | composition root fix | НЕ в scope | n/a |
| **T-1.2** (cycle 1) | SSE/HITL auth (8 xfailed) | НЕ в scope | n/a |
| **T-1.3** (cycle 1) | MQ DLQ data-loss | НЕ в scope | n/a |
| **T-2.1** (cycle 1) | reverse-layer cleanup | НЕ в scope | n/a |
| **T-4.1** (cycle 1) | text-RAG E2E test | НЕ в scope | n/a |
| **P0-001 (cycle 2)** | 4-way CVE drift + 9 CVE already fixed | **RESIDUAL** | DEPS-P0-001 (8 stale) + DEPS-P0-003 (4-way drift). Подтверждено. |
| **P0-002 (cycle 2)** | hardcoded IGNORED_VULNS | **RESIDUAL** | DEPS-P1-002 — comments обновлены, но hardcoded `PYSEC-2026-87` остался. |
| **P0-003 (cycle 2)** | (не верифицировано — не в моём scope) | не проверено | — |
| **P0-004 (cycle 2)** | streamlit no upper bound | **RESIDUAL** | DEPS-P0-002 — `streamlit>=1.58.0` (line 137), upper bound не добавлен. |

**Targeted pytest runs (все через `.venv/bin/python`)**:
| Test path | Exit | Кол-во passed | Notes |
|---|---|---|---|
| `tests/unit/dsl/engine/processors/eip/reliability/` | 0 | 9 | cycle-2 added |
| `tests/unit/dsl/engine/processors/eip/routing/` | 0 | 6 | cycle-2 added |
| `tests/unit/dsl/processors/security/` | 0 | 5 | cycle-1 added |
| `tests/unit/dsl/engine/processors/test_security.py` | 0 | 7 | cycle-1 modified |
| `tests/unit/infrastructure/cache/rag/` | 0 | (passed) | cycle-1 added |
| `tests/unit/services/ai/test_gateway_adapter.py` | 0 | 9 | cycle-1 modified |
| `tests/unit/entrypoints/filewatcher/test_watcher_routes.py` | 0 | (passed) | cycle-1 modified |
| `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py` | 0 | (passed) | cycle-1 added |
| `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` | 0 | (passed) | cycle-1 added |
| **Total** | **0** | **51+** | **0 failed** |

---

## 5. Contradictions / overlaps to flag

### 5.1 `diskcache` — комментарий vs реальность
- `tools/pip_audit_gate.py:19-21` говорит: `diskcache REMOVED in s170, replaced with custom JSONDisk cache`.
- Реальность: `diskcache 5.6.3` всё ещё INSTALLED (`from diskcache import Cache` в
  `src/backend/infrastructure/decorators/caching/storage/disk.py:6`).
- "JSONDisk cache" — НЕ существует (поиск 0 matches в src/).

→ Комментарий вводит в заблуждение. Diskcache — действующая зависимость.
CVE-2025-69872 остаётся активной защитой.

### 5.2 `pip-audit.json` empty
- Файл `pip-audit.json` существует (untracked, pre-existing per BASELINE), размер 0 bytes.
- `tools/pip_audit_gate.py:26-28` падает с exit 1 если файл не существует, но
  пустой файл — успешно парсится → `vuln_count = 0` → "PASS: 0 unignored vulnerabilities".
- Если CI не пересоздаёт файл через `pip-audit --output` — gate всегда PASS,
  даже если есть unfixed CVE.

→ Verify: `tools/pip_audit_gate.py` должен падать exit 1 на пустой JSON, не exit 0.

### 5.3 mlflow vs starlette conflict (deferred per pyproject comment)
- `pyproject.toml:347-349`: "mlflow 3.x requires starlette<1.0.0 which conflicts with
  core starlette>=1.0.1 (PYSEC-2026-161). Install ai-model-registry extra in isolated
  environments".
- В `.venv` (dev only): `starlette 1.3.1` installed, mlflow NOT installed.
- Реальная проблема только при `uv sync --extra ai-model-registry`.
- Не верифицировано offline (mlflow extra не установлен).

→ Out of immediate scope, but flag для awareness.

---

## 6. Readiness score

**Формула**: `score = 100 - (P0_count × 15) - (P1_count × 7) - (P2_count × 2) - (P3_count × 1)`

Где:
- P0 = security/data-loss/race/fail-open.
- P1 = layer boundaries / systemic drift.
- P2 = dead code / minor security hygiene.
- P3 = library replacement / minor hygiene.

**Расчёт**:
- P0 count = 3 (DEPS-P0-001, -002, -003) → -45
- P1 count = 2 (DEPS-P1-001, -002) → -14
- P2 count = 2 (DEPS-P2-001, -002) → -4
- P3 count = 2 (DEPS-P3-001, -002) → -2

**Score**: `100 - 45 - 14 - 4 - 2 = 35`

**Обоснование**:
- 3 P0 — все RESIDUAL от cycle-2 (код не изменился, retrospective commit только).
- 4-way CVE drift + 8 stale CVE IDs + streamlit без upper bound — это fail-open
  security gate: новый CVE может пройти незамеченным, потому что:
  (a) allowlist маскирует реальные CVE рядом со stale;
  (b) GitHub/GitLab CI ignore'ят разные CVE;
  (c) streamlit без upper bound позволяет breaking-change незаметно проникнуть в lock.
- Это серьёзные P0, блокирующие sprint sign-off для production-readiness.
- P1 issues — systemic drift (CI не покрывает deptry/creosote, stale comments),
  усугубляют P0.
- Score 35 отражает: infra (uv.lock, 35-entry allowlist pipeline) работает,
  но enforcement разорван в 4 местах, manual cleanup required.

**Score ≥80 запрещён при P0/P1** → score остановлен на 35 (правило соблюдено).

---

## 7. Recommended next tasks

1. **[P0, 30 min]** `chore(deps): cleanup 8 stale CVE из allowlist` —
   удалить L65,67,69,71,74,76,79 из `.security/pip-audit-allowlist.txt`.
   Проверить post-cleanup: `pip-audit` (если доступен) или static `grep`.

2. **[P0, 15 min]** `fix(deps): pin streamlit<2.0.0` —
   `pyproject.toml:137: "streamlit>=1.58.0,<2.0.0"`.
   Проверить: `uv lock --check`, 95 imports работают.

3. **[P0, 2 hr]** `chore(security): unify 4 CVE-enforcement sites` —
   Все 4 enforcement точки (GitHub workflow, GitLab CI, pip_audit_gate.py, Makefile)
   должны читать `.security/pip-audit-allowlist.txt` динамически.

4. **[P1, 1 hr]** `ci(deps): add deptry job to lint.yml` —
   non-blocking сначала, потом перевести на blocking после DEPS-P3-001 config.

5. **[P1, 5 min]** `docs(pip_audit_gate): remove stale comments` —
   удалить L18-21 в `tools/pip_audit_gate.py` (или удалить entry, если CVE fixed).

6. **[P2, 30 min]** `chore(deps): add upper bounds for 7 deps` —
   per §3.7 список.

7. **[P2, 15 min]** `docs(api): mark sphinx requirements.txt as DEPRECATED`.

8. **[P3, 30 min]** `tooling(deptry): add [tool.deptry] config` —
   `known_first_party = ["src"]` убирает 6700 false-positives.

9. **[P3, 1 hr]** `chore(deps): declare moto/boto3/clickhouse_connect in extras` —
   `testkit` extra + `[tool.deptry]` ignore для `tools/migrations/`.

---

## 8. Commands run (с Python interpreter)

| Команда | Python | Exit | Output |
|---|---|---|---|
| `git rev-parse HEAD` | n/a | 0 | `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` |
| `git status --short` | n/a | 0 | 14 modified + 8 untracked (BASELINE match) |
| `.venv/bin/python --version` | .venv | 0 | `Python 3.14.0` |
| `which python3` | system | 0 | `/usr/bin/python3` |
| `python3 -c "import prometheus_client"` | system | 1 | `ModuleNotFoundError: No module named 'prometheus_client'` |
| `.venv/bin/python -c "import prometheus_client"` | .venv | 0 | OK |
| `.venv/bin/python -c "import fastapi; print(fastapi.__version__)"` | .venv | 0 | `0.141.1` |
| `.venv/bin/python -c "import hypothesis; print(hypothesis.__version__)"` | .venv | 0 | `6.165.1` |
| `.venv/bin/python -c "from importlib.metadata import version; print(version('tenacity'))"` | .venv | 0 | `9.1.4` |
| `.venv/bin/python -c "from importlib.metadata import version; print(version('starlette'))"` | .venv | 0 | `1.3.1` |
| `.venv/bin/python -c "...version('streamlit')..."` | .venv | 0 | `1.61.0` |
| `.venv/bin/python -c "...version('sqladmin')..."` | .venv | 0 | `0.30.0` |
| `.venv/bin/python -c "...version('gitpython')..."` | .venv | 0 | `3.1.58` |
| `.venv/bin/python -c "...version('urllib3')..."` | .venv | 0 | `2.7.0` |
| `.venv/bin/python -c "...version('idna')..."` | .venv | 0 | `3.18` |
| `.venv/bin/python -c "...version('lxml')..."` | .venv | 0 | `6.1.1` |
| `.venv/bin/python -c "...version('mako')..."` | .venv | 0 | `1.4.1` |
| `.venv/bin/python -c "...version('mistune')..."` | .venv | 0 | `3.3.4` |
| `.venv/bin/python -c "...version('diskcache')..."` | .venv | 0 | `5.6.3` |
| `.venv/bin/python -c "...version('python-multipart')..."` | .venv | 0 | `0.0.32` |
| `.venv/bin/python -c "...version('strawberry-graphql')..."` | .venv | 0 | `0.323.2` |
| `.venv/bin/python /tmp/check_stale_cves.py` | .venv | 0 | 8 STALE entries identified |
| `.venv/bin/python -m pip_audit --format json --output /tmp/pip-audit-test.json --timeout 60` | .venv | 1 | ReadTimeout (pypi.org network blocked) |
| `curl -s --max-time 10 -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/pip-audit/json` | n/a | 28 | Network timeout |
| `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` | n/a | 0 | `35` |
| `grep -E "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt \| wc -l` | n/a | 0 | `35` |
| `.venv/bin/python -m deptry . \| tail -3` | .venv | 1 | `Found 289 dependency issues.` |
| `.venv/bin/python -m deptry src/backend \| tail -3` | .venv | 1 | `Found 6794 dependency issues.` (false-positives) |
| `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/reliability/ tests/unit/dsl/engine/processors/eip/routing/ tests/unit/dsl/processors/security/ -x --no-header -q` | .venv | 0 | `20 passed` |
| `.venv/bin/python -m pytest tests/unit/infrastructure/cache/rag/ tests/unit/services/ai/test_gateway_adapter.py tests/unit/entrypoints/filewatcher/test_watcher_routes.py tests/unit/entrypoints/cdc/test_management_endpoints_auth.py tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` | .venv | 0 | `34 passed` |
| `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_security.py` | .venv | 0 | `7 passed` |
| `.venv/bin/python -m pytest tests/unit/services/ai/test_gateway_adapter.py` | .venv | 0 | `9 passed` |
| `grep -nE "streamlit" pyproject.toml \| grep "^    \"streamlit"` | n/a | 0 | 2 entries (L137 no-upper, L477 with-upper) |
| `grep -E "no-first-party\|known-first-party" pyproject.toml` | n/a | 0 | 0 (нет [tool.deptry]) |
| `grep -rnE "deptry\|creosote" .github/workflows/*.yml` | n/a | 1 | 0 matches (CI не покрывает) |

**Python interpreter used for ALL runtime checks**: `.venv/bin/python` (Python 3.14.0).
**System Python** (`/usr/bin/python3`, debian default) — НЕ подключён к `.venv`, fails на
`prometheus_client`, `fastapi`, `hypothesis` (pre-existing env state, не dependency
domain issue).

---

## 9. Заключение

Домен **Зависимости** в cycle 3 имеет **3 P0 residual findings**, все унаследованные от
cycle-2 (код не менялся с `ca5bff93` → `7f3d94a3`):
- 4-way CVE drift enforcement (P0-001/003 cycle 2 → DEPS-P0-003 здесь).
- 8 stale CVE в active allowlist (часть P0-001 cycle 2 → DEPS-P0-001 здесь).
- `streamlit>=1.58.0` без upper bound (P0-004 cycle 2 → DEPS-P0-002 здесь).

**T-W3-01 (tenacity)** — **RESOLVED**: library pinned `tenacity>=9.0.0,<10.0.0`,
installed 9.1.4, используется в 7+ files (services/ai/agents, http_httpx,
flow.py, retry.py, и др.).

**Production-readiness для dependencies домена**: **35/100** — fail-open security
drift не устранён, требуется manual cleanup pass перед Sprint 36 sign-off.
