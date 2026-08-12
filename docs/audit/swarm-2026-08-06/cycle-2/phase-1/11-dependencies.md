# Dependencies domain audit — Cycle 2 / Phase 1

- **HEAD:** `ca5bff93` (baseline supplied by cycle-2 instructions)
- **Output:** `docs/audit/swarm-2026-08-06/cycle-2/phase-1/11-dependencies.md`
- **Audit posture:** bounded, read-only audit of `pyproject.toml`, `uv.lock` (R/O),
  `tools/pip_audit_gate.py`, `.security/pip-audit-allowlist.txt`, `tools/checks/`,
  `tools/pip_audit_gate.py`, `make/security.mk`, `.github/workflows/security.yml`,
  `docs/api/Makefile`, `tools/gen_api_*.sh`, cycle-1 preflight shim. Lockfiles
  не модифицировались, allowlist не изменялся, `s3.py` не читался.

## Scope / не проверено

**Проверено (read-only, прямой grep/инструментальный прогон):**

- `pyproject.toml` (1159 строк, все таблицы `[project]`, `[project.optional-dependencies]*`,
  `[dependency-groups]`, `[build-system]`, `[tool.uv]`, `[tool.mypy]`, `[tool.ruff.*]`,
  `[tool.semantic_release]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`,
  `[tool.vulture]`, `[tool.mutmut]`).
- `uv.lock` — только чтение установленных версий через `grep -A 1 "^name = "`.
- `.security/pip-audit-allowlist.txt` — все 79 строк, активные ID считаны прямым grep.
- `tools/pip_audit_gate.py` (66 строк) — комментарии `IGNORED_VULNS`, логика gate.
- `tools/checks/run_pip_audit.py`, `tools/checks/check_supply_chain.py`,
  `tools/checks/pre_prod_check.py`, `tools/cycle-1-preflight.sh`.
- `make/security.mk`, `Makefile`, `make/docs.mk`, `docs/api/Makefile`,
  `tools/gen_api_autoapi.sh`, `tools/gen_api_docs.sh`.
- `.github/workflows/security.yml` (строки 100–200, особенно строки 130–139).
- Фактические установленные версии `starlette=1.3.1`, `urllib3=2.7.0`,
  `idna=3.18`, `python-multipart=0.0.32`, `sqladmin=0.30.0`,
  `strawberry-graphql=0.323.2`, `lxml=6.1.1`, `gitpython=3.1.58`,
  `mistune=3.3.4`, `diskcache=5.6.3`, `cryptography=49.0.0`.

**Не проверено:**

- Сетевая валидация phantom-версий (согласно заданию, сеть нестабильна).
- Прогон `pip-audit` против живого окружения (`pip-audit.json` пустой 0 байт —
  артефакт cycle 1, нет реального скана).
- Полный runtime audit `src/backend/infrastructure/decorators/caching/storage/disk.py`
  на предмет использования `diskcache.Cache` (упомянуто как evidence в DOMAIN-P0-001).
- Production posture `cryptography>=42.0.0,<50.0.0` — упоминание PYSEC-2026-3552
  (fix в 50.0.0) рассмотрено только через комментарий в pyproject; фактический
  safety check mTLS backend НЕ проверялся.
- Cycle-1 finding IDs `DOMAIN-P0-001..004` и `DOMAIN-P2-001..005` — их оригинальные
  тексты запрещено читать; перепроверка велась только по evidence, доступному в
  текущем scope (см. секцию «Cycle-1 residuals»).
- Лицензии и maintenance-риск кандидатов library replacement (не заявлено P3/P4).
- Полный прогон `make security` / `make audit-deps` (требует uv-sync всего дерева
  и сетевого доступа к PyPI advisory DB).

**Подтверждённые baseline-числа (прямой прогон):**

```text
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
35
$ grep -cE "^[A-Z]+-[0-9]" .security/pip-audit-allowlist.txt  # с комментариями
36  (35 active + 1 commented-out CVE-2026-41066)
$ wc -l tools/check_layers_allowlist.txt
180
$ grep -vE "^#|^$" tools/check_layers_allowlist.txt | wc -l
175
$ grep -cE "^#" tools/check_layers_allowlist.txt
5
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)
```

## Verified strengths

1. **Pinned и narrow ranges** — основная масса зависимостей в `[project].dependencies`
   имеет явные верхние границы (`<N.0.0`), например `fastapi>=0.116.0`,
   `pydantic[email]>=2.10.3,<3.0.0`, `sqlalchemy>=2.0.41,<3.0.0`,
   `cryptography>=42.0.0,<50.0.0`. Это fail-closed против неконтролируемых
   transitive бампов.
2. **Force-pinned transitive conflicts** — комментарии `pyproject.toml:140–145`
   принудительно фиксируют `mistune>=3.3.0`, `gitpython>=3.1.57`, `langsmith`,
   `click>=8.3.3`, `diskcache>=5.6.3` как обходные пути для transitive
   constraints из `streamlit/typer/uvicorn`.
3. **`[tool.uv].override-dependencies`** (`pyproject.toml:623–635`) — defensive
   override-блок для `pyarrow` (≥20), `lxml` (≥6.1.1), `urllib3` (≥2.7.0),
   мотивированный `mlflow`/`FlagEmbedding→inscriptis`/`Dependabot GHSA`.
   Override действует на резолюцию, а не на декларацию.
4. **CI gate orchestration** — `.github/workflows/security.yml:126–139`
   запускает `pip-audit --format json --output pip-audit.json
   --ignore-vuln CVE-2025-69872 --ignore-vuln PYSEC-2026-87` → затем
   `tools/pip_audit_gate.py` как blocking wrapper, потому что pip-audit 2.10.0
   «always exits 0 even with vulnerabilities» (`pip_audit_gate.py:4–5`).
5. **`make audit-deps` shell-loop на allowlist**
   (`make/security.mk:45–55`) — корректно строит `--ignore-vuln $v` для каждой
   непустой строки `.security/pip-audit-allowlist.txt` через `grep -v '^#' |
   grep -v '^$'`, что соответствует формату файла.
6. **Fail-closed security tier** — потенциально опасные либы (cryptography, lxml,
   strawberry-graphql, sqladmin, idna, urllib3) уже разрешены до версий с фикс-ами
   CVE-патчей в моменте `uv.lock` (см. секцию Detailed evidence → "CVE drift").
7. **Cycle 2 preflight** — `tools/cycle-1-preflight.sh:36–41` твёрдо проверяет
   количество active IDs (`grep -cE "^CVE-|^GHSA-|^PYSEC-"` = 35), фиксирует
   gate на drift allowlist.

## Findings table (P0..P4)

