# ADR-0124 — Sprint 50 closure: TD backlog + transport.py B3-B5 + ai_banking/rpa god-file decomp (5 commits, 5/5 substantive)

* Статус: Accepted (Sprint 50 W5, 2026-06-10)
* Связано с: 46a8906d (W1), 02066a45 (W2), b8a59582 (W3), bd6fbb1a (W4), ADR-0123 (S49 W5 closure).

## Контекст

Sprint 50 = tech-debt closure cycle. Pre-flight verify-claims обнаружил
TD-009 stale (S49 closed it, entry не обновлён), Python target уже locked
(TD-001), vite-env.d.ts is correct (TD-007 no-bug). God-file backlog:
ai_banking.py 828, rpa.py 823, transport.py 13 методов remaining.

## Sprint 50 deliverables (4 новых commits + 1 closure = 5 commits)

| # | Task | Commit | Source | Outcome |
|---|------|--------|--------|---------|
| W1 | TD-001/007/009 stale closure + re-scope TD-002/003/006/010 | `46a8906d` | post-S49 verify-claims | ✅ 3 closed, 4 re-scoped |
| W2 | transport.py B3-B5: Sources/External/Proxy mixin extraction | `02066a45` | ADR-0107 S84 W2 carryover | ✅ 13 methods → 3 mixins, ADR-0107 fully closed |
| W3 | ai_banking.py 828 → 6-file package (identity/credit/document + _audit/_base) | `b8a59582` | 4th-largest god-file | ✅ 828 → 1001 LOC across 6 files (re-export overhead) |
| W4 | rpa.py 823 → 4-file package (documents/operations/system) | `bd6fbb1a` | 5th-largest god-file | ✅ 823 → 974 LOC across 4 files |
| W5 | closure (CHANGELOG + ADR-0124 + INDEX regen) | (this commit) | S50 W5 | ✅ this commit |

**5/5 substantive waves.**

## Решения

### W1: TD backlog re-scope

3 stale TDs closed (через verify-claims S49 retrospective):
- **TD-001** (Python target): `requires-python = ">=3.14,<3.15"` already locked,
  decision made (pydantic-core PyO3 0.25+ migration done в S43+)
- **TD-007** (vite-env.d.ts bug): file is `/// <reference types="vite/client" />`
  (correct), NOT HTML — TD-007 description was wrong from start
- **TD-009** (31_DSL_Visual_Editor.py): S49 W2 closed (776→616 LOC, target 600
  overshoot 16)

4 TDs re-scoped для S51+:
- **TD-002** (per-module coverage): full pytest --cov still >90min; defer
  per-module active
- **TD-003** (vault_cipher removal): S51 W2 candidate (2 files, 0 usage,
  363 LOC tests preserved)
- **TD-006** (Vite/chromadb phantom versions): low risk, S51+ if needed
- **TD-010** (set_page_config): 69 files affected, batch add needed

### W2: transport.py B3-B5 — ADR-0107 closure

Per S84 W2 (B1) + S49 W4 plan, decomposed 13 remaining methods into 3
mixin files (per ADR-0107 B3-B5):

| File | Methods | LOC |
|------|---------|-----|
| `transport/sources.py` | directory_scan, from_nats_js, from_webdav, to_nats_js, poll (5) | 231 |
| `transport/external.py` | http_call, graphql_query, web_search (3) | 124 |
| `transport/proxy.py` | expose_proxy, forward_to, proxy, redirect (4) | 134 |
| `transport/__init__.py` | TransportMixin (MRO) + timer (1) | 58 |

**MRO chain:** `TransportMixin → SourcesMixin → ExternalMixin → ProxyMixin
→ PersistenceMixin → SinksMixin → object` (6-level).

**ADR-0107 status:** Accepted (B1+B3-B5 complete, fully implemented per
decomposition plan).

### W3: ai_banking.py 828 → 6-file package

Multi-class domain module (NOT single god-class), so file split per
domain (not MRO per ADR-0107):

| File | Items | LOC |
|------|-------|-----|
| `ai_banking/_audit.py` | _emit_audit helper | 95 |
| `ai_banking/_base.py` | _BankingAIProcessor base | 127 |
| `ai_banking/identity.py` | KycAml{Result,VerifyProcessor}, AntiFraud{Result,ScoreProcessor} | 291 |
| `ai_banking/credit.py` | CreditScoring{Result,RagProcessor}, CustomerChatbotProcessor, AppealProcessorAI | 214 |
| `ai_banking/document.py` | DocumentClassifier{Result,Processor}, Francotyping{Result,Processor}, TransactionCategorizerProcessor, FinDocOcrLlmProcessor | 293 |
| `ai_banking/__init__.py` | re-exports + __all__ | 55 |

**Backward-compat:** 10+ consumer files (processors/__init__.py:25,
builders/ai_rpa.py:670-722, tests/unit/dsl/banking/test_ai_banking.py:36)
work без изменений (Python package import precedence).

**Lessons from W3:**
- 4 script iterations needed (imports_only stripping, missing _logger def,
  result class extraction, __all__ cleanup)
- Per-class line-range slicing (S49 W3 lesson reinforced)
- Cross-module imports: `from ._base import _BankingAIProcessor` в identity/credit/document

### W4: rpa.py 823 → 4-file package

Simpler than ai_banking (no base/results, just 16 independent processor
classes):

| File | Classes | LOC |
|------|---------|-----|
| `rpa/documents.py` | PdfRead, PdfMerge, WordRead, WordWrite, ExcelRead (5) | 268 |
| `rpa/operations.py` | FileMove, Archive, ImageOcr, ImageResize, Regex, TemplateRender, Hash, Encrypt, Decrypt (9) | 496 |
| `rpa/system.py` | ShellExec, EmailCompose (2) | 157 |
| `rpa/__init__.py` | re-exports + __all__ | 53 |

**Backward-compat:** 5+ consumer files (processors/__init__.py:168,
tests/unit/dsl/engine/processors/test_rpa.py:13) work без изменений.

## Outstanding work (S51+ candidates)

- **TD-003 (vault_cipher removal)** — S51 W2 candidate (low risk, 2 files, 0 external usage)
- **TD-010 (set_page_config batch add)** — 69 files affected, S51+ W3 candidate
- **God-file backlog (3 remaining):** validator.py 760 (core/config/), loader_v11.py 724 (services/plugins/), agent_dsl.py 771 (builders/eip/) — single-sprint each
- **transport.py B6+:** scheduling.py (timer already in __init__.py, low priority)
- **Sibling-RACE outstanding:** 21 unstaged entries (feature-flags refactor + stub regenerations from `script_runner.py`, `builder.pyi`, `base.pyi`)

## Quality gates (final)

- **mypy**: 1544 source files clean (was 1532 at S49 closure, +12 for new transport/ai_banking/rpa files; -3 sibling-untracked errors not from S50)
- **ruff**: 0 errors (S50 baseline was 0, S50 changes preserve it)
- **ADRs**: 73 → 74 (S50 W5 this ADR)
- **CHANGELOG**: Sprint 49 section → Sprint 50 section
- **Disk**: same as S49 (-2GB from S49 W4 trunk hygiene preserved)

**5/5 substantive waves.** Sprint 50 closed.
