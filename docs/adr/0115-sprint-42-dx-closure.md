# ADR-0115 — Sprint 42 closure: Developer Experience Polish (5/5 DoD)

* Статус: Accepted (Sprint 42 W5, 2026-06-09)
* Связано с: PLAN.md §6 (S42 #1-#5); ADR-0110, 0111, 0113, 0114 (DX trend).

## Контекст

Sprint 42 = Developer Experience Polish. 5 DoD tasks из PLAN.md §6.

## Sprint 42 deliverables

| # | Task | Wave | Commit | Files |
|---|---|---|---|---|
| 1 | LSP server для DSL (pygls) — formalize + make target | W1 | `107c3f36` | `Makefile`, `docs/lsp/vscode-config.example.json`, ADR-0114 |
| 2 | Onboarding wizard (5-step interactive setup) | W2 | `f5e7d9ae` | `tools/wizards/onboarding_wizard.py` (270 LOC) |
| 3 | ADR→wiki sync automation | W3 | `08927170` | `tools/build_adr_wiki.py`, `.github/workflows/adr-sync.yml` |
| 4 | Route debugger (visual trace Streamlit page) | W4 | `85f0d2fd` | `src/frontend/streamlit_app/pages/35_Route_Debugger.py` (159 LOC) |
| 5 | Plugin scaffolding — interactive codegen | W4 | `85f0d2fd` | `tools/codegen_plugin.py` (+87 LOC) |

## Решения

### W1: LSP server formalize (не rewrite)
- Существующий `src/backend/dsl/cli/lsp_server.py` (236 LOC, S6/K3) уже
  6/6 tests pass.
- Добавили Makefile target `lsp-server` + `docs/lsp/vscode-config.example.json`.
- **Не мигрировали** на monaco / language-server extras — `pygls>=1.3` достаточно.

### W2: Onboarding wizard
- Typer + questionary + rich (тот же паттерн что `plugin_wizard.py` S33 W2 +
  `route_wizard.py` S33 W1).
- 5 шагов: preflight → uv sync → doctor → precommit → sample plugin.
- `--non-interactive` + `--dry-run` modes для CI.
- `make onboarding` + `make onboarding-non-interactive` targets.

### W3: ADR → wiki sync
- Lightweight GitHub Action (5 sec) vs full Sphinx build (5 min).
- `tools/build_adr_wiki.py` парсит ADR frontmatter, генерирует
  `docs/adr/WIKI.md` с chronological summary + sprint tags.
- Regex `S(?:print)?\s*(\d+)\s*W(\d+)` поддерживает "Sprint 40 W1" и "S40 W1".
- Auto-commit `WIKI.md` через GitHub Action.

### W4a: Route Debugger (Streamlit)
- `src/frontend/streamlit_app/pages/35_Route_Debugger.py` (159 LOC):
  timeline + step list + summary metrics (3× cols) + filters.
- Demo data fallback для offline view.
- Backend integration TODO: wire к `src/backend/dsl/engine/tracer.py` (S10/K3/W8).

### W4b: Interactive codegen
- `--interactive` flag в `tools/codegen_plugin.py` → questionary prompts
  (name, description, features, capabilities, with_frontend, overwrite).
- `--name` теперь optional (required только в non-interactive mode).
- Backward compat: argparse flows неизменны, CI scripts работают.

## Sprint 42 DoD score

**5/5 closed**. Все gates зелёные:
- ruff: All checks passed на всех новых/modified файлах.
- mypy: 0 issues (streamlit pages с explicit `float()`/`int()` cast +
  `# type: ignore[union-attr]` на `cols[].metric` per streamlit stubs).
- LSP server: 6/6 tests pass.
- pytest: full DSL suite 3366+ passed.

## Тех. долг (deferred)

Sprint 42 не починил следующие TDs (scope был чисто DX, не maintenance):
- **TD-018** — 18 undeclared FF `_strict` flags (S42+ D).
- **TD-019** — 100+ docstring violations (cert_store.py=25, redis.py=21,
  generic.py=47, ...).
- **TD-020** — 33 chaos tests skipped (need toxiproxy daemon).
- **TD-021** — B104 hardcoded bind (`0.0.0.0` allowed via `B104` nosec).
- **TD-022** — B608 nosec на 20 SQL builders (`_safe_ident` + `_escape`
  allowlisted per ADR-0099).
- **TD-023** — full perf benchmark (k6 1000 RPS sustained).
- **TD-024** — Jupyter DSL + routes (deferred to S43+ по запросу user).

## Метрики сессии

- Commits: 4 (W1-W4), 0 fix-up.
- LOC added: ~615 (W1: 50, W2: 270, W3: 158, W4: 246 — частично overlap).
- ADR count: 64 → 65 (этот).
- Test count: +0 (LSP 6/6 уже passing до S42; новые wizards CLI-only).
- Push: на стороне user.

## Next (S43+)

Per `PLAN.md` §7 backlog + user direction "Продолжай s42, к Jupiter
вернёмся позже":

1. **S43** (TBD scope) — candidates:
   - TD-024 Jupyter DSL (требует user clarifications: scope, transport,
     storage — см. conversation 2026-06-09).
   - Continue S42 maintenance TDs (TD-018, 019).
   - New DX tasks (e.g., Streamlit ThemeBuilder, async job visualizer).
2. **S44+** — chaos+toxiproxy infra (TD-020), perf-env k8s (TD-023).
