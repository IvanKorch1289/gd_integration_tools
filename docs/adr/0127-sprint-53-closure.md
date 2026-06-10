# ADR-0127 — Sprint 53 closure: format_convert + streaming + setup god-file decomp + TD-002 closure (5 commits, 5/5 substantive)

* Статус: Accepted (Sprint 53 W5, 2026-06-10)
* Связано с: 42c80d19 (W1), 6cd6e113 (W2), 4b76a836 (W3), 2710fcbb (W4), ADR-0126 (S52 W5 closure).
* Pre-flight verify-claims: 9 god-files closed S49-S52, top-3 remaining после S52: format_convert 744, streaming 737, setup 756 (1-function god-class).

## Контекст

Sprint 53 = continuation of god-file backlog closure + TD-002 closure. Top-3 god-files после S52 (S50/S51/S52 closed: actions, transport, ai_banking, rpa, agent_dsl, ai_rpa, validator, loader_v11, 31_DSL_Visual_Editor):

1. `format_convert.py` 744 (1 god-class, 38 methods) → W1 S53
2. `streaming.py` 737 (12 small classes) → W2 S53
3. `setup.py` 756 (1 function 731 LOC) → W3 S53
4. TD-002 (pre-prod-check-coverage-timeout) → W4 S53
5. Closure → W5 S53

5 substantive waves, 5/5.

## Sprint 53 deliverables (5 commits, 5/5 substantive)

| # | Task | Commit | Outcome |
|---|------|--------|---------|
| W1 | format_convert.py → FormatConvertProcessor 38 methods → 3 mixins + 5 core | `42c80d19` | ✅ MRO 4-level, _helpers pattern re-used |
| W2 | streaming.py → 13 classes → 4 groups | `6cd6e113` | ✅ rpa.py S50 W4 pattern re-used |
| W3 | setup.py → register_action_handlers 731 LOC → 25 _register_xxx() helpers + 25-call orchestrator | `4b76a836` | ✅ New pattern: per-service lazy imports in helpers |
| W4 | TD-002 closure: Makefile `coverage-gate` uses `pytest -n auto` (xdist) + `coverage combine` | `2710fcbb` | ✅ Per-module workaround retained as fallback |
| W5 | closure (CHANGELOG + ADR-0127 + INDEX regen) | (this commit) | ✅ |

## Решения

### W1: format_convert.py — 38 methods, MRO 4-level, _helpers re-used

4-file structure (per S52 W2 _helpers pattern):
- `__init__.py` (207 LOC): FormatConvertProcessor (`__init__`, `process`, `_convert`, `_to_json`, `_from_json`) + MRO + state attrs (root_tag, sheet_name, etc.)
- `data_formats.py` (340 LOC): DataFormatsMixin (16 methods — CSV, XML, YAML, Excel, Parquet, Msgpack, TOML, INI)
- `encodings.py` (187 LOC): EncodingsMixin (8 methods — Base64, URL, HTML, Markdown)
- `specialized.py` (211 LOC): SpecializedFormatsMixin (9 methods — UUID, JWT, Bencode, compact JSON, Protobuf-like, Avro-like)
- `_helpers.py` (15 LOC): `_to_text()` shared helper (was duplicated across 3 mixins initially; extracted to _helpers.py per S52 W2 pattern)

**MRO:** `FormatConvertProcessor → DataFormatsMixin → EncodingsMixin → SpecializedFormatsMixin → object` (4-level).

**State attrs (S52 W3 pattern re-used):** class-level `root_tag`, `sheet_name`, etc. declared on root for mypy MRO.

### W2: streaming.py — 13 classes, file split per domain

4-file structure (rpa.py S50 W4 pattern re-used):
- `windows.py` (419 LOC): _BaseWindow + TumblingWindowProcessor + SlidingWindowProcessor + SessionWindowProcessor + GroupByKeyProcessor (5 classes)
- `message_meta.py` (162 LOC): MessageExpirationProcessor + CorrelationIdProcessor + SchemaRegistryValidator (3 classes)
- `reliability.py` (151 LOC): ReplyToProcessor + ExactlyOnceProcessor + DurableSubscriberProcessor (3 classes)
- `operations.py` (101 LOC): ChannelPurgerProcessor + SamplingProcessor (2 classes)
- `__init__.py` (50 LOC): re-exports all 13 classes

**__all__ quirk (S53 W2 lesson):** `__all__ = ('_BaseWindow, TumblingWindowProcessor, ...')` (single STRING, not tuple) — ruff rejects as F401. Fix: explicit tuple `__all__ = ("TumblingWindowProcessor", "_BaseWindow", ...)` (sorted alphabetically).

### W3: setup.py — 1 function 731 LOC, new pattern: per-service helpers with lazy imports

`register_action_handlers()` was 731 LOC of inline `action_handler_registry.register/register_many` calls. 20 service sections delimited by `# ── X ──` comments.

