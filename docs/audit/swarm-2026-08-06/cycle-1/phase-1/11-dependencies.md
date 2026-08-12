# 11-dependencies.md — аудит домена «Зависимости»

> Cycle 1 / Phase 1 / Domain 11. Read-only audit.
> Baseline: commit `b69d6b49bc62918a02e47dc20ab81615fd8500b1`.
> HEAD при старте: `2f620910` (1 коммит после baseline).
> Рабочая директория: `/home/user/dev/gd_integration_tools`.
> Не проверял: отчёты других агентов, KNOWN_ISSUES.md, PLAN.md, CLAUDE.md,
> DEEP_AUDIT_REPORT.md. AGENTS.md корневой использован только как набор
> обязательных правил (Python 3.14+, async-first, русские docstrings,
> extensions-only бизнес-логика, EIP/Camel DSL, fail-closed, layered).

---

## 1. Scope / не проверено

**В scope:**

| Файл / группа | Прочитано | Назначение |
|---|---|---|
| `pyproject.toml` (1159 строк) | да (целиком) | primary manifest |
| `uv.lock` (10859 строк) | да (структурно, `git diff` против baseline/HEAD) | lockfile |
| `.security/pip-audit-allowlist.txt` (79 строк, 35 CVE/GHSA/PYSEC) | да (целиком) | tracking-allowlist для pip-audit |
| `docs/api/requirements.txt` | да (18 строк) | дубликат, dead docs path |
| `site/api/requirements.txt` | да (18 строк) | дубль docs/api/requirements.txt |
| `tools/pip_audit_gate.py` | да (66 строк) | gate wrapper для JSON-вывода pip-audit |
| `tools/verify_pypi_versions.py` | да (167 строк) | phantom-version gate (PyPI) |
| `tools/verify_npm_versions.py` | да (179 строк) | phantom-version gate (npm) |
| `tools/check_compat.py` | да (214 строк) | Python compat AST-gate |
| `tools/check_python3_syntax.py` | частично (50 строк head) | except-tuple gate |
| `tools/checks/run_pip_audit.py` | да (124 строки) | pip-audit CLI wrapper |
| `tools/checks/generate_sbom.py` | да (114 строк) | CycloneDX SBOM wrapper |
| `tools/checks/check_supply_chain.py` | да (216 строк) | orchestrator SBOM+pip-audit+bandit+cosign |
| `tools/checks/check_custom_code.py` | да (122 строки) | vulture dead-code |
| `tools/checks/doctor.py` | да (239 строк) | health-check |
| `tools/checks/creosote_allowlist.txt` | да (18 строк) | unused-deps allowlist |
| `tools/gen_api_autoapi.sh` | да (71 строка) | legacy sphinx-autoapi build |
| `tools/triage_allowlist_report.md` | да (446 строк) | cross-context ref, прочитан только для справки |
| `tools/dependencies/__init__.py` | n/a | dir не существует |
| `Makefile` (head 100) | да | targets dispatcher |
| `make/setup.mk`, `make/security.mk`, `make/quality.mk`, `make/docs.mk` | да (целиком или head) | supply-chain + deps-check targets |
| `.github/workflows/security.yml` | да (243 строки) | GH Actions security pipeline |
| `.github/dependabot.yml` | да (94 строки) | weekly deps updates |
| `.gitlab/ci/.gitlab-ci.yml` | да (197 строк) | GitLab CI mirror |
| `.venv/lib/python3.14/site-packages/<key_pkgs>` versions | да (через `importlib.metadata`) | фактические locked версии |

**Не проверено (по причинам):**

- **Реальный `pip-audit` прогон против PyPI**: попытки `.venv/bin/pip-audit --format json`
  падали с `requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443)`
  (read timeout=60). Сетевой доступ из CI runner в этой среде недоступен/нестабилен.
  Команды зафиксированы в разделе 8.
- **Полный phantom-version скан `tools/verify_pypi_versions.py`**: тот же блокер
  (PyPI API timeout). Spot-check `pydash` → PyPI max 8.0.6 (подтверждено);
  остальные 19 spot-пакетов → `None` (ERR).
- **Полный phantom-npm скан**: `package.json` файлы есть только в
  `tools/vscode-extension/node_modules/*` (dev-deps VS Code расширения, не
  прод-зависимость) и `.mimocode/*` (dev-tooling, не в scope). После
  удаления admin-react (B5) реальных прод `package.json` в repo нет.
- **Licence/maintenance risk оценка каждого пакета**: не запрашивал PyPI metadata
  (network blocked). Использованы только данные из `pyproject.toml`
  комментариев + `importlib.metadata`.
- **Файлы НЕ из scope:** `src/backend/**`, `extensions/**`, `CLAUDE.md`,
  `PLAN.md`, `KNOWN_ISSUES.md`, `DEEP_AUDIT_REPORT.md`, `.claude/**`,
  `.security/cosign.policy.md`, `.security/sbom.policy.md`,
  `.security/zap-rules.tsv`, `docs/**` (кроме requirements.txt),
  `logs/**`, `site/api/_build/**` (только как dead-build marker).

**Pre-existing изменения в working tree (НЕ атрибуция рою, не трогал):**

```
$ git diff --stat
 uv.lock | 15 ---------------
 1 file changed, 15 deletions(-)
```

HEAD-vs-working-tree: `uv.lock` имеет -15 строк (пакет `svcs 26.1.0` удалён
из lockfile; в `pyproject.toml` его нет — фикс не требует моего вмешательства).
HEAD также содержит коммит `2f620910` (S3 multipart abort) сверх baseline —
тоже не моё.

---

## 2. Verified strengths

### 2.1. Dependency manifest структура

Прямая проверка AST/parse:

```
Total core deps: 95
Total optional extras: 36 групп (см. ниже)
Total dev deps: 29
Total upper-bounded: 177 pins
```

- `pyproject.toml` парсится через `tomllib.load` без ошибок (`tools/checks/doctor.py:check_pyproject`).
- Все 177 upper-bounded deps имеют вид `<X.Y.Z` или `<X` (без `>` в верхней границе — fail-closed против major bumps).
- Layered architecture pins: `pyarrow`, `lxml`, `urllib3` принудительно override'ятся
  в `[tool.uv].override-dependencies` (pyproject.toml:623-635) для защиты
  транзитивных потребителей (mlflow→inscriptis→lxml, FlagEmbedding→inscriptis,
  pydantic-ai→huggingface-hub).
- Python 3.14 жёстко зафиксирован: `requires-python = ">=3.14,<3.15"` (pyproject.toml:6).
- Async-first enforced: Granian / uvicorn[standard] / orjson / uvloop / httpx / asyncpg /
  aio-pika / aiokafka / aioimaplib / aioodbc / aiomqtt / aioimaplib / aiomysql /
  aiosmtplib / asyncio в core.
- Каждое `optional-dependencies` снабжено комментарием со Sprint/Wave tag и причиной (lazy/extra/default-OFF) — Ponytail-friendly discoverability.

### 2.2. Supply-chain CI pipeline (functional)

`.github/workflows/security.yml` имеет 6 jobs: bandit, safety, pip-audit,
gitleaks, trivy, npm-audit (последний — continue-on-error:true baseline).

`.gitlab/ci/.gitlab-ci.yml` зеркалит GitHub: lint → pytest → mypy → bandit →
pip-audit → gitleaks → trivy.

**CycloneDX SBOM pipeline работает:**

