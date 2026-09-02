# Sprint 53 Plan — M3 Dependency Upgrade (per swarm risk analysis)

> **Generated**: 2026-09-01 (Sprint 53 = M3-#3 + M3-#5 continuation).
> **Source**: Sprint 52 STOP analysis + 2-agent swarm risk assessment (tornado + pypdf).
> **Output**: concrete tasks with risk score + minimum test subset per upgrade.

---

## Sprint 53 scope (по результатам swarm analysis)

| # | Задача | Risk | Test subset | Est |
|---|---|---|---|---|
| S53-T2 | tornado 6.5.7 → 6.5.8 (GHSA-wwv5-g3v4-889x + GHSA-8423-8fgw-73vq) | LOW | 10 unit tests + dask smoke | ~10 min |
| S53-PDF | pypdf 6.14.2 → 6.16.1 (PYSEC-2026-3655/3656 + CVE-2026-84309/84310/84311) | LOW | tier 1+2 tests | ~50 min |
| S53-CRYPTO | cryptography 49.0.0 → 50.0.0+ (PYSEC-2026-3552) | HIGH | full SSL test path | deferred to S54 (ADR required) |
| S53-DISK | diskcache deferral | N/A | N/A | DONE (ADR-0287) |
| S53-VERIFY | Final `uv run pip-audit` — expect 0 vulns except diskcache | LOW | pip-audit + make test | ~5 min |

**Total estimate**: ~65 min + S54 cryptography ADR work.

---

## Swarm analysis summary (read-only verification)

### Tornado (agent-12)

**Finding**: gd_integration_tools **НЕ использует Tornado как web framework**.
- Direct imports: **0** (`grep -rE 'tornado' src/backend/ → 0 matches`)
- HTTP framework = FastAPI (entrypoints)
- WebSocket = `websockets` library (НЕ `tornado.websocket`)
- Cookies = JWT/Redis (НЕ `RequestHandler.set_cookie`)
- Tornado transitive ONLY через `dask.distributed` (dask_backend.py) + `jupyter_client` (3 jupyter execution files)

**CVE applicability**: theoretical-only (нет RequestHandler surface в production).
**Recommendation**: BUMP for compliance/hygiene.

**Minimum test subset** (после `uv lock --upgrade-package tornado`):
```bash
# Tier 1: imports sanity
uv run python -c "import tornado; assert tornado.version == '6.5.8'"

# Tier 2: targeted unit tests (10 файлов)
uv run pytest \
  tests/unit/dsl/test_dask_compute_smoke.py \
  tests/unit/dsl/builders/test_dask_mixin.py \
  tests/unit/services/jupyter/execution_service/test_papermill_factory_heartbeat.py \
  tests/unit/services/jupyter/execution_service/test_e2b_kernelspec.py \
  tests/unit/services/jupyter/test_hub_actions_contracts.py \
  tests/unit/services/jupyter/test_hub_run_orchestrator.py \
  tests/unit/dsl/engine/processors/test_notebook_jupyter.py \
  tests/unit/dsl/engine/processors/test_notebook_dsl.py \
  tests/unit/dsl/processors/test_notebook_di_singleton.py \
  -v --tb=short -m "not slow"

# Tier 3: dask smoke (если dev_light profile)
uv run python -c "
from dask.distributed import LocalCluster, Client
cluster = LocalCluster(n_workers=2, threads_per_worker=1, dashboard_address=None)
client = Client(cluster)
fut = client.submit(lambda x: x*2, 21)
assert fut.result() == 42
client.close(); cluster.close()
print('dask smoke OK')
"

# Tier 4: lint + type-check
make lint-strict
make type-check
```

**Expected runtime**: ~10 min.

### pypdf (agent-13)

**Finding**: 5 production files, all using stable public API.
- `PdfReader` + `.pages` + `page.extract_text()` — public stable since 4.x
- 1 `PdfWriter` usage (documents.py:125)
- 1 `reader.metadata.title/author` (pdf_ingester.py:267-270)
- Low-level `pypdf.generic.*` ONLY в test fixture (`test_pdf_ingester.py:36`)

**4-layer defense-in-depth**:
1. Cascade fallback: `pdfium → pypdf → PdfReaderUnavailable` (graceful degradation)
2. Lazy import в RPA-processors (ImportError → exchange.fail)
3. `markitdown_settings.engine_enabled` toggle (legacy fallback opt-in)
4. Skip-if-not-installed в `PdfExtractProcessor`

**Recommendation**: BUMP (CVE RCE-class, public API stable).

**Minimum test subset** (tier-ordered, ~30 min):
```bash
# Tier 1 — HIGHEST risk (production + fragile fixture)
pytest tests/unit/utilities/test_pdf_reader.py -v
pytest tests/unit/services/ai/rag/multimodal/test_pdf_ingester.py -v
# ↑ фикстура _make_minimal_pdf использует pypdf.generic.* — primary risk

# Tier 2 — MEDIUM risk (RPA surface)
pytest tests/unit/dsl/engine/processors/rpa/operations/test_document_processors.py -v
pytest tests/unit/dsl/engine/processors/rpa/test_pdf_extract.py -v

# Tier 3 — Smoke (legacy _parse_pdf)
pytest tests/unit/services/ai/document_parsers -v  # если есть unit-tests

# Tier 4 — Full regression net
make test
```

**Pass criteria**:
- [ ] `test_pdf_ingester_extracts_text_via_pypdf` (metadata.engine in ('pypdfium2','pypdf') + page_count >= 1)
- [ ] `test_pdf_ingester_handles_broken_pdf` (graceful degradation)
- [ ] `test_pdf_ingester_falls_back_to_pypdf` (cascade не сломан)
- [ ] `_make_minimal_pdf` fixture НЕ (pypdf.generic.* rename → fixture-fix required)

---

## ADR-0288 (cryptography bump — Sprint 54)

**Status**: Deferred to Sprint 54. Требует:
1. ADR-0288 с risk analysis: upper bound lift `cryptography<50.0.0` → `<51.0.0`
2. Объяснение wheel-availability constraint (cp314-cp314**t free-threaded wheels)
3. SSL test path (core/auth/mtls_backend.py, services/crypto/*)
4. `uv run python -c "from cryptography.hazmat.primitives import ..."` smoke

---

## Honest assessment

**CVE exposure для gd_integration_tools (real)**:
- tornado 6.5.7 → 6.5.8: **0% exploitable** (no Tornado surface in production paths)
- pypdf 6.14.2 → 6.16.1: **CVE RCE-class** (per upstream), реально exploitable если атакующий может передать crafted PDF в upload. Production upload paths через `/api/v1/rag/*` И `/api/v1/admin/*` И `/import/bulk-objects` — attack surface REAL but gated by capability check.
- cryptography: BLOCKED per S36-4 hardening
- diskcache: fallback-only

**Recommendation**: Sprint 53 — bump tornado + pypdf + final pip-audit. Sprint 54 — cryptography ADR + bump.

---

## Sprint 53 atomic commits

| # | Commit | Описание |
|---|---|---|
| 1 | `docs(adr): ADR-0288 tornado 6.5.7 → 6.5.8 rationale` | per swarm analysis |
| 2 | `chore(deps): uv lock --upgrade-package tornado` | isolated blast radius |
| 3 | (verification commit, conditional) | if tier 1+2 fail |
| 4 | `docs(adr): ADR-0289 pypdf 6.14.2 → 6.16.1 rationale` | per swarm analysis |
| 5 | `chore(deps): uv lock --upgrade-package pypdf` | within `<7.0` constraint already |
| 6 | `chore(deps): final pip-audit — expect 0 vulns except diskcache` | M3-#5 done-критерий |

**Hard rules respected**: NO pyproject.toml edit (pypdf constraint `>=6.14.2,<7.0` already admits 6.16.1); NO force-push; single-package upgrades (не bulk).