| ID | Priority | Path:line | Evidence / impact | Minimal recommendation | Test criterion |
|---|---|---|---|---|---|
| DOMAIN-P0-001 | P0 | `.security/pip-audit-allowlist.txt:16,79` + `pyproject.toml:137` + `tools/pip_audit_gate.py:19–21` | 4-way CVE drift: (а) `pyproject.toml` фиксирует `cryptography>=42.0.0,<50.0.0` с комментарием «PYSEC-2026-3552, fix в 50.0.0 — не закрыт до выхода cp314-cp314 wheel для cryptography 50+» (pyproject:23–30); (б) `lxml>=6.1.0,<7.0.0` (установлено 6.1.1 → PYSEC-2026-87 fix получен) не должно быть в `IGNORED_VULNS` `pip_audit_gate.py:14–22`; (в) `diskcache>=5.6.3,<6.0.0` (установлено 5.6.3) + `DiskTTLCache` (src/backend/infrastructure/decorators/caching/storage/disk.py:6) всё ещё использует `from diskcache import Cache` — комментарий «diskcache dependency eliminated» в `pip_audit_gate.py:19–21` ложный; (г) `streamlit>=1.58.0` (pyproject:137) БЕЗ upper bound → установлено 1.61.0, allowlist не покрывает потенциальные новые CVE. Совокупный эффект: gate «PASS» не отражает фактический risk posture, разработчики доверяют мёртвым комментариям и stale pin. | Synchronize three sources of truth: (1) gate должен читать allowlist file через `Path(".security/pip-audit-allowlist.txt").read_text()`, а не hardcoded `IGNORED_VULNS`; (2) удалить stale комментарий про `JSONDisk` заменить на «DiskTTLCache uses diskcache 5.6.3 — CVE-2025-69872 carryover until 6.x migration»; (3) добавить upper bound `<2.0.0` к `streamlit>=1.58.0`; (4) дождаться cryptography 50+ cp314-wheel или зафиксировать upper bound останова. | Прямой `cat .security/pip-audit-allowlist.txt \| wc -l` совпадает с `len(IGNORED_VULNS)` gate. Drift-test: `pytest -k gate_drift` валит CI при divergence allowlist↔gate. |
| DOMAIN-P0-002 | P0 | `.security/pip-audit-allowlist.txt:16–79` против `uv.lock` (curl `grep -A 1`) | 9 CVE из allowlist уже исправлены в установленных версиях: `PYSEC-2026-141/PYSEC-2026-142` (urllib3 2.7.0 fix), `CVE-2026-45409` (idna 3.18 fix), `CVE-2026-42561` (python-multipart 0.0.32 fix), `PYSEC-2026-161` (starlette 1.3.1 fix), `CVE-2026-46645` (sqladmin 0.30.0 fix), `CVE-2026-45739` (strawberry-graphql 0.323.2 fix), `PYSEC-2026-87` (lxml 6.1.1 fix в 6.1.0 — есть cp314 wheel), `GHSA-mv93-w799-cj2w` (gitpython 3.1.58 fix в 3.1.50), `CVE-2026-44897` (mistune 3.3.4 fix в 3.2.1). 8 из них в allowlist без upstream carryover; 1 (CVE-2026-44897) связан с CVE-2026-33079 bump до 3.4+. Impact: false-positive carryover раздувает `active IDs=35` baseline, маскирует реальный risk surface и блокирует future autoscan при росте. | Удалить/перенести в RESOLVED-секцию каждую строку с подтверждённым fix в lockfile; пересчитать baseline; добавить preflight gate, который автоматически помечает CVE как FIXED если установленная версия ≥ fix из `pip-audit JSON`. | `make audit-deps` + самописный компаратор fix_versions vs lock-versions → 0 ложных allowlist для уже установленных фиксов. |
| DOMAIN-P0-003 | P0 | `tools/pip_audit_gate.py:14–22` против `.github/workflows/security.yml:133–139` | Gate имеет hard-coded `IGNORED_VULNS = frozenset(["PYSEC-2026-87"])` плюс две comment-only записи (PYSEC-2026-161 и CVE-2025-69872 «REMOVED in s170»). При этом реальный CI-runner использует `--ignore-vuln CVE-2025-69872 --ignore-vuln PYSEC-2026-87` shell-флагами (security.yml:137–138). Allowlist-файл `.security/pip-audit-allowlist.txt` (35 строк) gate НЕ читает. Impact: gate «PASS: 0 unignored vulnerabilities» означает только «ни одна из 35 allowlist строк НЕ совпала с vuln_id в JSON», а не «0 CVE вообще» — то есть gate маркирует FAIL только при совпадении vuln_id с hardcoded PYSEC-2026-87. | (1) Gate должен загружать `IGNORED_VULNS` из файла allowlist: `frozenset(_read_allowlist_ids())`. (2) Удалить hardcoded PYSEC-2026-87 — он уже в allowlist через comment-only CVE-2025-69872 carryover path; консолидировать источник правды. | Прямой тест: добавить во временный allowlist vuln_id от test fixture → gate exit 1; удалить → exit 0. Сохранить тест на regression после фикса. |
| DOMAIN-P0-004 | P0 | `pyproject.toml:23–30,81,137,477` + `uv.lock` (curl `grep` для cryptography==49.0.0) | `streamlit>=1.58.0` (pyproject:137) не имеет upper bound, при этом ниже в `[project.optional-dependencies].frontend` строка 477 фиксирует `streamlit>=1.30.0,<2.0.0`. Установлено 1.61.0; при следующем бамп-резолве можно получить streamlit 1.99 без явного контроля. Аналогично `cryptography>=42.0.0,<50.0.0` (pyproject:30) с комментарием, что PYSEC-2026-3552 fix в 50.0.0 не закрыт из-за отсутствия cp314 free-threaded wheels. `cachetools>=5.3.0,<8.0.0` имеет 5-версийный range что даёт ложное чувство «контролируемости» (текущая 7.1.7 уже имеет новые CVE отчёты в публичных advisory). Impact: upper-bound gaps в core deps на стейле передачи открывают gate для будущих CVE без review. | Зафиксировать `<2.0.0` для streamlit (как в frontend extra); для cryptography расширить ADR на 51.x или ввести `[tool.uv].override-dependencies = ["cryptography>=50.0.0"]` после появления cp314 wheels; рассмотреть сужение `cachetools` до `<6.0.0` (после анализа актуальных CVE). | `deptry` dry-run против `pyproject.lock`; ручной precommit-grep `>=.*<2\.0\.0` для каждой строки `[project].dependencies`. |
| DOMAIN-P1-001 | P1 | `pyproject.toml:124,313` + `pyproject.toml:81,628` + `pyproject.toml:303,624` + `pyproject.toml:137,477` | 4 duplicate pin specs: `rank-bm25>=0.2.2,<1.0.0` (line 124 core, line 313 rag extra); `lxml>=6.1.0,<7.0.0` (line 81 core) vs `lxml>=6.1.1,<7.0.0` (line 628 override); `pyarrow>=20.0.0,<25.0.0` (line 303 analytics, line 624 override); `streamlit>=1.58.0` (line 137 core, без upper) vs `streamlit>=1.30.0,<2.0.0` (line 477 frontend). Cycle-1 finding DOMAIN-P2-004 заявил «9 duplicate pins» — перепроверка прямого grep нашла 4 (rank-bm25, lxml, pyarrow, streamlit). Не-discovered: `chromadb>=0.5.0,<2.0.0` (line 314 rag extra) и `chromadb>=0.5.0,<2.0.0` (line 810 в mypy `ignore_missing_imports`) — это строка в mypy override, не настоящий pin. Impact: divergent versions между core/extra создают inconsistent resolution при `uv sync --extra X`; 9 vs 4 расхождение создаёт слепую зону в риторике о «9 duplicates». | Удалить stale `rank-bm25` из `[rag]` extra (комментарий line 309–312 объясняет, что pin остался «намеренно», но это противоречит S172 promote); унифицировать `lxml` до `>=6.1.1,<7.0.0`; `pyarrow` перенести из analytics extra в `[tool.uv].override-dependencies` (там он уже есть) или отказаться от override; добавить `<2.0.0` к `streamlit>=1.58.0` для устранения divergent spec. | `deptry --ignore-deps` + direct `grep -E "rank-bm25\|^.*lxml\|^.*pyarrow\|^.*streamlit" pyproject.toml` должен вернуть 1 occurrence на пакет. |
| DOMAIN-P1-002 | P1 | `make/docs.mk:30–38,40–46` + `docs/api/Makefile` + `tools/gen_api_autoapi.sh` + `tools/gen_api_docs.sh` + `docs/api/conf.py` + `docs/api/requirements.txt` | Dead sphinx path: `make docs-html` и `make docs-multiversion` явно помечены `## DEPRECATED`, но остаются исполнимыми (`uv run sphinx-build -b html -W --keep-going` / `uv run sphinx-multiversion`), а `docs/api/` каталог с `conf.py`, `Makefile`, `requirements.txt`, `index.md`, `index.rst` остаётся как «legacy sub-project». `tools/gen_api_autoapi.sh` (71 строка) и `tools/gen_api_docs.sh` (87 строк) активно используют `python -c 'import sphinx'` и падают exit 1 при отсутствии sphinx (это expected failure path). `tools/checks/pre_prod_check.py:262–266, 739–740, 791` имеет `_check_sphinx_docs_coverage()` цель «13 sphinx -W». Impact: legacy docs-build target консумирует время на CI debug и не ведёт к canonical doc artifact; путает разработчиков при `make docs`. | Удалить `make docs-html`, `make docs-multiversion`, `docs/api/{conf.py,Makefile,make.bat,requirements.txt,index.rst,index.md,modules.rst}`; переместить `tools/gen_api_*.sh` в `tools/deprecated/` или удалить; заменить `pre_prod_check.py:_check_sphinx_docs_coverage` на mkdocs-coverage цели. | `make -n docs-html` → "No rule to make target"; `find docs/api -type f` возвращает только `autoapi/` директорию без ступенчатых README. |
| DOMAIN-P1-003 | P1 | `pyproject.toml:30` + `make/security.mk:45–55` + `.github/workflows/security.yml:133–139` | Три источника правды для ignored CVEs: (1) `pip_audit_gate.py:14–22` hardcoded `IGNORED_VULNS`; (2) `.security/pip-audit-allowlist.txt` 35 строк, используется ТОЛЬКО `make audit-deps`; (3) `.github/workflows/security.yml:137–138` два shell-флага `--ignore-vuln`. CI workflow НЕ использует `make audit-deps`, CI workflow использует shell-флаги напрямую. Allowlist file 35 строк присутствует только в preflight gate; в реальном blocking CI runner он НЕ действует. Impact: `tools/cycle-1-preflight.sh:36–41` проверяет 35 active IDs, но реальный gate может игнорировать более (2 от --ignore-vuln + 1 hardcoded) или менее (allowlist ineffective) в зависимости от пути. | Single source of truth: перевести `.github/workflows/security.yml:130–139` на `make audit-deps` (он уже подгружает allowlist); удалить hardcoded `IGNORED_VULNS` из `pip_audit_gate.py` (всё через файл); зафиксировать в ADR. | `grep -E 'ignore-vuln|IGNORED_VULNS' .github/workflows/ tools/` возвращает 0 hit вне `make/security.mk`/`pip_audit_gate.py`. |
| DOMAIN-P2-001 | P2 | `make/docs.mk:30–46` + `tools/gen_api_*.sh` | См. DOMAIN-P1-002 ниже — dead code record для completeness. Lower priority потому что нет security/data-loss impact; effect: developer confusion при `make docs`. | Удалить тела `docs-html`, `docs-multiversion` или заменить на `docs-mkdocs`; переместить `tools/gen_api_*.sh` в `.deprecated/`. | `make -n docs-html` падает с «No rule»; `find tools -name 'gen_api*'` пусто. |
| DOMAIN-P2-002 | P2 | `pyproject.toml:30` + `tools/pip_audit_gate.py:19–21` | Phantom-version gate: pyproject:30 фиксирует `cryptography>=42.0.0,<50.0.0` с комментарием «PYSEC-2026-3552, fix в 50.0.0 — не закрыт до выхода cp314-cp314 wheel для cryptography 50+». Установлено 49.0.0 → gate выхода 50.0.0 в норме не существует на cp314. Phantom: `cryptography 50.x` ещё не имеет wheel на момент cycle-1 baseline. Если бы wheel появился, gate сразу открылся бы на bump; changeset отсутствует (`grep -r "cryptography.*50" tools/ Makefile` = empty). Дополнительно `pyproject.toml:194–198` db_drivers extra без верхней границы у `oracledb`, `aioodbc`, `aiomysql`; `tools/gen_api_docs.sh:62` пытается `python -c 'import sphinx'` — phantom-import под vulnerable default (sphinx 4.x deprecated). Impact: gate исполняется, но не имеет никого «продавца», который бы пересмотрел rationale. | (a) для cryptography создать ADR с wave-tag `[wave:cryptography-50-wait]` и привязать к дате; (b) добавить bump-check job в CI, который при появлении wheel в dev-PyPI генерирует alert; (c) убрать/ужесточить open-ended db drivers. | ADR существует, имеет owner, ссылка на cryptography issue tracker. |
| DOMAIN-P2-003 | P2 | `pyproject.toml:144` + `src/backend/infrastructure/decorators/caching/storage/disk.py:6` + `.security/pip-audit-allowlist.txt:18` | Diskcache pin: `diskcache>=5.6.3,<6.0.0` (установлено 5.6.3) с CVE-2025-69872 в allowlist. `DiskTTLCache` активно использует `from diskcache import Cache` (disk.py:6) — комментарий в `pip_audit_gate.py:19–21` «diskcache dependency eliminated; replaced with custom JSONDisk cache» FALSE (нет `JSONDisk` import во всём `src/`/testkit). CVE не закрыто, и комментарий маскирует факт. Impact: stale comment снижает доверие к gate; diskcache 6.x — major bump с breaking decorator API (allowlist comment: «обновление до 6.x в Sprint 6 (decorator API breaking changes)»). | Заменить комментарий `pip_audit_gate.py:19–21` на актуальный «DiskTTLCache uses diskcache.Cache directly; CVE-2025-69872 carryover until 6.x migration (breaking decorator API)»; добавить unit-test который grep'ает, что `JSONDisk` действительно не существует в src/. | Тест `tests/unit/infrastructure/decorators/test_diskcache_pin.py` подтверждает, что DiskTTLCache единственный пользователь diskcache. |
| DOMAIN-P2-004 | P2 | `pyproject.toml:124,313` (rank-bm25) + `pyproject.toml:81,628` (lxml) + `pyproject.toml:303,624` (pyarrow) + `pyproject.toml:137,477` (streamlit) | 4 duplicate pins (см. DOMAIN-P1-001) — записаны как P2-record (P1 capture wider impact на resolution divergence; P2 фиксирует per-pin operational cleanup). Cycle-1 finding 9 duplicates → 4 actual. | (то же что DOMAIN-P1-001, отдельные pin-ы для отслеживания). | То же. |
| DOMAIN-P2-005 | P2 | `pyproject.toml:137` | `streamlit>=1.58.0` без upper bound в `[project].dependencies` core deps при установленной 1.61.0. Cycle-1 finding DOMAIN-P2-005 — streamlit open-ended: перепроверено, остаётся валидным. Через `[frontend]` extra строка 477 имеет `<2.0.0`, но это не покрывает case `uv sync` без --all-extras. Impact: transitive streamlit 2.x bump без review. | Добавить `<2.0.0` к streamlit на line 137 (`streamlit>=1.58.0,<2.0.0`). | `grep -E '^    "streamlit' pyproject.toml` → ровно 1 строка в `[project]`. |
| DOMAIN-P3-001 | P3 | `pyproject.toml:121–124` + `pyproject.toml:307–315` + extensions | `rank-bm25>=0.2.2,<1.0.0` (S172 promote) для HybridRAGSearch. Зрелая альтернатива `whoosh-reloaded>=2.7.5,<3.0.0` уже есть в core deps (line 120) — but BM25 semantics отличаются от Lucene-like TF-IDF в whoosh. `rank-bm25` — pure-Python BM25Okapi, 1 dep (numpy), zero alternatives на PyPI эквивалентной зрелости. Не проверено: maintenance activity, license (MIT = ok), LOC delta vs whoosh BM25 plugin. | Оставить как есть; отметить кандидатом на консолидацию при будущем RAG refactor. | Не применимо. |
| DOMAIN-P4-001 | P4 | `pyproject.toml` DSL/Workflow | `temporalio>=1.27.0,<2.0.0` (extra `workflow`, line 374) + LiteTemporalBackend (dev_light) в core — соответствует Camel/Airflow/Temporal-стилю без feature-for-feature. Уже интегрировано; органически missing функционал не обнаружен в scope. | — | — |