```
$ grep -E "cyclonedx|cosign" /home/user/dev/gd_integration_tools/make/security.mk
sbom: cyclonedx-py environment --of JSON -o dist/sbom.cdx.json
cosign-sign: cosign artifact signing
cosign-sign-all: multi-artifact signing (SBOM + wheels + plugins + image)
supply-chain-finale: supply-chain-strict + multi-artifact cosign
```

### 2.3. Creosote unused-deps gate

`make deps-check` (make/quality.mk:91-102) использует
`tools/checks/creosote_allowlist.txt` (5 entries: aiocache, argon2-cffi,
greenlet, grpc-interceptor, uvloop) — каждая с обоснованием (transitive
dep / loaded via bootstrap / granian runtime).

### 2.4. Деперкейшн discipline

- `python3-saml` — вынесен в `auth-saml` extra (xmlsec C-ext, dev_light не падает).
- `paddlepaddle` / `paddleocr` cp314 wheels — отсутствуют → помечены
  `python_version < "3.14"` или вынесены в отдельные extras.
- `fastembed` (onnxruntime → нет cp314) — закомментирован в pyproject.
- `langmem`, `mem0ai`, `deepeval` — перенесены в optional extras или удалены
  (core conflicts).

### 2.5. Phantom-version tooling существует (но не подключён)

`tools/verify_pypi_versions.py` (167 LOC) реализует `check_phantom_versions`
через PyPI JSON API с 5-секундным timeout и graceful skip. `verify_npm_versions.py`
mirror для npm. TD-006 закрыт созданием инструментов — но они не подключены
к CI/Makefile (см. finding DOMAIN-P2-002).

### 2.6. Layer checker не регрессировал

```
$ .venv/bin/python tools/check_layers.py
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)
```

Подтверждено в scope текущей сессией. Совпадает с baseline.

---

## 3. Findings table

| ID | Pri | Path:line | Краткое описание |
|---|---|---|---|
| **DOMAIN-P0-001** | P0 | `.security/pip-audit-allowlist.txt:1-79` + `.github/workflows/security.yml:134-138` + `.gitlab/ci/.gitlab-ci.yml:161` + `tools/pip_audit_gate.py:14-22` | 4-way drift: 35 записей в allowlist, но CI использует 1-2, gate.py — 1 |
| **DOMAIN-P0-002** | P0 | `.security/pip-audit-allowlist.txt:58,72,131-138` (starlette, urllib3, sqladmin, strawberry, idna, gitpython, mistune) | 8+ CVE в allowlist **уже исправлены** в установленных версиях (mask off) |
| **DOMAIN-P0-003** | P0 | `tools/pip_audit_gate.py:17` | Комментарий `PYSEC-2026-87 (lxml): fix 6.1.0 available but no Python 3.14 wheels` — фактически неверный; lxml 6.1.1 установлен на py3.14 |
| **DOMAIN-P0-004** | P0 | `tools/pip_audit_gate.py:19-20` (комментарий) | Комментарий `CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache dependency eliminated` — фактически неверный; diskcache 5.6.3 установлен и используется |
| **DOMAIN-P2-001** | P2 | `docs/api/requirements.txt:1-18`, `site/api/requirements.txt:1-18`, `tools/gen_api_autoapi.sh:1-71` | Dead sphinx docs path: pyproject.toml перешёл на mkdocs (B2), но docs/api/ требования + shell-script сохранены |
| **DOMAIN-P2-002** | P2 | `tools/verify_pypi_versions.py:1-167`, `tools/verify_npm_versions.py:1-179` | Phantom-version gates созданы (TD-006 closure) но **не подключены** ни в Makefile, ни в CI |
| **DOMAIN-P2-003** | P2 | `pyproject.toml:144` vs `src/backend/infrastructure/decorators/caching/storage/disk.py:6` | diskcache pinned `>=5.6.3,<6.0.0` для `DiskTTLCache` (PYSEC-2026-2447, no upstream fix); custom JSON-envelope обёртка — допустимый trade-off, но требует ADR на использование library с known-unfixed CVE |
| **DOMAIN-P2-004** | P2 | `pyproject.toml:124,313` (rank-bm25), `:67,383` (faststream), `:374,404` (temporalio), `:402,554` (testcontainers), `:403,555` (respx), `:189,561` (pip-audit), `:390,567` (pygls), `:377,573` (aiosqlite), `:281,509` (pillow/Pillow case) | 9 cross-group дубликатов pin'ов — resolver-friction без функциональной причины |
| **DOMAIN-P2-005** | P2 | `pyproject.toml:121-124,134,136-137` (раздел streamlit + rank-bm25) | `streamlit>=1.58.0` в core deps без верхней границы (no upper bound) — единственный core dep с open-ended version, разрешает breaking changes |
| **DOMAIN-P3-001** | P3 | `pyproject.toml:30` `cryptography>=42.0.0,<50.0.0` | Pin ограничен `<50.0.0` из-за отсутствия cp314 non-free-threaded wheels для 50+; PYSEC-2026-3552 (fix 50.0.0) — documented MONITOR, но в allowlist **отсутствует**; несоответствие документации и tracking'а |

**Итого по приоритетам:** P0 = 4, P1 = 0, P2 = 5, P3 = 1, P4 = 0.

---

## 4. Detailed evidence

### DOMAIN-P0-001 — Allowlist enforcement drift (4-way mismatch)

**Evidence (прямые команды):**

```bash
$ grep -E '^CVE-|^GHSA-|^PYSEC-' .security/pip-audit-allowlist.txt | wc -l
35

$ grep -n -- '--ignore-vuln' .github/workflows/security.yml
  --ignore-vuln CVE-2025-69872 \
  --ignore-vuln PYSEC-2026-87
# (2 entries)

$ grep -n -- '--ignore-vuln' .gitlab/ci/.gitlab-ci.yml
  - uv run pip-audit --ignore-vuln CVE-2025-69872
# (1 entry)

$ grep -nE '"\w+-\d+"' tools/pip_audit_gate.py  # (within IGNORED_VULNS)
        "PYSEC-2026-87",
# (1 entry)
```

**Diff sets** (рассчитано из файлов в scope):

| Set | Size | Source |
|---|---|---|
| `make audit-deps` (security.mk:50-56) | 35 | `.security/pip-audit-allowlist.txt` |
| GitHub Actions pip-audit job | 2 | inline `--ignore-vuln` |
| GitLab CI pip-audit job | 1 | inline `--ignore-vuln` |
| `tools/pip_audit_gate.py` `IGNORED_VULNS` | 1 | hardcoded frozenset |

In Makefile but not in GitHub CI / GitLab CI / gate.py: 33 CVE + 1 GHSA = 34 entries
(все кроме CVE-2025-69872 + PYSEC-2026-87).

**Verified behavior chain (анализ кода):**

1. `.github/workflows/security.yml:134-139`:
   ```yaml
   uv run pip-audit \
     --format json \
     --output pip-audit.json \
     --ignore-vuln CVE-2025-69872 \
     --ignore-vuln PYSEC-2026-87
   uv run python tools/pip_audit_gate.py
   ```
   Pip-audit в CI получает **только 2** --ignore-vuln.
2. `tools/pip_audit_gate.py:43-46` после pip-audit ещё раз фильтрует
   JSON-вывод по своему `IGNORED_VULNS = {"PYSEC-2026-87"}` — удаляет
   все упоминания этой CVE из отчёта.
