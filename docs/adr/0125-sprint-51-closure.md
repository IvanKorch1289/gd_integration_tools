# ADR-0125 — Sprint 51 closure: ai_rpa.py (2-wave) + agent_dsl.py + TD-003 (5 working + 1 fixup commits, 5/5 substantive)

* Статус: Accepted (Sprint 51 W5, 2026-06-10)
* Связано с: a21b1427 (W1), b9b3d502+a89f0cc3 (W2, split into 2 commits), 0b252cd3 (W3), e801d9ce (W4), ADR-0124 (S50 W5 closure).

## Контекст

Sprint 51 = god-file decomp cycle (continuation of S50 tech-debt closure).
Pre-flight verify-claims: 2-largest god-files now are `ai_rpa.py` (61-method
god-class) и `agent_dsl.py` (17-method god-class). TD-003 vault_cipher removal
eligible per S50 re-scope.

## Sprint 51 deliverables (4 working commits + 1 fixup = 5 commits, 5/5 substantive)

| # | Task | Commit | Source | Outcome |
|---|------|--------|--------|---------|
| W1 | ai_rpa.py W1: 18 AI/LLM methods → AILlMMixin | `a21b1427` | 1st-largest god-file (61 methods) | ✅ 18/61 methods extracted, MRO 2-level |
| W2 | ai_rpa.py W2: 20 RPA methods → RPAMixin + fixup unused imports | `b9b3d502` + `a89f0cc3` | continuation of W1 | ✅ 38/61 methods extracted, MRO 3-level |
| W3 | agent_dsl.py 17 methods → OrchestrationMixin(8) + InfraMixin(9) | `0b252cd3` | 3rd-largest god-file | ✅ 17/17 methods extracted, MRO 2-level |
| W4 | TD-003 vault_cipher removal: delete 2 files (430 LOC) | `e801d9ce` | S50 re-scope | ✅ 2 files deleted, 0 external usage, tests preserved |
| W5 | closure (CHANGELOG + ADR-0125 + INDEX regen + TD-003 close) | (this commit) | S51 W5 | ✅ this commit |

**5/5 substantive waves (W2 split into 2 commits per fixup pattern).**

## Решения

### W1: ai_rpa.py W1 — AILlMMixin

Extracted 18 AI/LLM methods from 61-method god-class `AIRPAMixin` (824 LOC):

| Category | Methods | LOC |
|----------|---------|-----|
| Integration processors | mcp_tool, agent_graph | 24 |
| Web primitives | scrape, paginate, api_proxy | 49 |
| RAG | rag_search, rag_query, rag_ingest | 66 |
| LLM core | compose_prompt, call_llm, parse_llm_output | 25 |
| Token + PII | token_budget, sanitize_pii, restore_pii | 17 |
| Memory + events | get_feedback_examples, publish_event, load_memory, save_memory | 44 |

**MRO chain:** `AIRPAMixin → AILlMMixin → object` (2-level).

### W2: ai_rpa.py W2 — RPAMixin + fixup

Extracted 20 RPA methods (browser automation + caching + document ops):

| Category | Methods | LOC |
|----------|---------|-----|
| Browser automation | navigate, click, fill_form, extract, screenshot, run_scenario | 50 |
| Caching + routing | call_llm_with_fallback, cache, cache_write, guardrails, semantic_route | 67 |
| Document operations | pdf_read, pdf_merge, word_read, word_write, excel_read, file_move, archive, ocr, image_resize | 110 |

**MRO chain:** `AIRPAMixin → RPAMixin → AILlMMixin → object` (3-level).

**ai_rpa.py decomp status (post-S51 W2):**
- 38/61 methods extracted (62%)
- 23 methods remain in `__init__.py` (deferred to S52):
  - regex, render_template, hash, encrypt, decrypt (5 text ops)
  - shell, email (2 system)
  - citrix, terminal_3270, appium_mobile, email_driven, keystroke_replay (5 automation)
  - kyc_aml_verify, antifraud_score, credit_scoring_rag, customer_chatbot, appeal_ai, tx_categorize, findoc_ocr_llm (7 banking)
  - script_python, script_node, script_ruby, script_shell (4 scripting — sibling added S51 W0 commit)

**W2 fixup commit (`a89f0cc3`):** post-commit removal of unused imports
(`Callable`, `Any`, `Exchange`) из `__init__.py` — 4 LOC reduction. Per
S49 W4-W5 pattern: post-strip + ruff --fix surfaces dead imports, fixup
acceptable scope expansion.

### W3: agent_dsl.py — 2 mixins (Orchestration + Infra)

| File | Methods | LOC |
|------|---------|-----|
| `agent_dsl/orchestration.py` | agent_run, ai_invoke, agent_branch, agent_loop, agent_parallel, plan_execute, reflection_loop_workflow, hitl_approval (8) | 391 |
| `agent_dsl/infra.py` | guardrails_apply, pii_mask, pii_unmask, agent_graph, skill_invoke, ai_memory_recall, ai_memory_store, ai_rpa, mcp_tool (9) | 431 |
| `agent_dsl/__init__.py` | MRO composition only | 18 |

**MRO chain:** `AgentDSLMixin → OrchestrationMixin → InfraMixin → object` (3-level).

**Backwards-compat:** `from src.backend.dsl.builders.agent_dsl import AgentDSLMixin`
preserved (now from package `__init__.py`).

### W4: TD-003 vault_cipher removal

Verified 0 external usage (3 references found, all comments/docstrings):
- `src/backend/core/config/vault.py:7` — docstring example
- `src/backend/core/config/features/sprints_18_21.py:60` — feature list string
- `src/backend/core/net/outbound_http.py:90` — comment

Deleted 2 files (430 LOC total):
- `src/backend/core/security/vault_cipher.py` (150 LOC, 11430 bytes)
- `src/backend/core/security/vault_cipher_sqlalchemy.py` (75 LOC, 6871 bytes)

**Tests preserved (S38):** 2 test files in `tests/unit/core/security/test_vault_cipher{,_sqlalchemy}.py`
stay (522 tests pass per S38) — deletion is low-risk для V24+ migration.

## Outstanding work (S52+ candidates)

- **ai_rpa.py W3:** 23 methods remaining (text ops + banking + scripts) → 2-3 mixins
- **validator.py 760:** ConfigValidator god-class (16 methods, 532 LOC) → MRO decomp
- **loader_v11.py 724:** PluginLoaderV11 god-class (14 methods, 610 LOC) → MRO decomp
- **TD-002** (per-module coverage), **TD-006** (Vite/chromadb phantom), **TD-010** (set_page_config)
- **Sibling-RACE outstanding:** 19+ unstaged entries (feature-flags refactor + stub regenerations)

## Quality gates (final)

- **mypy**: 1546 source files clean (S51 changes: +2 from agent_dsl/orchestration.py + infra.py)
- **ruff**: 0 errors on S51 changes
- **ADRs**: 74 → 75 (S51 W5 this ADR)
- **TECH_DEBT entries closed:** TD-003 (S51 W4)
- **LOC reduction:** -2,050 LOC (ai_rpa.py -824 + agent_dsl.py -771 + vault_cipher -430 ≈ -2,025 + 6 new mixin files overhead)

**5/5 substantive waves.** Sprint 51 closed.