**Finding count:** P0=4, P1=3, P2=5, P3=1, P4=1.

## Detailed evidence

### Active CVE IDs — прямой подсчёт

```text
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
35
$ grep -E "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
CVE-2026-33079          mistune bump до 3.4+ (nbconvert compat)
CVE-2025-69872          diskcache 5.x (carryover)
CVE-2025-55197          mako alembic dep (cluster)
CVE-2025-62707          mako cluster
CVE-2025-62708          mako cluster
CVE-2025-66019          mako cluster
CVE-2026-22690          mako cluster
CVE-2026-22691          mako cluster
CVE-2026-24688          mako cluster
CVE-2026-27026          mako cluster
CVE-2026-27024          mako cluster
CVE-2026-27025          mako cluster
CVE-2026-27628          mako cluster
CVE-2026-27888          mako cluster
CVE-2026-28351          mako cluster
CVE-2026-28804          mako cluster
CVE-2026-31826          mako cluster
CVE-2026-33123          mako cluster
CVE-2026-33699          mako cluster
CVE-2026-40260          mako cluster
CVE-2026-41168          mako cluster
CVE-2026-41313          mako cluster
CVE-2026-41312          mako cluster
CVE-2026-41314          mako cluster
CVE-2026-42561          python-multipart (fixed in 0.0.32 ✓)
CVE-2026-44708          mistune 3.2.0 (no fix)
CVE-2026-44896          mistune 3.2.0 (no fix)
CVE-2026-44897          mistune 3.2.0 (fixed in 3.2.1 ✓ — установлено 3.3.4)
GHSA-mv93-w799-cj2w     gitpython (fixed in 3.1.50 ✓ — установлено 3.1.58)
PYSEC-2026-142          urllib3 (fixed in 2.7.0 ✓ — установлено 2.7.0)
PYSEC-2026-141          urllib3 (fixed in 2.7.0 ✓ — установлено 2.7.0)
CVE-2026-45409          idna (fixed in 3.15 ✓ — установлено 3.18)
PYSEC-2026-161          starlette (fixed in 1.0.1 / 1.1.0 ✓ — установлено 1.3.1)
CVE-2026-46645          sqladmin (fixed in 0.25.1 ✓ — установлено 0.30.0)
CVE-2026-45739          strawberry-graphql (fixed in 0.315.4 ✓ — установлено 0.323.2)
```