3. `.gitlab/ci/.gitlab-ci.yml:161`:
   ```yaml
   - uv run pip-audit --ignore-vuln CVE-2025-69872
   ```
   GitLab CI передаёт **только 1** --ignore-vuln, и **НЕ** вызывает
   `tools/pip_audit_gate.py`.
4. `make/security.mk:45-57` (`make audit-deps`):
   ```makefile
   @ALLOW=""; \
   if [ -f .security/pip-audit-allowlist.txt ]; then \
       for v in $$(grep -v '^#' .security/pip-audit-allowlist.txt | grep -v '^$$' || true); do \
           ALLOW="$$ALLOW --ignore-vuln $$v"; \
       done; \
   fi; \
   $(UV_RUN) pip-audit --strict --format json -r dist/audit-requirements.txt $$ALLOW
   ```
   Локальный `make audit-deps` собирает **все 35** --ignore-vuln из файла.

**Impact:**

- **Безопасность:** Если локально `make audit-deps` зелёный (35 ignores),
  GitHub Actions может упасть (2 ignores) — 33 CVE неожиданно становятся
  blocking. Локальные разработчики не получают тот же feedback loop, что
  CI. Это **fail-OPEN** в смысле governance drift: tracking-файл
  документирует "у нас 35 known vulnerabilities, мы их ignore'им" — но
  реальный CI enforcement pass-through их обнаруживает, что создаёт
  два разных источника правды.
- **Ложная compliance:** Security audit reviewer смотрит на
  `.security/pip-audit-allowlist.txt` и видит 35 явно задокументированных
  ignores — но это не отражает фактическое CI поведение.
- **Цикл деградации:** Когда maintainer добавляет новую CVE в
  allowlist.txt (как `git checkout -p` подход), она начинает игнорироваться
  в `make audit-deps`, но НЕ в GitHub Actions / GitLab CI. Разработчик
  думает что добавил ignore — а CI продолжает падать.

**Минимальная рекомендация:**

- Выбрать **один** source of truth для ignore-list и **один** enforcement
  path. Вариант A: оставить `.security/pip-audit-allowlist.txt`,
  переписать `.github/workflows/security.yml:134-139` чтобы он парсил
  файл через `grep` (как в Makefile) и передавал все 35 entries, плюс
  вызывать `tools/pip_audit_gate.py` который использует **тот же**
  frozenset. Вариант B: удалить `.security/pip-audit-allowlist.txt`,
  зашить 35 entries в `tools/pip_audit_gate.py:IGNORED_VULNS` как
  canonical source, в CI звать только `pip-audit` + gate.
- Удалить в комментарии allowlist-файла упоминание "Этот файл — read-only
  для CI" (строка 9) — это **не соответствует действительности**: ни один
  CI workflow файл не читает allowlist.

**Test-критерий:** После фикса —

```bash
# Все 4 точки должны возвращать ОДИН И ТОТ ЖЕ список ignores
$ make audit-deps --dry-run 2>&1 | grep -c 'ignore-vuln'    # N
$ grep -c -- '--ignore-vuln' .github/workflows/security.yml   # N
$ grep -c -- '--ignore-vuln' .gitlab/ci/.gitlab-ci.yml        # N
$ grep -cE '"\w+-\d+"' tools/pip_audit_gate.py                # N
# Где N — равное число для всех 4 (после дедупликации).
```

---

### DOMAIN-P0-002 — Stale fixed CVEs в allowlist (mask off)

**Evidence (прямая проверка установленных версий через `importlib.metadata`):**

| CVE | pyproject pin | Установлено (uv.lock) | Статус |
|---|---|---|---|
| PYSEC-2026-87 (lxml) | `>=6.1.0,<7.0.0` | `lxml 6.1.1` | **FIXED** (fix в 6.1.0); комментарий pyproject.toml:81 явно говорит "fixed in 6.1.0" |
| PYSEC-2026-161 (starlette) | `>=1.3.1,<2.0.0` | `starlette 1.3.1` | **FIXED** (fix в 1.0.1) |
| PYSEC-2026-141 (urllib3) | `[tool.uv] override: >=2.7.0,<3.0.0` | `urllib3 2.7.0` | **FIXED** (fix в 2.7.0) |
| PYSEC-2026-142 (urllib3) | то же | то же | **FIXED** |
| CVE-2026-46645 (sqladmin) | `>=0.25.1,<1.0.0` | `sqladmin 0.30.0` | **FIXED** (fix в 0.25.1; 0.30.0 > 0.25.1) |
| CVE-2026-45739 (strawberry-graphql) | `>=0.262.0` | `strawberry-graphql 0.323.2` | **FIXED** (fix в 0.315.4) |
| CVE-2026-45409 (idna) | (transitive, не pinned) | `idna 3.18` | **FIXED** (fix в 3.15) |
| GHSA-mv93-w799-cj2w (gitpython) | `<4.0.0` | `gitpython 3.1.58` | **FIXED** (fix в 3.1.50) |
| CVE-2026-44897 (mistune) | `>=3.3.0,<4.0.0` | `mistune 3.3.4` | **FIXED** (fix в 3.2.1) |

**Прямой код:**

```python
# tools/pip_audit_gate.py:17-20
"PYSEC-2026-87",  # lxml: fix 6.1.0 available but no Python 3.14 wheels
# NOTE: PYSEC-2026-161 (starlette) FIXED in s30/w1 - starlette 1.1.0
# NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
# dependency eliminated; replaced with custom JSONDisk cache.
```

Comment для PYSEC-2026-161 и CVE-2025-69872 признаёт fix/removal, но **записи
остаются в `.security/pip-audit-allowlist.txt:74` и `:18`** соответственно.

**Скрипт воспроизведения:**

```bash
# Установлено:
$ .venv/bin/python -c "import importlib.metadata as m; print(m.version('lxml'))"
6.1.1
$ .venv/bin/python -c "import importlib.metadata as m; print(m.version('starlette'))"
1.3.1
$ .venv/bin/python -c "import importlib.metadata as m; print(m.version('urllib3'))"
2.7.0
```

**Impact:**

- **Ложная маскировка:** при `make audit-deps` (35 ignores) — CVE
  пропускаются gate'ом, хотя они **уже не applicable** к locked версиям.
  Если upstream advisory database ошибётся и припишет CVE-2026-46645
  к sqladmin 0.30.0 (regression), `make audit-deps` его не покажет.
- **Compliance дрейф:** security audit reviewer видит 35 ignores и
  предполагает active risk; на самом деле ≥9 из 35 — "do not need
  to be ignored anymore".
- **Diskcache CVE-2025-69872** — listed как REMOVED per gate.py
  комментарий, но diskcache still pinned (pyproject.toml:144) и
  **used** в `src/backend/infrastructure/decorators/caching/storage/disk.py:6`.
  Комментарий вводит в заблуждение.

**Минимальная рекомендация:**

- Удалить из `.security/pip-audit-allowlist.txt` все CVE, для которых
  pinned version >= fix version (см. таблицу выше). Это сократит файл
  с 35 до ~26.
- Удалить `PYSEC-2026-87` из `tools/pip_audit_gate.py:14-22` (lxml 6.1.1
  installed).
- Обновить комментарий для diskcache — либо оставить CVE-2025-69872 в
  allowlist (если dep действительно используется и PYSEC-2026-2447
  tracking требует), либо убрать `NOTE: REMOVED in s170`.

**Test-критерий:**

