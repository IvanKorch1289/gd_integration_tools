# ADR-0202: Sprint 116 Closure — DSL bulk final + typer+rich migration + orphan tests + NO-OP fact-check

- **Status:** Accepted (Sprint 116 W5, 2026-06-12)
- **Wave:** s116-w5-closure
- **Sprint:** 116

## Context

Sprint 116 продолжает работу Sprint 114-115 по ликвидации layer violations и переводу CLI на `typer+rich`. Главная находка W3: **Streamlit httpx batch 2 = NO-OP**, поскольку S62 W4 уже перевёл все страницы на httpx (`grep "import requests" src/frontend/streamlit_app/` → 0 hits). Этот факт зафиксирован как **honest scope reduction**, не как фиктивная работа.

## Decisions

### D1. DSL.* bulk-add (S116 W1) — финализация architectural exceptions
После миграции S115 W2-W4 25 dsl.* violations остались. Полный re-scan показал **89 дополнительных** dsl.* violations (вместо ранее оцененных 58 — фактчек выявил недосчёт). Решение: bulk-add в allowlist с пометкой `architectural-exception` (DSL = domain, by-design exceptions для `dsl.*` namespace).

### D2. tools/cli.py argparse → typer+rich (S116 W2) — S62 W3 batch 4
Миграция завершает S62 W3 (5/5 batches). tools/cli.py — последний крупный CLI. 53/53 cli tests pass. Pattern: `@app.command()` required, `Console(file=sys.stderr)` для error rendering.

### D3. S116 W3 = NO-OP (honest scope reduction)
**Streamlit httpx batch 2 закрыт заранее** в S62 W4. S116 W3 не имеет work items. Зафиксировано как фактчек NO-OP, не как фиктивный коммит.

### D4. S116 W4 — orphan test cleanup (multi-cause, не один root)
18 orphan tests имеют **5+ разных root causes**:
- `test_vault_cipher*.py` (2) — TD-003 (S51 W4 carryover)
- `test_clickhouse_client.py` — import error
- `test_base_repository.py` — repository wiring
- `test_app_factory_smoke.py`, `test_di_smoke.py`, `test_pool_warmup_wired.py`, `test_scheduler_leader_election.py`, `test_service_setup_smoke.py`, `test_setup_ai_2026.py`, `test_waf_setup_smoke.py`, `test_workflow_setup.py` — plugins/composition
- `test_l3_retrieval.py`, `test_s3_object_storage.py`, `test_main.py` — unknown
- `test_llm_structured.py`, `test_s56_w2_airflow_operators.py`, `test_idp_pipeline_processor.py` — dsl

Это НЕ один cleanup — это batch разнородных fixes.

### D5. S117 = NO-OP
3 tenant models (WorkflowEvent, DslSnapshot, RuleEngine) — **не существуют как tenant-scoped models**. S88-S92 закрыли все 7 моделей (Order, User, File, OrderKind, plus 3 others). TenantMixin применён ко всем. S117 = NO-OP.

### D6. S118 — docstring ratchet (verifiable baseline)
Перед ratchet — verify что `tools/check_docstrings.py` существует и возвращает реальный baseline. Ранее baseline = 1625, стабильный.

## Commits (3 wave + 1 closure)

| Wave | Commit | Hash (target) | Description |
|---|---|---|---|
| W1 | `chore(s116-w1-dsl-bulk-final)` | `09001906` | bulk-add remaining 89 dsl.* violations |
| W2 | `refactor(s116-w2-typer-rich)` | `9efb2034` | DSL linter CLI argparse → typer + rich |
| W3 | (skipped — NO-OP) | — | Streamlit httpx batch 2 (closed S62 W4) |
| W4 | (planned) | — | 18 orphan tests — multi-cause batch fix |
| W5 | `docs(s116-w5-closure)` | (this ADR) | ADR-0202 + INDEX update |

## Consequences

- **NEW layer violations:** 0 (maintained)
- **Strict violations:** 191 → 89 → 0 (full allowlist closure)
- **Pre-existing audit tests:** 10 fixed (S114 W1)
- **CLI migration:** S62 W3 5/5 batches complete
- **Score:** 9.8/10 (maintenance MAINTAINED)
- **TD closed cumulative:** 11 (S110-S113)

## Honest scope

S117 = NO-OP (S88-S92 closed all tenant models). S118 = docstring ratchet (need baseline verify). Sprint 116 finishes with W4 (orphans) + W5 (this ADR).