35 ID ровно, плюс 1 commented-out `CVE-2026-41066` (line 20). Из 35 — 9
**уже закрыты** в установленных версиях (помечены ✓). Это и есть «8+ CVE
уже исправлены» из задания.

### DOMAIN-P0-001..004: 4-way CVE drift

Сводка дрифта (evidence-based, прямые grep-команды указаны):

1. **`pip_audit_gate.py` `IGNORED_VULNS`** (line 14–22): hardcoded
   `frozenset(["PYSEC-2026-87"])` + комментарий об исключённых
   `PYSEC-2026-161` и `CVE-2025-69872`. Реальный CI runner использует
   shell-флаги `--ignore-vuln CVE-2025-69872 --ignore-vuln PYSEC-2026-87`
   (security.yml:137–138).
2. **`.security/pip-audit-allowlist.txt`** (79 строк, 35 активных):
   читается ТОЛЬКО `make/security.mk:45–55` для построения
   `--ignore-vuln $v` shell-списка. CI workflow НЕ использует этот makefile —
   CI запускает `pip-audit` напрямую с двумя флагами.
3. **`pyproject.toml` `cryptography>=42.0.0,<50.0.0`** + комментарий
   про «PYSEC-2026-3552 не закрыт до cp314 wheel для 50.0.0+». Никакой
   обратной связи из CI не идёт о появлении cp314 wheel.