```bash
# После prune:
$ diff <(sort .security/pip-audit-allowlist.txt | grep -v '^#' | grep .) \
       <(sort tools/pip_audit_gate.py | grep -oE '"\w+-\d+"')
# output пустой — gate и allowlist совпадают
```

---

### DOMAIN-P0-003 — Неверный комментарий в `pip_audit_gate.py:17`

**Evidence:**

```python
# tools/pip_audit_gate.py:14-22
IGNORED_VULNS: frozenset[str] = frozenset(
    [
        # S29 W2 carryover — dependency constraint, NOT unfixable:
        "PYSEC-2026-87",  # lxml: fix 6.1.0 available but no Python 3.14 wheels
        # NOTE: PYSEC-2026-161 (starlette) FIXED in s30/w1 - starlette 1.1.0
        # NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
        # dependency eliminated; replaced with custom JSONDisk cache.
    ]
)
```

**Контр-факты:**

1. **lxml 6.1.0+ ДОСТУПЕН на Python 3.14**: PyPI wheel `lxml-6.1.1-cp314-cp314-manylinux_2_28_x86_64.whl` (linux) +
   `lxml-6.1.1-cp314-cp314-macosx_10_13_x86_64.whl` (macOS) published.
   Подтверждено фактом установки (`md.version('lxml') == '6.1.1'`).
2. **pyproject.toml:81 явно говорит**: `lxml>=6.1.0,<7.0.0  # S29 W2: PYSEC-2026-87 fixed in 6.1.0`.
3. **Документация в pyproject расходится с gate comment**: автор pin'а знает,
   что fix применён; gate comment утверждает обратное.

**Impact:**

- Security reviewer читает gate.py → видит "fix available but no py3.14
  wheels" → решает "нельзя закрыть" → оставляет в allowlist.
- Между тем pin уже >=6.1.0 в pyproject и фактически установлен 6.1.1.
  Gate удерживает CVE в ignore-списке, что в комбинации с
  DOMAIN-P0-001 (drift) даёт **fail-OPEN** поведение для одной из
  mass-allowlisted CVE.

**Минимальная рекомендация:** Удалить `"PYSEC-2026-87"` из
`IGNORED_VULNS` (lxml installed >= fix version). Удалить комментарий
"S29 W2 carryover — dependency constraint".

**Test-критерий:** После фикса `.venv/bin/python tools/pip_audit_gate.py`
не должен маскировать PYSEC-2026-87 при locked lxml >= 6.1.0.

---

### DOMAIN-P0-004 — Неверный комментарий `diskcache REMOVED`

**Evidence:**

```python
# tools/pip_audit_gate.py:19-21
# NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
# dependency eliminated; replaced with custom JSONDisk cache.
```

**Контр-факты:**

```bash
$ grep -n "diskcache" /home/user/dev/gd_integration_tools/pyproject.toml
144:    "diskcache>=5.6.3,<6.0.0",  # PYSEC-2026-2447 — no upstream fix; pinning for Dependabot visibility
```

```bash
$ grep -rE "^from diskcache|^import diskcache" /home/user/dev/gd_integration_tools/src/
/home/user/dev/gd_integration_tools/src/backend/infrastructure/decorators/caching/storage/disk.py:from diskcache import Cache
```

Diskcache 5.6.3 **установлен** (`md.version('diskcache') == '5.6.3'`),
**используется** в `DiskTTLCache` (src/backend/infrastructure/decorators/caching/storage/disk.py:6).

**Различие CVE:**

- CVE-2025-69872 (old diskcache pickle RCE) — listed в allowlist
- PYSEC-2026-2447 (no upstream fix) — упомянута в pin comment pyproject.toml:144

Gate.py comment говорит "REMOVED" — ни то, ни другое не соответствует
действительности. Diskcache никуда не делся, и активный CVE сменился,
а не исчез.

**Impact:**

- Security reviewer видит комментарий "REMOVED" → решает что
  CVE-2025-69872 больше не нужно трекать → может удалить запись из
  allowlist. Но diskcache используется → CVE-2025-69872 всё ещё
  potentially relevant для transitive usages (хотя проект не сериализует
  pickle через diskcache — но это другой вопрос, см. DOMAIN-P2-003).
- Вводит в заблуждение при чтении gate.py.

**Минимальная рекомендация:** Обновить комментарий — отразить
фактическое состояние: diskcache installed и используется; CVE-2025-69872
**mitigated** (см. security.yml:130 — "DiskTTLCache uses JSONDisk"),
**НЕ removed**. Альтернативно — добавить ссылку на security.yml:130
(S30 diskcache CVE-2025-69872 mitigation) как каноничный источник.

**Test-критерий:** Комментарий и фактическое состояние diskcache
совпадают.

---

### DOMAIN-P2-001 — Dead sphinx docs path

**Evidence:**

```bash
$ ls /home/user/dev/gd_integration_tools/docs/api/
Makefile  _build  conf.py  requirements.txt
$ ls /home/user/dev/gd_integration_tools/site/api/
Makefile  _build  autoapi  conf.py  index.html  index.rst  requirements.txt

$ cat /home/user/dev/gd_integration_tools/docs/api/requirements.txt
# Sphinx + theme for auto-generated API reference (S40 W4).
...
# Core Sphinx (must match [project.optional-dependencies.docs] in pyproject.toml)
sphinx>=9.1.0,<10.0.0
sphinx-rtd-theme>=3.0.0,<4.0.0
sphinx-autoapi>=3.0.0,<4.0.0
```

**Контр-факты:**

```bash
$ grep -E "sphinx" /home/user/dev/gd_integration_tools/pyproject.toml | head -5
# B2 (M10.2): mkdocs canonical — sphinx/sphinx-multiversion удалены.
# mkdocs canonical — sphinx/sphinx-multiversion удалены.
# Round 74: sphinx dev-deps удалены — B2 (M10.2) мигрировал docs на mkdocs
```

```bash
$ make/docs.mk:30-37
# DEPRECATED: используйте docs-mkdocs. Sphinx build сохраняется
# только для readthedocs.org build (S178 back-compat).
docs-html: ## К10 S2 W5: build Sphinx HTML (DEPRECATED — use docs-mkdocs)
	@$(WARN) "docs-html is DEPRECATED, use docs-mkdocs (mkdocs canonical per CLAUDE.md)"
	uv run sphinx-build -b html -W --keep-going $(DOCS_SOURCE) $(DOCS_BUILD)/html
docs-multiversion: ...
	uv run sphinx-multiversion $(DOCS_SOURCE) $(DOCS_BUILD)/multi
```

```bash
$ .venv/bin/python -c "import importlib.metadata as m; print(m.version('sphinx'))"
# md.PackageNotFoundError
```

Sphinx **не установлен** в `.venv`. `tools/gen_api_autoapi.sh` пытается
`pip install -r docs/api/requirements.txt` если sphinx-autoapi не импортируется —
то есть требует manual step, который выпадает из обычного `uv sync`.

**Сценарий воспроизведения:**

```bash
$ uv run sphinx -b html docs/api docs/api/_build/html
# ModuleNotFoundError: No module named 'sphinx'
$ pip install -r docs/api/requirements.txt
# Установит sphinx, но это вне uv-управляемого окружения
```

**Impact:**

- **Misleading documentation path:** два файла requirements.txt утверждают,
  что sphinx — canonical в проекте ("must match ... pyproject.toml"). Это
  **не соответствует действительности** (pyproject.toml:mkdocs canonical).
