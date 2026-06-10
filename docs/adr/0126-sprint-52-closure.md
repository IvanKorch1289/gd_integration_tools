# ADR-0126 — Sprint 52 closure: ai_rpa.py W3 + validator.py + loader_v11.py god-file decomp + TD-010 closure (5+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 52 W5, 2026-06-10)
* Связано с: 41fdce35+a5a17864 (W1), 9bdc0fc6 (W2), ba49541a (W3), 4533ba41 (W4), ADR-0125 (S51 W5 closure).
* Параллельная работа: sibling commits `f3c7105e` (JupyterHub settings + async client, TD-024) и `5435e976` (Python 2-style except mass-fix) выполнены в S52 timeframe.

## Контекст

Sprint 52 = continuation of god-file backlog closure (S49-S51 series).
Pre-flight verify-claims: top remaining god-files в src/backend (после S51):
1. `ai_rpa.py` (S51 W1+W2 WIP, 23 methods remaining) → W1 S52
2. `validator.py` 760 → W2 S52
3. `loader_v11.py` 724 → W3 S52
4. TD-010 stale (setup_page helper) → W4 S52
5. Closure → W5 S52

5 substantive waves, 5/5.

## Sprint 52 deliverables (5 commits, 5/5 substantive)

| # | Task | Commit | Source | Outcome |
|---|------|--------|--------|---------|
| W1 | ai_rpa.py W3: 23 remaining methods → TextOpsMixin(5) + SystemOpsMixin(7) + BankingScriptsMixin(11) | `41fdce35` + `a5a17864` (fixup) | S51 W1+W2 carryover | ✅ 61/61 methods fully decomposed, MRO 6-level |
| W2 | validator.py 760 → ConfigValidator 14 _check_* methods + 2 public → SecurityChecksMixin(6) + APIDocsChecksMixin(3) + InfrastructureChecksMixin(5) + _helpers | `9bdc0fc6` | new top-1 god-file | ✅ ConfigValidator fully decomposed, MRO 4-level, _helpers pattern established |
| W3 | loader_v11.py 724 → PluginLoaderV11 14 methods → DiscoveryMixin(2) + LoadingMixin(5) + ValidationMixin(2) + 5 public | `ba49541a` | new top-2 god-file | ✅ PluginLoaderV11 fully decomposed, MRO 4-level, state attrs via class-level annotations |
| W4 | TD-010 closure: documentation update (stale entry, superseded by ``setup_page()`` helper) | `4533ba41` | S50 re-scope | ✅ 1 line, TD-010 marked stale (no code change needed) |
| W5 | closure (CHANGELOG + ADR-0126 + INDEX regen) | (this commit) | S52 W5 | ✅ this commit |

## Решения

### W1: ai_rpa.py W3 — final 23 methods

3 new mixin files (all в S52 W1):
- `text_ops.py` (99 LOC): regex, render_template, hash, encrypt, decrypt
- `system_ops.py` (140 LOC): shell, email, citrix, terminal_3270, appium_mobile, email_driven, keystroke_replay
- `banking_scripts.py` (211 LOC): kyc_aml_verify, antifraud_score, credit_scoring_rag, customer_chatbot, appeal_ai, tx_categorize, findoc_ocr_llm (7 banking) + script_python, script_node, script_ruby, script_shell (4 scripting)

**Final MRO chain (6-level):** `AIRPAMixin → BankingScriptsMixin → SystemOpsMixin → TextOpsMixin → RPAMixin → AILlMMixin → object`.

**ai_rpa.py decomp COMPLETE** (61/61 methods, 3 waves: S51 W1+W2, S52 W1).

### W2: validator.py decomp — new pattern: _helpers.py

4-file structure:
- `_helpers.py` (49 LOC): PRODUCTION_ENV, JWT_SECRET_MIN_LENGTH, ConfigSeverity, ConfigViolation (dataclass), ProductionConfigError, _FEATURE_FLAG_DEPENDENCIES, _FEATURE_FLAG_DEPENDENCIES_CRITICAL, _FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP
- `security_checks.py` (229 LOC): waf_strict_prod, waf_strict_allow_empty, clamav_fail_open, vault_disabled, cors_credentials, jwt_secret
- `api_docs_checks.py` (100 LOC): swagger_in_prod, redoc_in_prod, admin_without_ips
- `infrastructure_checks.py` (246 LOC): debug_mode, database_host, redis_host_required, redis_host_localhost, feature_flag_dependency
- `__init__.py` (148 LOC): ConfigValidator (validate, _is_prod) + validate_startup_config + MRO

**MRO chain:** `ConfigValidator → SecurityChecksMixin → APIDocsChecksMixin → InfrastructureChecksMixin → object` (4-level).

**New pattern:** `_helpers.py` для shared definitions (constants + helper classes) — avoids circular import between mixin ↔ __init__.py. Future god-files with inline shared definitions should use this pattern.

### W3: loader_v11.py decomp — stateful class challenge