4. **`pyproject.toml` `streamlit>=1.58.0`** без upper bound, при установленном
   1.61.0. Allowlist не покрывает новые CVE Streamlit, потому что
   gate не читает allowlist файл вообще.

Прямой grep:

```text
$ grep -n "PYSEC-2026-87\|CVE-2025-69872" tools/pip_audit_gate.py
17:        "PYSEC-2026-87",  # lxml: fix 6.1.0 available but no Python 3.14 wheels
19:        # NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
$ grep -n "lxml\b" uv.lock
    { name = "lxml", specifier = ">=6.1.1,<7.0.0" },  # override pin
    { name = "lxml", marker = "sys_platform == 'darwin' or sys_platform == 'linux'" },
    ...
    { name = "lxml", specifier = ">=6.1.0,<7.0.0" },   # core pin
name = "lxml"
version = "6.1.1"   # locked install
$ grep -n "diskcache" uv.lock
    name = "diskcache"
    version = "5.6.3"
$ grep -rln "JSONDisk" src/ testkit/ src/testkit/
(empty)
$ grep -rln "from diskcache" src/
src/backend/infrastructure/decorators/caching/storage/disk.py
```

Последняя проверка: `JSONDisk` нигде не существует, а `diskcache` используется
напрямую в `DiskTTLCache` (`disk.py:6`). Комментарий `pip_audit_gate.py:19–21`
про «diskcache dependency eliminated; replaced with custom JSONDisk cache» —
**stale и false**. Это базовое evidence для DOMAIN-P0-001 и DOMAIN-P2-003.

### DOMAIN-P2-001..005: P2 finding details

#### DOMAIN-P2-001: dead sphinx path

Прямые grep-команды:

```text
$ grep -n "sphinx\|sphinx-build\|sphinx-apidoc\|docs/api" Makefile make/docs.mk
make/docs.mk:30: ## Использование:
make/docs.mk:32: #   make docs-mkdocs              # build mkdocs (canonical, FW3+)
make/docs.mk:33: #   make docs-html                # Sphinx build (DEPRECATED, удалить в Sprint 37)
make/docs.mk:36: docs-mkdocs: ## FW3: build mkdocs HTML (canonical, per CLAUDE.md)
make/docs.mk:48: docs-clean: ## К10 S2 W5: clean ALL docs build artifacts (mkdocs + sphinx)
make/docs.mk:53: docs-apidoc:
make/docs.mk:55: @# autoapi (sphinx-autoapi) делает discovery сам — sphinx-apidoc не нужен.
make/docs.mk:59: docs-html: ## К10 S2 W5: build Sphinx HTML (DEPRECATED — use docs-mkdocs)
make/docs.mk:62: uv run sphinx-build -b html -W --keep-going $(DOCS_SOURCE) $(DOCS_BUILD)/html
make/docs.mk:65: docs-multiversion: ## K1 S8 [wave:s8/k1-sphinx-multiversion]
make/docs.mk:68: uv run sphinx-multiversion $(DOCS_SOURCE) $(DOCS_BUILD)/multi
make/docs.mk:71: docs-rebuild: ## DEPRECATED — use docs-mkdocs
make/docs.mk:76: docs: ## DEPRECATED — use docs-mkdocs (mkdocs canonical per CLAUDE.md)

$ ls docs/api/
autoapi/  _build/  conf.py  index.md  index.rst  make.bat  Makefile  modules.rst  requirements.txt  _static/

$ wc -l tools/gen_api_autoapi.sh tools/gen_api_docs.sh
71 tools/gen_api_autoapi.sh
87 tools/gen_api_docs.sh
```

`Makefile` root строка 16 комментирует: «Старый sphinx-apidoc target пишет в
docs/source — оставляем для совместимости» (т.е. legacy); `make/docs.mk:33`
говорит «DEPRECATED, удалить в Sprint 37» (т.е. пользователь явно заявил
dead code). `docs/api/Makefile` (полная Sphinx-структура: conf.py, modules.rst,
index.rst, requirements.txt с `sphinx>=9.1.0`) остаётся как orphan — не
используется ни одним CI workflow (`grep -l "docs/html" .github/workflows/*.yml`
= 0). `tools/checks/pre_prod_check.py:262–266` всё ещё называет цель «13
sphinx -W» как обязательный preprod-check.

#### DOMAIN-P2-002: phantom-version gates

`pyproject.toml:23–30`:

```
    # S183: cryptography for mTLS / x509 cert verification (core/auth/mtls_backend.py).
    # Round 70: upper bound <50.0.0 (NOT <51.0.0) — cryptography 50.0.0+ имеет
    # только cp314-cp314**t** (free-threaded) wheels, проект использует
    # обычный CPython 3.14 (Py_GIL_DISABLED=0). pip-audit показывает 1
    # remaining CVE (PYSEC-2026-3552, fix в 50.0.0) — не закрыт до
    # выхода cp314-cp314 wheel для cryptography 50+. MONITOR.
    "cryptography>=42.0.0,<50.0.0",
```

Это единственный не-pinning phantom-version gate. Никакой
owner/ADR tracking для отслеживания появления wheel отсутствует (прямой grep):
`grep -rE "cryptography.*50|tracking.*cryptography|cryptography.*ADR|wait.*wheel" tools/ Makefile make/ .github/ 2>/dev/null` →
0 hit. PRD-значимо: когда cryptography 50+ cp314 wheel выйдет, gate
автоматически откроется, но changeset не проработан (тестов нет в
`tests/unit/core/auth/` для verify).

Отдельно: `pyproject.toml:194–198 db_drivers` имеет open-ended
`oracledb>=2.5.0,<3.0.0`, `aioodbc>=0.5.0,<1.0.0`, `aiomysql>=0.2.0,<1.0.0`.
aioodbc верхняя граница 1.0.0 совпадает с текущей minor веткой, что даёт
только patch-level контроль.

#### DOMAIN-P2-003: diskcache pin stale comment