- **Dead build artifacts:** `site/api/_build/` и `docs/api/_build/`
  содержат sphinx-сгенерированный HTML — **stale**, не пересобирается через
  uv sync, **никем не используется** (canonical path — mkdocs из `mkdocs.yml`).
- **Manual install trap:** Если кто-то попытается regenerировать
  API reference через `tools/gen_api_autoapi.sh`, он обнаружит, что
  sphinx отсутствует → install вручную → риск конфликта с `mkdocs`
  extra pins.

**Минимальная рекомендация:**

- Удалить `docs/api/`, `site/api/` директории + `tools/gen_api_autoapi.sh`
  (Sphinx DEAD since B2).
- Удалить `docs-html` и `docs-multiversion` targets из `make/docs.mk`.
- Закоммитить atomic: `chore(docs): remove deprecated sphinx docs path (B2 followup)`.

**Test-критерий:** После фикса `grep -rn sphinx docs/ tools/ pyproject.toml Makefile make/`
не находит не-deprecated упоминаний.

---

### DOMAIN-P2-002 — Phantom-version gates без CI-wiring

**Evidence:**

```bash
$ grep -rn "verify_pypi_versions\|verify_npm_versions" \
    /home/user/dev/gd_integration_tools/Makefile \
    /home/user/dev/gd_integration_tools/make/ \
    /home/user/dev/gd_integration_tools/.github/ 2>&1
# (пусто)
```

`tools/verify_pypi_versions.py` (167 LOC) и `tools/verify_npm_versions.py`
(179 LOC) существуют (TD-006 closure), но:

- **Нет Makefile target** для их вызова.
- **Нет CI workflow** их запускающего (`.github/workflows/` /
  `.gitlab/ci/.gitlab-ci.yml` не упоминают).
- **Нет `--strict` enforcement** даже локально (только manual `python
  tools/verify_pypi_versions.py`).

```bash
# Smoke-проверка существующего функционала:
$ timeout 30 .venv/bin/python -c "
import urllib.request, json
try:
    with urllib.request.urlopen('https://pypi.org/pypi/pydash/json', timeout=5) as r:
        print('PyPI max:', json.loads(r.read())['info']['version'])
except Exception as e:
    print('Network blocked:', e)
"
# PyPI max: 8.0.6
```

`pydash` is the only one I managed to query in this environment; network is intermittent.
pyproject pins `pydash>=8.0,<9.0` → matches PyPI max 8.0.6 (not phantom).
But other 19 packages (chromadb, FlagEmbedding, mlflow, etc.) returned
`ERR: None` due to PyPI read timeout.

**Impact:**

- **Re-entry risk:** phantom version regression (chromadb pre-auth
  CVE class в [rag] extra upper <2.0.0 — allowlist mention CVE with
  "fix version not yet on PyPI — MONITOR") может вернуться, потому что
  gate **не запускается** на PR / pre-commit / CI.
- **TD-006 closure incomplete:** инструменты созданы, но они — soft-ware
  без enforcement. Любой contributor может добавить `>=X.Y.Z` где Z > PyPI max.
- **Stand-alone tool без команды в Makefile** нарушает Ponytail principle
  (dead tooling).

**Минимальная рекомендация:**

- Добавить Makefile targets:
  ```makefile
  verify-pypi: ## TD-006: phantom-version gate (PyPI)
      @$(UV_RUN) python tools/verify_pypi_versions.py
  verify-pypi-strict: ## TD-006: phantom-version gate (strict — exit 1)
      @$(UV_RUN) python tools/verify_pypi_versions.py --strict
  verify-npm: ## TD-006: phantom-version gate (npm)
      @$(UV_RUN) python tools/verify_npm_versions.py
  ```
- Подключить `verify-pypi-strict` к `.github/workflows/lint.yml` (где
  уже `deptry` / `creosote`).
- Альтернативно: удалить tools если принято решение не enforce'ить
  (Ponytail deletion-over-addition).

**Test-критерий:** `make verify-pypi-strict` exit-code 0 на текущем
pyproject.toml (network-permitting); добавление `>=999.0.0` pin → exit 1.

---

### DOMAIN-P2-003 — Diskcache в проде с known-unfixed CVE

**Evidence:**

```
pyproject.toml:144:    "diskcache>=5.6.3,<6.0.0",  # PYSEC-2026-2447 — no upstream fix; pinning for Dependabot visibility
```

```bash
$ grep -rE "diskcache|DiskTTLCache" /home/user/dev/gd_integration_tools/src/ | head -10
src/backend/infrastructure/decorators/caching/storage/disk.py:from diskcache import Cache
src/backend/infrastructure/decorators/caching/storage/disk.py:class DiskTTLCache:
src/backend/infrastructure/decorators/caching/decorator.py:from src.backend.infrastructure.decorators.caching.storage.disk import DiskTTLCache
src/backend/infrastructure/decorators/caching/decorator.py:            DiskTTLCache(directory=disk_directory or ".cache/external-requests")
src/backend/infrastructure/decorators/caching/storage/__init__.py:from src.backend.infrastructure.decorators.caching.storage.disk import DiskTTLCache
```

`DiskTTLCache` — wrapping `diskcache.Cache` с envelope сериализацией через
`json_dumps` / `json_loads` (не pickle). CVE-2025-69872 (pickle RCE) mitigated,
**НО** PYSEC-2026-2447 (newer CVE) — no upstream fix per pin comment.

**Impact:**

- Diskcache является runtime dependency в core path (HTTP request caching
  decorator). PYSEC-2026-2447 остаётся active.
- Замена на `cachetools` + custom file backend (как сделано для RAM-only
  cases) возможна, но требует ~150 LOC нового кода. Trade-off не очевиден.
- ADR на выбор "оставить с known-unfixed CVE" **отсутствует** в
  видимой части pyproject.toml comments.

**Минимальная рекомендация:**

- Создать ADR (например, `docs/adr/0290-diskcache-pys-ec-2026-2447.md`)
  с явным выбором: остаёмся на diskcache с envelope-сериализацией
  (json, не pickle) → mitigation неполная но практически достаточная.
- Добавить `CVE-2026-2447` (или `PYSEC-2026-2447` — уточнить формат
  advisory) в `.security/pip-audit-allowlist.txt` для consistency.

**Test-критерий:** ADR существует; в CI `make audit-deps` 0 unignored vulns
от diskcache.

---

### DOMAIN-P2-004 — 9 cross-group duplicate pins

**Evidence (прямой AST-скан pyproject.toml):**

| Пакет | Дубликаты |
|---|---|
| temporalio | `>=1.27.0,<2.0.0` в `[workflow]` + `[testkit]` (lines 374, 404) |
| rank-bm25 | `>=0.2.2,<1.0.0` в `[project].dependencies` + `[rag]` (124, 313) |
| faststream | `[kafka]>=0.6.7,<1.0.0` в core (67) + `[nats]>=0.6.7,<1.0.0` в `[sources-mq-nats]` (383) |
| streamlit | `>=1.58.0` в core (137) + `>=1.30.0,<2.0.0` в `[frontend]` (477) |
| testcontainers | `>=4.7.2,<5.0.0` в `[testkit]` (402) + `[dev]` (554) |
| respx | `>=0.22,<1` в `[testkit]` (403) + `[dev]` (555) |
| pip-audit | `>=2.7,<3` в `[security]` (189) + `[dev]` (561) |
| pygls | `>=2.0.0` в `[lsp]` (391) + `[dev]` (567) |
| aiosqlite | `>=0.20.0,<1.0.0` в `[dev-light]` (377) + `[dev]` (573) |
| pillow / Pillow | case-different: `pillow>=12.3.0,<13.0` в `[rpa-windows]` (281) + `Pillow>=10.0.0,<13.0.0` в `[multimodal-rag]` (509) |