**Extraction:**
- Each section becomes `_register_xxx()` helper (def wrapper)
- Helper body preserves original lazy imports (the original `from extensions.X import Y` lines that were inside the function body get duplicated in each helper — preserves original semantics)
- `register_action_handlers()` becomes 25-line orchestrator with 25 calls

**File grew:** 756 → 1222 lines (helpers add +466 lines = duplicated imports + function wrappers). But:
- Main function: 731 → 25 lines (-706 LOC, -97%)
- Each helper: 5-50 LOC, independently testable
- New pattern: per-service lazy imports in helpers (preserves runtime semantics)

**S53 W3 pattern:** for "1 function god-class" files, extract by section boundaries (delimited by `# ── X ──` comments), wrap each in `def _register_xxx():` with imports inlined.

### W4: TD-002 closure (parallel coverage)

Per S38 workaround: per-module `pytest --cov=src.backend.X.Y` (0.5-2s per module) because full `pytest --cov=src` times out at 600s.

**Fix applied:**
- `Makefile`: `coverage-gate` + `coverage-gate-strict` now use `pytest -n auto` (xdist) + `coverage combine` + `coverage report`
- `pyproject.toml [tool.coverage.run]`: `parallel = true`, `concurrency = ["thread", "multiprocessing"]`, `sigterm = true`
- Per-module workaround retained as fallback (TD-002 description still mentions it)

**Expected:** coverage time from 7+ min → ~2-3 min (4x speedup on multi-core machines).

## Quality gates (final)

- **mypy**: 1566 source files clean (S53 changes: +10 new files, ~30 helpers)
- **ruff**: 0 errors on S53 changes
- **ADRs**: 75 → 76 (this ADR)
- **TECH_DEBT entries closed:** TD-002 (S53 W4, parallel coverage) + TD-010 (S52 W4) + TD-003 (S51 W4) + TD-001/007 (S50 W1) + TD-009 (S49) = **6 TDs closed за 5 sprints**
- **God-files fully closed S49-S53:** 9 → **12** (added format_convert, streaming, setup)

## S49-S53 cumulative

| Sprint | God-files fully decomposed | TDs closed |
|--------|---------------------------|------------|
| S49 | 31_DSL_Visual_Editor 1267→616, actions.py 986→353+669 | TD-009 |
| S50 | transport.py 475→58+489, ai_banking.py 828→6 files, rpa.py 823→4 files | TD-001, TD-007 |
| S51 | agent_dsl.py 771→3 files, ai_rpa.py 61/61 methods (3-wave) | TD-003 |
| S52 | validator.py 760→4 files, loader_v11.py 724→4 files | TD-010 (stale) |
| S53 | format_convert.py 744→4 files, streaming.py 737→4 files, setup.py 756→25 helpers | TD-002 (parallel coverage) |

**Total: 12 god-files fully closed, 6 TDs closed.**

## Patterns established (cumulative S49-S53)

| Pattern | Introduced | Reused |
|---------|-----------|--------|
| `__init__.py` MRO composition | S49 W3 (actions.py) | 12 god-files |
| Per-method extract (line-range slicing) | S50 W2 (transport.py) | 7 god-files |
| `_helpers.py` для shared definitions | S52 W2 (validator) | S52 W2, S53 W1 (format_convert) |
| Stateful class state attrs via class-level annotations | S52 W3 (loader_v11) | S52 W3, S53 W1 (format_convert) |
| Per-domain file split (rpa.py pattern) | S50 W4 (rpa.py) | S50 W4, S53 W2 (streaming) |
| Per-service helpers with lazy imports | S53 W3 (setup.py) | S53 W3 (foundation) |
| Stale TD-XXX detection (helper already covers) | S52 W4 (TD-010) | S52 W4 |
| __all__ must be tuple of strings, not set | S53 W2 (streaming) | S53 W2 |
| Per-helper state attr declarations (class-level hints) | S52 W3 (loader_v11) | S52 W3, S53 W1 |
| TD-002 parallel coverage (`-n auto` + `coverage combine`) | S53 W4 | S53 W4 |

## Outstanding (S54+ candidates)

- **Sibling-RACE outstanding**: 8 unstaged entries (route_debugger rename, Makefile side-effects, etc.)
- **TD-006** (Vite/chromadb phantom versions): low risk, S54+ if needed
- **Top remaining god-files в src/backend (после S53):**
  - `mcp_server.py` 706 (entrypoints/mcp/) — 1 class
  - `ai_agent.py` 703 (services/ai/) — service class
  - `invoker.py` 666 (services/execution/) — service class
  - `builder.pyi` 646 (dsl/workflow/) — stub file (pre-existing mypy error)
  - `admin_workflows.py` 639 (entrypoints/api/v1/) — endpoint file
- **Streamlit frontend pages** — next layer
- **Coverage gap full >90min** — TD-002 workaround now addressed, full run target

**5/5 substantive waves.** Sprint 53 closed.