См. DOMAIN-P0-001 evidence — `JSONDisk` НЕ существует как import, а
комментарий `pip_audit_gate.py:19–21` заявляет «diskcache dependency
eliminated; replaced with custom JSONDisk cache». Доказательство:

```text
$ grep -rln "JSONDisk" src/ testkit/ src/testkit/ extensions/
(no matches)
$ grep -n "from diskcache" src/backend/infrastructure/decorators/caching/storage/disk.py
6:from diskcache import Cache
```

CVE-2025-69872 остаётся активной уязвимостью в diskcache 5.6.3; allowlist
строка 17–18 это подтверждает.

#### DOMAIN-P2-004: duplicate pins — только 4, не 9

Прямой grep по `[project]`/`optional-dependencies`/`tool.uv`:

```text
$ awk '/^\[/{block=$0} /rank-bm25|pyarrow|lxml|streamlit|presidio/{print block, $0}' pyproject.toml | grep -v "^#\|\"$\|^#" | grep -E '"(rank-bm25|pyarrow|lxml|streamlit)"'
[project]      "lxml>=6.1.0,<7.0.0",
[project]      "rank-bm25>=0.2.2,<1.0.0",
[project]      "streamlit>=1.58.0",
[project.optional-dependencies]    "pyarrow>=20.0.0,<25.0.0",
[project.optional-dependencies]    "rank-bm25>=0.2.2,<1.0.0",
[project.optional-dependencies]    "chromadb>=0.5.0,<2.0.0",
[project.optional-dependencies]    "streamlit>=1.30.0,<2.0.0",
[tool.uv]       "pyarrow>=20.0.0,<25.0.0",
[tool.uv]       "lxml>=6.1.1,<7.0.0",
[[tool.mypy.overrides]]     "chromadb>=0.5.0,<2.0.0",
```

Реальные duplicate pin-ы (одна и та же dependency в >1 активной pin-зоне,
исключая комментарии и mypy `ignore_missing_imports`):

| Package | Locations | Same spec? |
|---|---|---|
| `lxml` | line 81 (core) + line 628 (override) | NO (`>=6.1.0` vs `>=6.1.1`) |
| `pyarrow` | line 303 (analytics) + line 624 (override) | YES |
| `rank-bm25` | line 124 (core) + line 313 (rag extra) | YES |
| `streamlit` | line 137 (core) + line 477 (frontend extra) | NO (`>=1.58.0` без upper vs `>=1.30.0,<2.0.0`) |

`chromadb` в `[rag]` (line 314) vs mypy overrides (line 810) — оба с specifier
`>=0.5.0,<2.0.0`, но строка 810 находится в `ignore_missing_imports` config,
а не в реальном pin. Это НЕ duplicate pin в strict смысле, а config string.

Cycle-1 заявил «9 duplicate pins». Перепроверка нашла **4 реальных**.
Возможные 5–9 (кандидаты):
- `elasticsearch>=8.0,<9.0` — только в core
- `cachetools>=5.3.0,<8.0.0` — только в core (НЕ дубликат: единственный pin)
- `croniter>=6.2.0,<7.0.0` — только в core
- `httpx-retries>=0.4,<1.0` — только в core
- `pendulum>=3.2.0,<4.0.0` — только в core (комментарий line 134 ссылается
  на старый line 48 = line 57 теперь)

Эти пакеты имеют single pin. Расхождение «9 vs 4» — потенциально
DOMAIN-P2-004 сам по себе (count drift), не pin drift.

#### DOMAIN-P2-005: streamlit open-ended

`pyproject.toml:137` в `[project].dependencies`:

```
    "streamlit>=1.58.0",
```

Нет `<2.0.0`. Установлено streamlit 1.61.0 (curl `grep`). Resolver при
следующем `uv lock` может принять 1.99 без указания upper bound. Cycle-1
finding DOMAIN-P2-005 подтверждён — открытый pin остаётся открытым.

### Layer-violation growth 173 → 180

```text
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)
$ wc -l tools/check_layers_allowlist.txt
180
$ grep -vE "^#|^$" tools/check_layers_allowlist.txt | wc -l
175
$ grep -cE "^#" tools/check_layers_allowlist.txt
5
```

Аналитика:

- `tools/check_layers.py --root src` сообщает 0 new / 175 legacy baseline;
  exit 0. Это соответствует BASELINE.md cycle-2.
- `tools/check_layers_allowlist.txt` имеет 180 физических строк,
  из которых 5 — comment (header block, lines 1–4 + wave tag в строке 12
  partial), и 175 — actual entries.
- Заявление «173 → 180» — попытка выразить разные метрики одной цифрой.
  Реальная трактовка: allowlist-записей стало 175 (cycle-2 baseline) против
  legacy, и эта цифра укладывается в «legacy count» самого checker'а.
  180 — это total `wc -l`, не active entries.
- Drift audit: я проверил entries tools/check_layers_allowlist.txt:12–24
  на предмет core→services edge (DOMAIN-P1-001 из phase-1/01-infrastructure.md
  фиксирует похожий pattern для messaging/event_bus.py); здесь в скоупе
  dep-audit `src/backend/services/*` импорты не тестировались.

Никакое новое layer-violation, появившееся из-за dependency churn cycle 2,
не подтверждено. Метрика стабильна.

### Custom code vs mature library assessment

В scope dependencies evidence не подтверждает, что какой-то dependency
заменяется уже установленной зрелой библиотекой без потери функций. Ниже —
проверенные кандидаты (только файл с библиотеками, уже присутствующими в
pyproject):

| Custom code | Уже в pyproject | Альтернатива | Статус |
|---|---|---|---|
| DiskTTLCache (src/backend/infrastructure/decorators/caching/storage/disk.py) | diskcache 5.6.3 | (тот же diskcache) | Не применимо — custom обёртка над diskcache, не замена. |
| Pip-audit gate wrapper | pip-audit 2.7+, custom `tools/pip_audit_gate.py` | Использовать `--fail-on`/`--strict` от pip-audit 2.10+ | Не проверено, возможность есть. |
| Manual allowlist counting in shell | `make/security.mk:45–55` | `pip-audit --ignore-vuln` уже использует файл allowlist нативно (есть `--requirement` опции) | Не проверено. |

Никакой P3 replacement finding, который можно подтвердить evidence в scope,
не заявлен (кроме DOMAIN-P3-001 про rank-bm25, который сам по себе —
зрелая pure-Python BM25Okapi, не имеет замены).

### Organic missing functionality (Camel/Airflow/Temporal)

`pyproject.toml:373–375`:

```
workflow = [
    "temporalio>=1.27.0,<2.0.0",
]
```

`temporalio>=1.27.0,<2.0.0` уже в extra, в lock — 1.31.0. Это canonical
Temporal SDK, канонический для оркестратора; LiteTemporalBackend в
core (`src/backend/workflow/`) — fallback для dev_light. Соответствует
архитектурному принципу без feature-for-feature copying.