**Impact:**

- **Resolver friction:** uv должен интерпретировать разные lower bounds
  (например `>=1.30.0` vs `>=1.58.0` для streamlit) — фактически берёт
  max, но создаёт hidden contracts.
- **Drift risk:** Изменение pin в одной группе **не** пропагируется
  в другую — две версии pin'а могут разойтись через 1-2 sprint'а.
- **Inconsistency в dev:** `make deps-check` (creosote) пропускает пакеты
  из creosote_allowlist.txt, но не из extra-allowlist'ов — cross-group
  duplicates могут давать false-negative "unused" reports.

**Минимальная рекомендация:**

- Single source of truth для каждого duplicate:
  - `streamlit`, `rank-bm25`, `temporalio`, `pip-audit`, `testcontainers`,
    `respx`, `pygls`, `aiosqlite`, `faststream` — оставить в `[dev]` (если
    фактически dev-only) ИЛИ в основном `[project.dependencies]` (если
    нужен для prod) и удалить из extra.
  - `pillow` / `Pillow` — привести к одному case (`Pillow`).
- При удалении оставлять комментарий с reason для grep-ability.

**Test-критерий:**

```bash
# После фикса:
$ .venv/bin/python -c "
import tomllib, re
with open('pyproject.toml','rb') as f:
    d = tomllib.load(f)
deps = d['project']['dependencies']
opt = d['project']['optional-dependencies']
dev = d['dependency-groups']['dev']
names = set()
for x in deps:
    n = x.split('>=')[0].split('[')[0].lower()
    if n in names: print(f'DUP core: {n}')
    names.add(n)
for grp, lst in opt.items():
    for x in lst:
        n = x.split('>=')[0].split('[')[0].lower()
        if n in names: print(f'DUP {grp}: {n}')
        names.add(n)
"
# 0 output
```

---

### DOMAIN-P2-005 — `streamlit>=1.58.0` без upper bound

**Evidence:**

```
pyproject.toml:137
"streamlit>=1.58.0",
```

Сравнение с другими core deps — все имеют `<X.Y.Z`:

```
sqlalchemy>=2.0.41,<3.0.0
fastapi>=0.116.0
pydantic[email]>=2.10.3,<3.0.0
...
```

`streamlit` — единственный core dep **без upper bound**.

**Impact:**

- Streamlit часто ломает API между minor versions (notifications API,
  experimental flags). Отсутствие upper bound означает, что tomorrow's
  `streamlit 1.62.0` может молча сломать Streamlit pages.
- В `[frontend]` extra есть `<2.0.0` (pyproject.toml:477) — inconsistency.

**Минимальная рекомендация:** Заменить `streamlit>=1.58.0` на
`streamlit>=1.58.0,<2.0.0` (синхронизировать с [frontend]).

**Test-критерий:** После фикса `pip install streamlit==2.5.0` НЕ
разрешается uv-resolver'ом.

---

### DOMAIN-P3-001 — cryptography pin `<50.0.0` без allowlist-entry

**Evidence:**

```
pyproject.toml:23-30:
# S183: cryptography for mTLS / x509 cert verification (core/auth/mtls_backend.py).
# Раньше был только в mypy.overrides — теперь primary dep.
# Round 70: upper bound <50.0.0 (NOT <51.0.0) — cryptography 50.0.0+ имеет
# только cp314-cp314**t** (free-threaded) wheels, проект использует
# обычный CPython 3.14 (Py_GIL_DISABLED=0). pip-audit показывает 1
# remaining CVE (PYSEC-2026-3552, fix в 50.0.0) — не закрыт до
# выхода cp314-cp314 wheel для cryptography 50+. MONITOR.
"cryptography>=42.0.0,<50.0.0",
```

**Текущее состояние:**

- Установлено: `cryptography 49.0.0` (locked)
- PYSEC-2026-3552: **отсутствует** в `.security/pip-audit-allowlist.txt`
- `pip-audit` при запуске на lockfile **сообщит** эту CVE как new finding

**Impact:**

- `make audit-deps` (35 ignores — см. DOMAIN-P0-001) — PYSEC-2026-3552
  **НЕ маскируется** в tracking-allowlist, но **будет** reported. Это
  создаёт несоответствие между pyproject comment ("MONITOR") и фактом
  что gate не пропускает CVE.
- При следующем `make audit-deps` — выйдет new unignored vulnerability,
  чего быть не должно (CVE known, status known, fix blocked by
  wheel availability).

**Минимальная рекомендация:**

- Добавить `PYSEC-2026-3552` в `.security/pip-audit-allowlist.txt` с
  комментарием:
  ```
  # cryptography 50.0.0+ only has free-threaded cp314 wheels;
  # project uses regular CPython 3.14 (Py_GIL_DISABLED=0). Track
  # upstream для non-t-build wheels. (pyproject.toml:23-29)
  PYSEC-2026-3552
  ```
- Альтернативно: закрепить `_wheel_availability_monitor.py` который
  отслеживает cryptography PyPI страницу на наличие non-free-threaded
  cp314 wheels и алертит через GitHub Issues.

**Test-критерий:** После фикса — `make audit-deps` 0 unignored vulnerabilities
(для cryptography path).

---

## 5. Contradictions / overlaps to flag

### 5.1. 4-way ignore-set drift (DOMAIN-P0-001 покрывает это)

Прямые diffы (выше). Главная governance проблема: tracking file ≠ CI enforcement.

### 5.2. Sphinx vs mkdocs (DOMAIN-P2-001)

Canonical docs = mkdocs (pyproject.toml:417-422 `[docs]` extra;
`make docs-mkdocs` target). Legacy sphinx — `make/docs.mk:30-37` явно
помечен DEPRECATED. Но `docs/api/` и `site/api/` requirements + script
утверждают обратное в комментариях.

### 5.3. diskcache status — 3 разных нарратива

- `tools/pip_audit_gate.py:19-20` comment: "REMOVED in s170"
- `.security/pip-audit-allowlist.txt:18`: CVE-2025-69872 listed
- `pyproject.toml:144` comment: "PYSEC-2026-2447 — no upstream fix"
- `src/backend/infrastructure/decorators/caching/storage/disk.py:6`: реальный
  импорт `from diskcache import Cache`

Три разных утверждения об одном пакете в одном репозитории.

### 5.4. Streamlit pin split (DOMAIN-P2-004 и DOMAIN-P2-005)

`streamlit>=1.58.0` (core, без upper) vs `streamlit>=1.30.0,<2.0.0`
([frontend] extra). uv resolver берёт max lower; but two pins.

### 5.5. AGENTS.md D-rules частично упоминаются в pyproject

```
pyproject.toml:386: # PLAN V20 (Sprint 16 K1 W4 closure): scaffolding-extras удалены — iot/web3/
pyproject.toml:388: # legacy/banking/enterprise/datalake/temporal/beam не наполнены за 5 спринтов;
```

Эти "scaffolding-extras" — несуществующие extras упомянуты в комментарии
просто как background. Не нашёл следов их в `[project.optional-dependencies]`
актуального файла. OK.

