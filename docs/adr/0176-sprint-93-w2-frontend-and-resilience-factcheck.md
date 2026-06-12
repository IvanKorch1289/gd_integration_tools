# ADR-0176: Sprint 93 Wave 2 — Frontend PATH + Docstring Ratchet + Resilience Fact-Check

**Status:** Accepted
**Date:** 2026-06-12
**Sprint:** 93 (Wave 2 of 5)
**Author:** Assistant (autonomous cycle, follow-up на S93 W1)

## Context

S93 W2 закрывает 3 задачи:
1. C11: sys.path.insert хаки в Streamlit
2. C15: docstring ratchet -10 (586 → 576)
3. C25/C26: FACT-CHECK — V2/юзер claim "4× CB дубликатов" + "4× retry" оба FALSE POSITIVES

W1 закрытие (ADR-0175) выявил, что V2/юзер-лист содержит устаревшие данные.
S87 reverification (ADR-0169) уже показал: V2 verdicts unreliable.
S93 W2 продолжает эту линию — verify каждое утверждение file:line.

## Решения

### W2-C11: Streamlit sys.path.insert → manage.py PYTHONPATH

**Проблема:** 3 файла (`app.py`, `31_DSL_Visual_Editor.py`, `86_DSL_Usage_Audit.py`)
использовали `sys.path.insert(0, str(_project_root))` хак. Анти-паттерн.

**Фикс:**
- `manage.py:run_frontend()` — теперь устанавливает `PYTHONPATH=$(pwd)` через
  `os.execvpe` (вместо `os.execvp` без env)
- 3 streamlit-файла — `sys.path.insert` удалён
- `86_DSL_Usage_Audit.py` — `ROOT` заменён на lazy `project_root` (cwd || parents[4])
- NOTE comments в каждом файле: "Запускать через `python manage.py run-frontend`"

**Trade-off:** Прямой `streamlit run` БЕЗ manage.py упадёт с ImportError.
Документировано.

**Validation:**
- `PYTHONPATH=$(pwd) python -c "from src.frontend...api_clients import get_api_client"` → OK
- 5 NEW regression тестов (3× no sys.path.insert + manage.py env + import resolve)

### W2-C15: Docstring ratchet -10 (586 → 576)

**Состояние:** 581 baseline (per DEEP-RESEARCH 2026-06-12), actual 586 per `wc -l`.

**S93 W2 scope:**
- `dsl/engine/processors/eip/marshal/formats.py`: 5 классов (Json/Xml/Csv/MessagePack/Pickle)
  × 4 метода + 4 `__init__` = 24 docstrings
- `dsl/engine/processors/streaming/windows.py`: 4 процессора (Tumbling/Sliding/Session/GroupByKey)
  × 1 `process()` = 4 docstrings

**Ratchet effect:** 586 → 576 (-10 net). Некоторые entries в allowlist были
stale (напр., `marshal.py` указывал на несуществующий файл — реально в `marshal/` dir).

**Next sprints:** target -10/sprint to amortize 576 → 0 в ~58 sprints.

### W2-C25/C26: FACT-CHECK — false positive identification

**Claim:** "4× CB дубликатов" + "4× retry модулей" (DEEP-RESEARCH + юзер).

**Verified 2026-06-12:**

| Concern | Canonical | Specialized variants | Total |
|---|---|---|---|
| **CB** | `core/resilience/breaker.py` (V22.10.2, ADR-005) | 1 deprecated shim + 1 facade + 1 per-route middleware | 4 (НЕ дубликаты) |
| **Retry** | `core/resilience/retry.py` (V16 single-entry) | 1 make_async_retry + 1 retry_budget + 1 ai-Pydantic + 1 saga-compensation | 5 (5 разных concerns) |

**Все 4 CB файла** имеют разные docstring-объяснения:
- canonical: single entry
- shim: deprecated, remove V24+
- facade: pre-registered breakers
- middleware: per-route, NO global state (S81 W1, исправление A2/ADR-005 bug)

**Все 5 retry файла** — разные concerns:
- `core/resilience/retry.py`: `@with_retry` decorator (tenacity)
- `infrastructure/resilience/retry.py`: `make_async_retry` factory (K3 W1)
- `core/resilience/retry_budget.py`: token bucket (защита от retry storm)
- `core/ai/retry_policy.py`: Pydantic BaseModel (config, no wrapper)
- `core/orchestration/retry.py`: `RetryWithCompensation` (Saga, durable state + compensate)

**Решение:** НЕ делать consolidation. 7 NEW regression-тестов фиксируют
canonical state и блокируют re-introduction дубликатов.

## Lessons Learned

1. **V2/юзер verdicts unreliable (3rd time confirmed)**: W1 — C3 (ConvertersMixin 13%),
   W2 — C25/C26 (CB/retry 4×). Каждый раз claim неточен.
2. **Docstring gate — working tool**: 586 → 576 через 28 docstrings (-10 net).
   Stale entries в allowlist указывают на старые пути — можно почистить.
3. **manage.py as launcher** — proper way для CLI tools с project-root imports.
   Альтернатива (conftest.py) не работает для runtime-CLI (только pytest).

## Метрики (W1 → W2)

| Метрика | S93 W1 | S93 W2 | Δ |
|---|---|---|---|
| Layer violations (new) | 0 | 0 | 0 |
| Layer violations (legacy) | 186 | 186 | 0 |
| Docstring violations | 586 | **576** | -10 |
| Tests passing (S93 NEW) | 13 | **29** | +16 |
| New false-positive findings | 1 (C3) | 2 (+C25/C26) | +1 |
| Atomic commits | 6 | **9** | +3 |

## Следующие шаги (S93 W3+)

- **W3:** AuthGateway facade (12+ locations → 1)
- **W4:** PollCDCBackend реализация, stdlib logging codemod (24+20 → 0)
- **W5:** DSL features (from_sse, fork_join, db_insert/upsert/delete) + closure

## References

- DEEP-RESEARCH 2026-06-12: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md`
- V2 P0: `analysis/v2/FINAL_REPORT_V2.md`
- ADR-0169 (S87 reverification): `docs/adr/0169-sprint-87-v2-p0-reverification.md`
- ADR-0175 (S93 W1): `docs/adr/0175-sprint-93-w1-cleanup-and-critical-fixes.md`
- Master prompt: `gap-analysis/MASTER-PROMPT-factcheck-plan-execute.md`
- Skill `verify-analysis-claims`: key anti-pattern detection