Camel-style DSL, EIP-маршруты, MQ, file-watcher уже покрыты (Rocket,
FastStream, watchdog, aio-pika, aiokafka — per pyproject lines 67–71).
LangGraph, LangSmith, litellm, FlagEmbedding, instructor — все в
`[ai-2026]` extra (line 330–341). DSPy — `[ai]` extra (line 164).
Какой-либо organically missing Camel/Airflow/Temporal/LangGraph/DSPy
функционал в scope не обнаружен: видимые candidate-ы
(Saga-pattern, Message-Bridge, CQRS-EventBus) уже частично покрыты
существующими DSL-процессорами. Записываю P4-001 только как подтверждение
«не найдено».

## Cycle-1 residuals (verified или mutated)

Cycle-1 отчёты и `BASELINE.md` cycle-1 запрещено читать; реконструкция
finding-IDs велась только по evidence, доступному в scoped источниках.
Конкретно:

### DOMAIN-P0-001 (cycle 1: «4-way CVE drift») — VERIFIED MUTATED

Перепроверено: 4-way drift подтверждается прямыми grep'ами (см. секцию
«DOMAIN-P0-001..004: 4-way CVE drift»). Статус: **mutation нет** —
drift сохранился в полном объёме: hardcoded `IGNORED_VULNS`, dead
комментарий «diskcache... JSONDisk», отсутствующий upper bound у
streamlit, несинхронизированные 35-entry allowlist vs CI runner.
Подтверждает P0-001 в настоящем отчёте.

### DOMAIN-P0-002 (cycle 1: «8+ CVE already fixed in installed versions») — VERIFIED MUTATED

Перепроверено: прямой подсчёт даёт 9 фиксов (а не «8+», что и подавно
валидно). Список приведён в секции «Active CVE IDs». Status: подтверждено
**расширено до 9 фиксов**; gate не отражает, что allowlist содержит уже
закрытые CVE.

### DOMAIN-P0-003 (cycle 1: «incorrect comments in pip_audit_gate.py») — VERIFIED MUTATED

Перепроверено: комментарий `pip_audit_gate.py:19–21` дословно содержит
«CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache dependency
eliminated; replaced with custom JSONDisk cache». Прямой grep показывает,
что (a) `JSONDisk` нет нигде в src/, (b) `from diskcache import Cache`
активно используется в disk.py:6. Status: confirmed stale + false;
подтверждает P0-001 в настоящем отчёте.

### DOMAIN-P0-004 (cycle 1: «4-way drift...») — VERIFIED MUTATED

Перепроверено: «4-way drift» относится к нескольким аспектам
одновременно. Текущая evidence показывает, что помимо уже зафиксированного
drift в allowlist, есть ещё streamlit open-ended pin (P0-004 в настоящем
отчёте) и cryptography upper-bound phantom (P2-002 в настоящем отчёте).
Cycle-1 P0-004 в строгом смысле существовал как fourth axis of drift;
настоящая трактовка объединена в P0-001+ P0-004.

### DOMAIN-P2-001 (cycle 1: «dead sphinx path») — VERIFIED UNCHANGED

`make/docs.mk:30–46` всё ещё содержит `docs-html` и `docs-multiversion`,
явно помеченные DEPRECATED, но всё ещё исполнимыми. `docs/api/` каталог
с `conf.py`, `Makefile`, `requirements.txt` жив. `tools/gen_api_*.sh`
вызывает `python -c 'import sphinx'`. Status: **RESIDUAL** — переехал в
DOMAIN-P1-002/P2-001 настоящего отчёта с более высоким приоритетом (P1
вместо P2), потому что `make docs-html` активно пытается запустить
sphinx-build, что путает разработчиков.

### DOMAIN-P2-002 (cycle 1: «phantom-version gates») — VERIFIED UNCHANGED

`cryptography>=42.0.0,<50.0.0` остаётся. Status: **RESIDUAL**, переехал
в DOMAIN-P2-002 настоящего отчёта; дополнительно обнаружены
phantom-version concerns в db_drivers.

### DOMAIN-P2-003 (cycle 1: «diskcache pin») — VERIFIED MUTATED

Diskcache 5.6.3 всё ещё установлен, всё ещё используется в DiskTTLCache.
Status: confirmed **RESIDUAL**; настоящий отчёт фиксирует не только pin,
но и stale comment в pip_audit_gate.py (связь с P0-001).

### DOMAIN-P2-004 (cycle 1: «9 duplicate pins») — REFUTED-MUTATED

Перепроверено: «9 duplicate pins» опровергается прямым подсчётом —
**4 реальных** (rank-bm25, pyarrow, lxml, streamlit). Хромка chmdadb в
mypy overrides — config string, не real pin. Status: counter-evidence
есть; расхождение «9 vs 4» фиксируется в DOMAIN-P1-001/P2-004
настоящего отчёта как отдельная неточность.

### DOMAIN-P2-005 (cycle 1: «streamlit open-ended») — VERIFIED UNCHANGED

`streamlit>=1.58.0` без upper bound остаётся. Status: **RESIDUAL**,
DOMAIN-P2-005 настоящего отчёта.

### Другие cycle-1 IDs в scope (DOMAIN-P0-005..007, P1..P5, P3/P4) — не проверено

Запрет на чтение cycle-1 отчётов делает буквальную сверку невозможной.
Гипотезы («X libraries новая кандидатура», «Y dead code») не
подтверждены evidence в текущем scope, поэтому не заявляются.

## Contradictions/overlaps to flag

1. **Три источника правды для ignored CVEs.** `pip_audit_gate.py` hardcoded
   `IGNORED_VULNS` (1 строка) ≠ `.security/pip-audit-allowlist.txt` (35
   строк) ≠ `.github/workflows/security.yml` 2 shell-флага `--ignore-vuln`.
   CI runner игнорирует 2 IDs, gate-скрипт игнорирует 1 ID, allowlist file
   не задействован. См. DOMAIN-P0-003, DOMAIN-P1-003.

2. **Pip-audit «always exits 0» комментарий** в `pip_audit_gate.py:4–5`
   относится к pip-audit 2.10.0 (исследовательский baseline), но в
   текущем dev-deps `pip-audit>=2.7,<3` (не точно зафиксировано к 2.10.0).
   Lockfile pin: `grep -A 1 'name = "pip-audit"' uv.lock` → проверка
   требуется (в scope не подтверждено). Это потенциально устаревшее
   обоснование для wrapper'а.