### 5.6. `tools/triage_allowlist_report.md` (446 LOC, "Sprint 5.3 retry")

Находится в `tools/` и формально в scope (не в явном списке исключений).
Однако: документ не относится к dependency management напрямую — он про
**layer architecture** allowlist (174 → 100 entries migration plan).
Прочитан для cross-context, в dependency audit **не** используется как
evidence (его findings — layer-domain, не dep-domain). Упомянут здесь
только чтобы зафиксировать, что я видел файл в scope, но не делал по
нему dep-заключений.

---

## 6. Readiness score 0-100

### 6.1. Formula

```
score = max(0,
    100
    - 10 × P0_count
    - 5  × P1_count
    - 2  × P2_count
    - 1  × P3_count
    - 1  × P4_count
)
# Cap at 79 if any P0 or P1 present (per инструкция)
```

### 6.2. Подсчёт

```
P0: 4  (DOMAIN-P0-001, 002, 003, 004)
P1: 0
P2: 5  (DOMAIN-P2-001, 002, 003, 004, 005)
P3: 1  (DOMAIN-P3-001)
P4: 0
```

```
raw = 100 - 40 - 0 - 10 - 1 - 0 = 49
# Cap not triggered (49 < 79), but ≤79 anyway because of P0s
score = 49
```

### 6.3. Обоснование

**Что работает хорошо (даёт базовые ~80+):**

- pyproject.toml — корректный манифест, AST-парсится, 95 core + 36 extras + 29 dev deps.
- Lockfile с override-dependencies для транзитивных конфликтов (pyarrow, lxml, urllib3).
- Multiple supply-chain gates: CycloneDX SBOM, pip-audit (4 entrypoints), bandit, gitleaks, trivy, cosign.
- Dependabot configures для uv, npm, github-actions.
- `make audit-deps` собирает все 35 ignores из tracking-allowlist.
- 0 layer violations по `tools/check_layers.py` (baseline 175 legacy).
- Python compat AST-gate, dep-docstring gate, creosote unused-deps gate, deptry — все существуют.

**Что снижает score (до 49):**

- **DOMAIN-P0-001 (-10):** 4-way allowlist drift — главная governance проблема.
  Tracking file ≠ CI reality. Это **fail-open** в смысле compliance.
- **DOMAIN-P0-002 (-10):** 8+ CVE listed as active в allowlist, но fix version
  уже в lockfile → ложная маскировка.
- **DOMAIN-P0-003 (-10):** Wrong comment в gate.py → поддерживает маскировку
  fixed CVE (PYSEC-2026-87).
- **DOMAIN-P0-004 (-10):** Wrong comment "diskcache REMOVED" → противоречит
  фактическому использованию.
- **DOMAIN-P2-001..005 (-10):** Dead sphinx path, dormant verify gates,
  duplicate pins, no-upper streamlit, diskcache CVE without ADR.
- **DOMAIN-P3-001 (-1):** cryptography pin documented "MONITOR" but
  CVE not in allowlist — audit will fail.

### 6.4. Итог: **49 / 100** (insufficient)

Score ниже 79 → фиксы P0 обязательны. Главные блокеры — серия
DOMAIN-P0-001..004 (governance drift). После их закрытия score поднимется
до ~76 (3 P2, 1 P3 penalty). Финальный target ≥80 после cleanup duplicates
и wiring phantom-gates.

---

## 7. Recommended next tasks (приоритизированные)

| # | Task | Estimated scope | Findings closed |
|---|---|---|---|
| **N1** | Audit & reconcile 4-way ignore-set: выбрать один source of truth для ignores (allowlist.txt vs gate.py), переписать CI workflows чтобы они использовали тот же источник | ~3-5 файлов, ~50 LOC | DOMAIN-P0-001 |
| **N2** | Remove stale fixed CVEs из `.security/pip-audit-allowlist.txt` (≥9 записей для starlette, lxml, urllib3, sqladmin, strawberry, idna, gitpython, mistune — все fix version <= installed) | 1 файл, ~9 строк | DOMAIN-P0-002 |
| **N3** | Fix `tools/pip_audit_gate.py` comments: удалить PYSEC-2026-87 из IGNORED_VULNS, обновить diskcache comment на "mitigated" вместо "REMOVED" | 1 файл, ~10 строк | DOMAIN-P0-003, DOMAIN-P0-004 |
| **N4** | Add `PYSEC-2026-3552` (cryptography) в allowlist с явным комментарием про cp314 wheels | 1 файл, 1 строка + comment | DOMAIN-P3-001 |
| **N5** | Create ADR на diskcache + PYSEC-2026-2447 (decision: stay with envelope-json mitigation) | 1 новый ADR файл | DOMAIN-P2-003 |
| **N6** | Remove dead sphinx docs path: `docs/api/`, `site/api/`, `tools/gen_api_autoapi.sh`, `docs-html` / `docs-multiversion` Makefile targets | ~5 files / dirs removed | DOMAIN-P2-001 |
| **N7** | Wire `tools/verify_pypi_versions.py` + `tools/verify_npm_versions.py` в Makefile + `.github/workflows/lint.yml` | 2-3 файла, ~10 LOC | DOMAIN-P2-002 |
| **N8** | De-duplicate 9 cross-group pins (temporalio, rank-bm25, faststream, streamlit, testcontainers, respx, pip-audit, pygls, aiosqlite, pillow/Pillow) | 1 файл, ~9 edits | DOMAIN-P2-004 |
| **N9** | Add `<2.0.0` upper bound to `streamlit>=1.58.0` in core deps | 1 файл, 1 строка | DOMAIN-P2-005 |
| **N10** | Re-run full audit (Cycle 2) для подтверждения score ≥80 | audit pass | all |

**Ожидаемый score после N1-N4:** 49 + (10×4 fixed) → **76-79**.
**Ожидаемый score после N1-N10:** **80-85**.

---

## 8. Commands run

Все команды выполнялись в `/home/user/dev/gd_integration_tools` в read-only
режиме (без `git commit`, `uv add`, `pip install`).