PluginLoaderV11 has 11 state attrs (set в `__init__`). Challenge: mixin methods access `self._gate`, `self._loaded`, etc. — mypy needs hints.

4-file structure:
- `discovery.py` (180 LOC): _topo_sort_non_blocked, _reorder_manifest_paths
- `loading.py` (484 LOC): _load_one, _instantiate, _plugin_page_prefix, _mount_frontend_pages, _unmount_frontend_pages
- `validation.py` (135 LOC): _check_inventory_collisions, _record_owners
- `__init__.py` (212 LOC): PluginLoaderV11 (`__init__` + `loaded`/`successful` properties + `discover_and_load` 77 LOC + `shutdown_all`) + state attr class-level annotations + MRO

**MRO chain:** `PluginLoaderV11 → DiscoveryMixin → LoadingMixin → ValidationMixin → object` (4-level).

**S52 W3 patterns established:**
1. State attrs declared as class-level annotations on the root class (per S49 W3 lesson)
2. State attrs declared on mixins (as `Callable[..., None]` for method calls)
3. Re-exports in `__init__.py` for backward compat (LoadedPluginV11, PluginInventoryConflictError)
4. Re-define `_logger = get_logger(...)` in `__init__.py` (idempotent)
5. @property decorators extracted by including `item.lineno - 1` line
6. Single-line `__all__ = (...)` block: skip line if it ends with `)` (was bug в S51 W3 script)

### W4: TD-010 closure (stale documentation)

Per S50 W1 re-scope: "TD-010 — 14 pages без st.set_page_config, 69 files affected, batch add needed".

**Verify-claims finding:** all 69 affected streamlit pages use `setup_page("Title", ":icon:")` helper (introduced in Sprint 12 K3 W2), which internally calls `st.set_page_config(page_title=..., page_icon=..., layout="wide", initial_sidebar_state="expanded")`. **Helper is the standard pattern**, replaces 5-line boilerplate, called from every page.

**TD-010 entry stale** — superseded by helper. Action: documentation update (mark closed) instead of code change.

## Quality gates (final)

- **mypy**: 1558 source files clean (S52 changes: +3 from W1 mixins, +4 from W2 mixins + _helpers, +3 from W3 mixins = 10 new files)
- **ruff**: 0 errors on S52 changes
- **ADRs**: 75 → 76 (S52 W5 this ADR)
- **TECH_DEBT entries closed:** TD-010 (S52 W4, stale)
- **TD-003 + TD-001 + TD-007 + TD-009 (S50/S51) + TD-010 (S52) = 5 TDs closed за 3 sprints**

## Tech-debt closure (S49-S52 cumulative)

| Sprint | God-files fully decomposed | God-files partial | TDs closed |
|--------|---------------------------|-------------------|------------|
| S49 | 31_DSL_Visual_Editor.py 1267→616, actions.py 986→353+669 | — | TD-009 |
| S50 | transport.py 475→58+489, ai_banking.py 828→6 files, rpa.py 823→4 files | — | TD-001, TD-007 |
| S51 | agent_dsl.py 771→3 files | ai_rpa.py 38/61 (62%) | TD-003 |
| S52 | validator.py 760→4 files, loader_v11.py 724→4 files | — (ai_rpa.py W3 closes) | TD-010 (stale) |

**6 god-files fully closed (31_DSL_Visual_Editor + actions + transport + ai_banking + rpa + agent_dsl + ai_rpa (W3) + validator + loader_v11 = 9).**

## Outstanding (S53+ candidates)

- **Sibling-RACE outstanding**: 19+ unstaged entries (feature-flags refactor, JupyterHub async client, etc.)
- **TD-002** (per-module coverage): needs fresh scope (~90min full >)
- **TD-006** (Vite/chromadb phantom versions): low priority, re-scope if needed
- **Remaining top-5 god-files в src/backend (после S52):** все top-N closed. Next layer: streamlit pages (e.g., 31_DSL_Visual_Editor — already at 616 LOC after S49 W2).

## Patterns established (cumulative S49-S52)

| Pattern | Introduced | Reused |
|---------|-----------|--------|
| `__init__.py` MRO composition | S49 W3 (actions.py) | S49 W3, S50 W2, S51 W1+W2, S52 W1+W2+W3 |
| Class-level `Callable` annotation для MRO cross-attr | S49 W3 | S49 W3, S50 W2, S52 W2+W3 |
| Per-method extract (line-range slicing) | S50 W2 (transport.py) | S50 W2, S51 W1+W2, S52 W1+W2+W3 |
| `_helpers.py` для shared definitions (avoid circular import) | S52 W2 (validator) | S52 W2 (foundation for future) |
| Stateful class state attrs via class-level annotations | S52 W3 (loader_v11) | S52 W3 |
| Stale TD-XXX detection (helper already covers) | S52 W4 (TD-010) | S52 W4 |

**5/5 substantive waves.** Sprint 52 closed.