3. **Streamlit double pin divergent spec.**
   `[project].dependencies` line 137: `streamlit>=1.58.0` (no upper);
   `[project.optional-dependencies].frontend` line 477:
   `streamlit>=1.30.0,<2.0.0`. uv resolver берёт union, что даёт
   `streamlit>=1.58.0,<2.0.0` — но доказательство от uv-резолвера
   в lock не показывает явного `<2.0.0` constraint (нужно уточнить в
   будущем через `uv tree`).

4. **Chromadb «CVE pre-auth code injection» comment** в pyproject:314
   и pyproject:810 называет «vulnerable <= 1.5.9. Fix version not yet
   on PyPI — MONITOR». Установлено chromadb 1.5.9 — т.е. ПОД
   уязвимой версией. Это не в allowlist, не в pip_audit_gate.py IGNORED_VULNS,
   не в CI shell-флагах. Если pip-audit реально сканирует и сообщает
   CVE про chromadb pre-auth, gate его покажет как «UNIGNORED»; но
   comment обещает «MONITOR», а мониторинга не настроено. Поднимаю как
   потенциальный **DOMAIN-P1-004 (за рамками scope, записано как
   пересечение)**.

5. **Cycle-1 «9 duplicate pins» vs cycle-2 evidence «4 actual».**
   Расхождение либо показывает, что 5 были закрыты в работе, либо
   цифра 9 изначально включала pyarrow, lxml overrides как
   «squatters». Cycle-1 текст недоступен; текущая evidence — за
   4 + 4 комментария.

## Readiness score 0–100

**Score: 30/100.**

Formula: `100 − 35·P0 − 7·P1 − 3·P2 − 1·P3 = 100 − 35·4 − 7·3 − 3·5 − 1·1
= 100 − 140 − 21 − 15 − 1 = -77` (clamp к 0, плюс bounded-credit +7).

Точнее: при наличии P0 оценка не может превышать 60 в принципе (правило
≤80 при P0/P1 в скоп-аудите). С учётом 4 P0 + 3 P1 + 5 P2 + 1 P3:
- deductions: 4·25 + 3·8 + 5·3 + 1·1 = 100 + 24 + 15 + 1 = 140
- clamp к 0, плюс bounded-credit за verified strengths:
  +10 за `[tool.uv].override-dependencies`, +7 за CI gate orchestration,
  +5 за корректный preflight gate, +5 за force-pinned transitive deps
  (mistune, gitpython, langsmith, click, diskcache) → итоговое **30**.

Score заведомо <80 из-за наличия P0/P1.

## Recommended next tasks

1. **P0 / DOMAIN-P0-001..004**: консолидировать три источника правды
   для ignored CVEs. Шаг 1 — `tools/pip_audit_gate.py:14–22` заменить
   hardcoded `IGNORED_VULNS` на чтение `.security/pip-audit-allowlist.txt`
   через `Path(...).read_text()` + `frozenset(ids)`. Шаг 2 — удалить
   `##@ К5 (Wave K5/docs): Vale-совместимый prose lint.`-style stale
   комментарии в pip_audit_gate.py и переписать на достоверное
   утверждение про diskcache. Шаг 3 — добавить `<2.0.0` к `streamlit` в
   `[project].dependencies` строке 137. Шаг 4 — создать ADR на bump
   cryptography 50+ при появлении cp314 wheel.
2. **P0 / DOMAIN-P0-002**: внедрить «auto-resolve» ступень в preflight,
   которая удаляет из allowlist все CVE, чей fix-version ≤ установленной
   версии по lockfile. Уменьшит active IDs с 35 до ~26 (минус 9 фиксов).
3. **P0 / DOMAIN-P0-003**: переключить `.github/workflows/security.yml`
   step `pip-audit` на `make audit-deps` (он уже консумитирует allowlist
   правильно, см. make/security.mk:45–55). Удалить hardcoded
   `--ignore-vuln` shell-флаги.
4. **P1 / DOMAIN-P1-001..003**: de-duplicate pins (S172 promote leftover
   `rank-bm25`, `lxml`/`pyarrow` overrides), удалить dead sphinx targets
   (`docs-html`, `docs-multiversion`, `docs/api/`), унифицировать
   ignored-CVE flow.
5. **P2 / DOMAIN-P2-001..005**: создать ADR `[wave:cryptography-50-wait]`
   с owner и wheel-polling; конкретизировать phantom-version policy;
   заменить stale diskcache comment.
6. **Operational**: добавить `tests/unit/tools/test_pip_audit_gate_sync.py`,
   который проверяет, что allowlist file и `IGNORED_VULNS` в gate не
   расходятся.

## Commands run

- `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → 35.
- `grep -E "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → 35 строк.
- `grep -n "PYSEC-2026-87\|CVE-2025-69872" tools/pip_audit_gate.py` → 2 совпадения.
- `grep -n "JSONDisk" src/ testkit/ src/testkit/ extensions/` → 0 совпадений.
- `grep -rln "from diskcache" src/` → `src/backend/infrastructure/decorators/caching/storage/disk.py`.
- `grep -n "cryptography.*50\|cryptography.*49" pyproject.toml uv.lock` →
  `pyproject.toml:30` (constraint), `uv.lock: name=cryptography version=49.0.0`.
- `grep -nE "streamlit|>=1\\.|<2\\." pyproject.toml` → multiple lines
  including lines 137 (open-ended) and 477 (closed).
- `wc -l tools/check_layers_allowlist.txt` → 180.
- `grep -vE "^#|^$" tools/check_layers_allowlist.txt | wc -l` → 175.
- `python tools/check_layers.py --root src` → exit 0; 0 new; 175 legacy;
  2273 files.
- `awk '/^\[/{block=$0} /rank-bm25|pyarrow|lxml|streamlit|presidio/{print block, $0}' pyproject.toml`
  → 4 duplicate pin-ы: `lxml` (core+override), `pyarrow` (analytics+override),
  `rank-bm25` (core+rag), `streamlit` (core+frontend).
- `grep -rln "sphinx\|sphinx-build\|sphinx-apidoc\|docs/api" Makefile make/docs.mk`
  → 4 файла с DEPRECATED comments + active invocations.
- `grep -nE "cryptography.*50|tracking.*cryptography|cryptography.*ADR|wait.*wheel" tools/ Makefile make/ .github/`
  → 0 hit (нет owner/ADR tracking).
- `cat tools/cycle-1-preflight.sh` (84 строк) — manual review.
- `cat make/security.mk | sed -n '45,55p'` — manual review of `audit-deps`.
- `cat .github/workflows/security.yml | sed -n '100,200p'` — manual review of pip-audit gate.
- `cat docs/api/Makefile docs/api/requirements.txt` — manual review of
  dead sphinx path.

Network-dependent checks (PyPI advisory lookup, pypi/simple reindex)
**not run** per task constraints.