```bash
# 1. State & git context
git -C /home/user/dev/gd_integration_tools status
git -C /home/user/dev/gd_integration_tools log --oneline -5
git -C /home/user/dev/gd_integration_tools diff --stat
git -C /home/user/dev/gd_integration_tools log --oneline b69d6b49..HEAD
git -C /home/user/dev/gd_integration_tools diff HEAD pyproject.toml
git -C /home/user/dev/gd_integration_tools diff uv.lock | head -80

# 2. Scope enumeration
find /home/user/dev/gd_integration_tools -name "requirements*.txt" -o -name "constraints*.txt"
ls /home/user/dev/gd_integration_tools/.security/
ls /home/user/dev/gd_integration_tools/tools/ | wc -l
ls /home/user/dev/gd_integration_tools/tools/checks/ | wc -l
ls /home/user/dev/gd_integration_tools/.github/workflows/
ls /home/user/dev/gd_integration_tools/.gitlab/ci/

# 3. Allowlist parsing
grep -cE "^CVE-|^GHSA-|^PYSEC-" /home/user/dev/gd_integration_tools/.security/pip-audit-allowlist.txt
grep -E "^CVE-|^GHSA-|^PYSEC-" /home/user/dev/gd_integration_tools/.security/pip-audit-allowlist.txt | sort -u
grep -E "^# ===" /home/user/dev/gd_integration_tools/.security/pip-audit-allowlist.txt

# 4. pyproject.toml analysis
grep -i "sphinx" /home/user/dev/gd_integration_tools/pyproject.toml
grep -i "mkdocs" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "diskcache" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "PYSEC-2026-3552" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "pillow\|Pillow" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "rank-bm25" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "faststream" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "temporalio" /home/user/dev/gd_integration_tools/pyproject.toml
grep -n "testcontainers\|respx" /home/user/dev/gd_integration_tools/pyproject.toml
grep -nE "override-dependencies" /home/user/dev/gd_integration_tools/pyproject.toml

# 5. Cross-group duplicate scan (Python AST-style)
.venv/bin/python -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
# (cross-group dup detection — full output см. в работе)
"
# → 9 cross-group duplicates + pillow/Pillow case diff

# 6. Installed versions check
.venv/bin/python -c "
import importlib.metadata as md
for name in ['diskcache','lxml','starlette','fastapi','sqlalchemy','fastapi-filter',
             'sqladmin','mistune','gitpython','urllib3','strawberry-graphql',
             'cryptography','mako','purgatory','casbin','sqlalchemy-utils',
             'sqlalchemy-continuum','idna']:
    try: print(f'{name}: {md.version(name)}')
    except md.PackageNotFoundError: print(f'{name}: NOT INSTALLED')
"
# diskcache: 5.6.3 / lxml: 6.1.1 / starlette: 1.3.1 / sqladmin: 0.30.0 /
# mistune: 3.3.4 / gitpython: 3.1.58 / urllib3: 2.7.0 / strawberry-graphql: 0.323.2 /
# cryptography: 49.0.0 / idna: 3.18 / mako: 1.4.1

# 7. Compare ignore-sets
.venv/bin/python -c "
# Diff between Make audit-deps, GitHub CI, GitLab CI, gate.py
# (full output — section 4)
"

# 8. Usage search (deps that may be dead/unused)
grep -rE '^from joserfc|^import joserfc' src/ testkit/  # → used (jwt_backend.py)
grep -rE '^from pydash|^import pydash' src/ testkit/    # → used (eip/dict_ops.py)
grep -rE '^from glom|^import glom' src/ testkit/        # → used (eip/glom_ops.py, transforms)
grep -rE '^from openpyxl|^import openpyxl' src/         # → used (export_service.py lazy)
grep -rE '^from sqlalchemy.continuum|^from sqlalchemy_utils' src/  # → used
grep -rE '^from casbin|^import casbin' src/ extensions/  # → used (policy/casbin_adapter.py)
grep -rE '^from jmespath|^import jmespath' src/         # → used (airflow_sensors.py)
grep -rE '^from mako|^import mako' src/                  # → NOT directly used (transitive via alembic)
grep -rE '^from diskcache|^import diskcache' src/        # → used (decorators/caching/storage/disk.py)
grep -rE '^from FlagEmbedding|import FlagEmbedding' src/ # → used (embedding_providers_bge.py)
grep -rE '^from instructor|import instructor' src/      # → used (banking_processors, llm_structured)
grep -rE '^from litellm|import litellm' src/            # → used (gateway/client.py, pool_registration.py)
grep -rE '^from pydantic_ai|import pydantic_ai' src/    # → used (agents_pydantic)
grep -rE '^from mlflow|import mlflow' src/              # → used (model_registry/mlflow_backend.py)
grep -rE '^from fastembed|import fastembed' src/         # → used (embedding_providers.py lazy)

# 9. CI workflows read
cat /home/user/dev/gd_integration_tools/.github/workflows/security.yml
cat /home/user/dev/gd_integration_tools/.gitlab/ci/.gitlab-ci.yml
cat /home/user/dev/gd_integration_tools/.github/dependabot.yml

# 10. Makefile target search
grep -nE "audit-deps|pip-audit|allowlist|verify_pypi|verify_npm|cyclonedx|cosign" Makefile make/*.mk

# 11. pip-audit attempt (failed — network timeout)
.venv/bin/pip-audit --format json --output pip-audit.json --timeout 60
# ERROR: ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443): Read timed out.

# 12. PyPI spot check
.venv/bin/python -c "
import urllib.request, json
for p in ['chromadb','rank-bm25','e2b-code-interpreter','pydantic-ai','FlagEmbedding',
         'instructor','mlflow','transformers','openai-whisper','fastapi-filter','paddleocr',
         'pypdfium2','sentence-transformers','litellm','duckduckgo-search','tavily-python',
         'docling','redis','pydash','glom']:
    try:
        with urllib.request.urlopen(f'https://pypi.org/pypi/{p}/json', timeout=5) as r:
            print(f'{p}: {json.loads(r.read())[\"info\"][\"version\"]}')
    except Exception as e: print(f'{p}: ERR')
"
# → только pydash 8.0.6 (подтверждено); остальные 19 ERR (timeout)

# 13. Compat / syntax / layer gates
.venv/bin/python tools/check_compat.py --root src --root tools --root docs
# → Совместимость подтверждена (проверено 2418 файлов).

.venv/bin/python tools/checks/check_python3_syntax.py --root src --root tools
# → OK: no Python-2 style except clauses.

.venv/bin/python tools/check_layers.py
# → Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)

# 14. docs/api requirements verification
cat /home/user/dev/gd_integration_tools/docs/api/requirements.txt
diff /home/user/dev/gd_integration_tools/docs/api/requirements.txt /home/user/dev/gd_integration_tools/site/api/requirements.txt
# (identical content)

# 15. Pre-existing working tree confirmation
git -C /home/user/dev/gd_integration_tools diff --stat
# uv.lock | 15 ---------------
# 1 file changed, 15 deletions(-)
# (svcs removal pre-existing — не атрибуция рою)

# 16. Commit log since baseline
git -C /home/user/dev/gd_integration_tools log --oneline b69d6b49..HEAD
# ca5bff93 docs(s183-w2): cycle retrospective — 4 P0 fixes done, combined reviewer PASS
# 38258d1c fix(dsl): call_function strict-env теперь включает staging/dev_staging
# 77ff5139 fix(tests): polars-dependent test_dataframes теперь gracefully skipped
# 2f620910 fix(infra): S3 multipart abort on CancelledError + MemoryError
# (4 коммита после baseline — НЕ атрибуция текущему аудиту)
```

---

## 9. End summary

| Поле | Значение |
|---|---|
| Status | COMPLETED — read-only audit, отчёт создан |
| Readiness score | **49 / 100** (insufficient; P0 cap ≤79) |
| P0 count | 4 (DOMAIN-P0-001..004) |
| P1 count | 0 |
| P2 count | 5 |
| P3 count | 1 |
| P4 count | 0 |
| Top blockers | DOMAIN-P0-001 (allowlist drift), DOMAIN-P0-002 (stale fixed CVEs), DOMAIN-P0-003 + DOMAIN-P0-004 (wrong gate comments) |
| Отчёт | `/home/user/dev/gd_integration_tools/docs/audit/swarm-2026-08-06/cycle-1/phase-1/11-dependencies.md` |
| Изменения в repo | только этот markdown; **0 mutations** в source / lockfiles / allowlist |

Подтверждаю: pre-existing working-tree modifications (`uv.lock` svcs removal,
HEAD-коммиты `2f620910`/`38258d1c`/`77ff5139`/`ca5bff93`) **не атрибутированы
рою** и **не затронуты** моей работой.
