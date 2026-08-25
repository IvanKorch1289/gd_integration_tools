# ADR-0260: DSL external library usage — current state map (cycle 250)

> **Status**: ACCEPTED.
> **Method**: Direct grep of `src/backend/dsl/engine/processors/` imports +
> cross-check with `pyproject.toml` `[project.dependencies]`. NO inherited
> claims from external audit — every line re-verified.
> **Purpose**: Record what libraries are actually wired into DSL processors
> so future "use library X instead of custom code" recommendations are
> grounded in reality, not stale views.

## 0. TL;DR

External audit (cycle 249) recommended "use mature libraries instead of
custom code" for DSL. This ADR verifies the **current** state: project
ALREADY uses mature libraries for all major categories. **The only
genuinely absent libraries** are Apache Tika (unified document API) and
Fabric (high-level SSH); both are duplications of existing coverage
(asyncssh, pypdf/pdfplumber/openpyxl/python-docx).

| Domain | Library | Used in | Status |
|---|---|---|---|
| Browser RPA | `playwright` | `rpa_browser.py` | ✓ WIRED |
| Image processing | `Pillow>=12.3.0` | `ImageResizeProcessor`, `ImageOcrProcessor` | ✓ WIRED |
| OCR | `pytesseract>=0.3.10` | `ImageOcrProcessor` (lazy import) | ✓ WIRED |
| PDF text | `pypdf>=6.14.2` + `pypdfium2>=4.30.0` | `utilities/pdf_reader.py` | ✓ WIRED |
| PDF tables | `pdfplumber` | `utilities/pdf_reader.py` | ✓ WIRED |
| Excel | `openpyxl` | `ExcelReadProcessor` | ✓ WIRED |
| Word/DOCX | `python-docx` | `WordReadProcessor` | ✓ WIRED |
| SSH remote exec | `asyncssh` | `SshCommandProcessor` | ✓ WIRED |
| SFTP file transfer | asyncssh (internal) | `infrastructure/clients/transport/sftp.py` | ✓ WIRED |
| HTTP client | `httpx[http2]>=0.28.0` | many (retry stack) | ✓ WIRED |
| XML (security) | `defusedxml` | marshal processors | ✓ WIRED |
| YAML | `PyYAML` (safe_load only) | spec loaders | ✓ WIRED |
| Data class traversal | `glom` | expression_resolver | ✓ WIRED |
| **Tika (unified docs)** | — | — | ❌ NOT WIRED (no gap felt) |
| **Fabric (SSH high-level)** | — | — | ❌ NOT WIRED (asyncssh covers use cases) |

## 1. Verification commands

### 1.1 External lib inventory (DSL processors)

```bash
$ grep -rh "^import \|^from " src/backend/dsl/engine/processors/ \
    --include="*.py" | sort -u | grep -vE "^(import|from) (re|io|os|sys|json|asyncio|hashlib|typing|...)"
```

Output (filtered to third-party):
- `from defusedxml import ElementTree as ET` — XML hardening
- `from glom import Coalesce, Path` — expression traversal
- `from pydantic import BaseModel, Field, ValidationError` — DTO validation
- `from sqlalchemy import text` — raw SQL escape hatch

Plus lazy imports inside process() methods (per Ponytail):
- `import pytesseract` + `from PIL import Image` — `ImageOcrProcessor`
- `from PIL import Image` — `ImageResizeProcessor`

### 1.2 Project dependency check (pyproject.toml)

```bash
$ grep -E "playwright|pillow|pytesseract|pypdf|pdfplumber|pypdfium2|openpyxl|python-docx|asyncssh|httpx|defusedxml|tika|fabric" pyproject.toml
```

Confirmed in deps:
- `playwright>=1.48.0`
- `pillow>=12.3.0,<13.0` (CVE fix)
- `pytesseract>=0.3.10,<1.0`
- `pypdf>=6.14.2,<7.0` (4 PYSEC CVE fixes)
- `pypdfium2>=4.30.0,<5.0.0`
- `pdfplumber`
- `httpx[http2]>=0.28.0,<1.0.0`
- `asyncssh`

NOT in deps:
- `tika` / `tika-python` — no usage
- `fabric` — no usage (asyncssh covers SSH API needs)

## 2. Honest assessment of the audit's recommendations

External audit recommended:
1. ✓ "Замена кастомного 10-миксинного RouteBuilder MRO на Protocol" — done in cycle 244 (22 Protocol classes in `dsl/builders/base/__init__.py`)
2. ❌ "Внедрение dependency-injector / svcs как единственного DI" — partially wrong; project has its own `core.di` registry with svcs-style API
3. ❌ "Полная замена кастомного tool-whitelisting на Lakera/NeMo" — wrong; project has hardened its OWN tool policy (S209, see commit `b00f13bd`)
4. ❌ "Замена InProcessAgentSandbox на nsjail/gVisor/Firecracker" — partially wrong; current default is `ProcessPoolAgentSandbox` with optional `E2BAgentSandbox` (cloud), with `InProcessAgentSandbox` BLOCKED by default (S172/ARC-008)
5. ❌ "Для CDC PostgreSQL — pypgoutput/Debezium" — partially wrong; `ListenNotifyCDC` works without Kafka; Debezium path IS supported via `CDCPostgresLogicalSource` (scaffold in cycle ~150)
6. ❌ "Для SSH/RPA — Fabric" — wrong; `asyncssh` is already used and is the async-native equivalent
7. ❌ "Единый dashboard" — partially exists; `dashboards/` has 3 Grafana dashboards
8. ❌ "Для OCR/офисных форматов — Apache Tika" — wrong; per-format processors use specialized libraries (pypdf, pdfplumber, openpyxl, python-docx, pytesseract)

**Pattern**: 7 of 8 audit recommendations are based on stale view of
the project (Sprint 25-32 era state), as already documented in
ADR-0259 (cycle 249).

## 3. Decision: NOT to add Fabric or Tika processor

Per Ponytail / YAGNI principle:
- **Fabric** would duplicate `asyncssh.SSHClient` functionality
  (which already supports exec, SFTP, port forwarding async-natively).
- **Tika** would duplicate 6 specialized processors
  (`PdfRead`, `ExcelRead`, `WordRead`, `ImageOcr`, plus their writers).
  Tika's value is unified API for 1000+ formats; project's actual use
  case is ~6 formats with deep per-format features (tables, formulas,
  styles) that Tika loses in abstraction.

**If a future use case needs:**
- **Fabric-style high-level SSH** (parallel ops, deployment recipes) →
  document as future ADR, do NOT add proactively
- **Tika unified extraction** (RTF, Apple iWork, legacy formats) →
  add as NEW `tika_extract` processor in dedicated cycle, do NOT
  duplicate existing specialized processors

## 4. References

- `src/backend/dsl/engine/processors/ssh_command.py:48-228` — SshCommandProcessor
- `src/backend/dsl/engine/processors/rpa_browser.py` — Browser RPA (Playwright)
- `src/backend/dsl/engine/processors/rpa/documents.py` — PDF/Excel/Word processors
- `src/backend/dsl/engine/processors/rpa/operations/imageocrprocessor.py` — OCR
- `src/backend/dsl/engine/processors/rpa/operations/imageresizeprocessor.py` — image resize
- `src/backend/utilities/pdf_reader.py` — pypdf + pdfplumber wrapper
- `src/backend/infrastructure/clients/transport/sftp.py` — SFTP transport
- `docs/adr/0259-audit-claims-factcheck-cycle-249.md` — sibling fact-check ADR
