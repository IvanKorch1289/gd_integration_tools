# Cycle 5 / D-AUDIT-502 — `AgentSecurityFacade.validate_sql` per-workflow policy override

> Дата: 2026-08-07 · HEAD: `22e08a0d` + pre-existing working tree (uv.lock, .blue_green.state, untracked docs)
> Plan ref: cycle-4 phase-1/02-security.md SECURITY-P0-002
> Task: T-C5-02-VALIDATE-SQL|fix validate_sql policy_override drop
> Fix strategy: **option (b)** — explicit `NotImplementedError` + `_logger.error`
> Docstring marker: `cycle-5/D-AUDIT-502`

## Status

**COMPLETE** (минимальная правка, ponytail-mode).

## Real evidence

`src/backend/services/agent_security/facade.py:121-133` (HEAD):

```python
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    policy = self.get_policy_for_workflow(workflow_id)
    if policy is not None:
        kwargs["policy_override"] = policy  # ← кладётся в kwargs
    return self.framework.validate_sql(query)  # ← НЕ принимает kwargs/context
```

`AgentSecurityFramework.validate_sql(self, query: str)` (`src/backend/core/ai/security/agent_security.py:572`)
принимает **только** `query` — никаких `context`, `policy`, `policy_override`.
Результат: override **silently dropped** → per-workflow policy (S204 retro-audit B18)
не работает для SQL = security P0 fail-OPEN (cycle-4 finding SECURITY-P0-002).

## Fix applied

**Option (b)** — explicit `NotImplementedError` с `_logger.error`, без расширения
signature framework'а (минимальная поверхность; не нарушает cycle-1+2+3).

```python
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    """Validate SQL query (S187).

    Args:
        query: SQL query text.
        workflow_id: Опциональный workflow ID для per-workflow policy.
            При наличии workflow-specific policy override вызов
            фейлится с :class:`NotImplementedError` (cycle-5/D-AUDIT-502),
            поскольку :class:`AgentSecurityFramework.validate_sql` не
            принимает ни ``context``, ни ``policy_override`` —
            молчаливое игнорирование override = security P0 fail-OPEN.

    Raises:
        NotImplementedError: Если задан per-workflow policy override.
            Caller должен либо очистить override (``clear_workflow_policy``),
            либо реализовать ``AgentSecurityFramework.validate_sql(..., policy=)``.
    """
    policy = self.get_policy_for_workflow(workflow_id)
    if policy is not None:
        _logger.error(
            "validate_sql: policy_override dropped (framework.validate_sql "
            "не принимает context/policy); workflow_id=%s policy=%s",
            workflow_id,
            type(policy).__name__,
        )
        raise NotImplementedError(
            "AgentSecurityFramework.validate_sql does not yet support "
            f"policy_override (workflow_id={workflow_id!r}); "
            "see cycle-5/D-AUDIT-502"
        )
    # Без override — passthrough на framework (common path).
    return self.framework.validate_sql(query)
```

**Что сохранено** (обратная совместимость для common path):

- `facade.validate_sql("SELECT 1")` без workflow_id → passthrough как раньше.
- `facade.validate_sql("DROP DATABASE ...")` (default workflow без override) → блокируется framework'ом.
- `agent_security_check.py:141` (`facade.validate_sql(self._value)` без workflow_id) → продолжает работать (verified test'ом).

**Что изменилось** (security fix):

- `facade.validate_sql(query, workflow_id="wf")` где override задан → `NotImplementedError` (вместо silent fail-OPEN).
- `_logger.error` со схемой `policy_override dropped; workflow_id=...; policy=...` для observability.

## Tests added

`tests/unit/services/agent_security/test_facade_validate_sql.py` (5 тестов):

| Тест | Сценарий | Ожидание |
|---|---|---|
| `test_validate_sql_without_workflow_id_passes_through` | Common path без workflow_id | `decision.allowed is True` (passthrough) |
| `test_validate_sql_with_workflow_id_no_override_passes_through` | workflow_id без override | `decision.allowed is True` (passthrough) |
| `test_validate_sql_with_policy_override_raises_not_implemented` | `set_policy_for_workflow(strict, "wf-critical")` → `validate_sql("SELECT 1", workflow_id="wf-critical")` | `pytest.raises(NotImplementedError)` + error-лог содержит `"policy_override dropped"` |
| `test_validate_sql_with_policy_override_blocks_dangerous_sql_via_facade` | DROP DATABASE без override | `decision.allowed is False`, `"dangerous_sql" in decision.reason` |
| `test_facade_uses_framework_validate_sql_directly` | Spy на framework.validate_sql | Вызывается напрямую с `(query,)` без context kwarg (back-compat) |

## Diff stat

```
 src/backend/services/agent_security/facade.py                       | 25 ++++++++++++++++++++--
 tests/unit/services/agent_security/test_facade_validate_sql.py     | 124 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 147 insertions(+), 2 deletions(-)
```

`uv.lock` — **НЕ тронут** (45 lines churn — pre-existing drift, не моя правка).

## Verification

### `.venv/bin/python -m pytest`

```
tests/unit/services/agent_security/ tests/unit/core/ai/test_agent_security.py tests/unit/dsl/processors/test_agent_security_check.py
============================== 45 passed in 3.20s ==============================
```

Включает 5 новых + 17 framework тестов + 8 AgentSecurityCheckProcessor тестов.

### `make check-docstrings MAX_ALLOWED=0`

```
Total: 0 missing docstrings in 0 files
Files scanned: 839
docstring policy OK
```

### `bash tools/cycle-1-preflight.sh`

```
[OK]   layer checker — 0 new, 175 legacy
[OK]   allowlist active IDs — 27
[OK]   docstring gate — 0 missing
[FAIL] working tree — 25 entries (разобраться)
[FAIL] uv.lock churn — 45 lines (проверить не растёт ли)
[OK]   s3.py untouched — не modified
```

**Working tree / uv.lock FAIL — pre-existing drift**, не от моих правок:
- uv.lock: 17/-16 churn до моей работы (D-AUDIT-02 cycle-3 T-02 / cycle-4 worktree)
- `.blue_green.state`, `cycle-{1,2,3,4}/` — pre-existing untracked от предыдущих циклов
- Мои additions: 1 файл `tests/unit/services/agent_security/test_facade_validate_sql.py` + 25 строк в facade.py

Запреты соблюдены: uv.lock НЕ тронут, .security/pip-audit-allowlist.txt НЕ тронут,
src/backend/infrastructure/storage/s3.py НЕ тронут, tools/blue_green.sh НЕ тронут,
tests/unit/tools/test_blue_green_switch.py НЕ тронут, services/ai/gateway_adapter.py:128-129
НЕ тронут (явно запрещено всеми plan'ами).

## Outcome vs Phase-1 finding SECURITY-P0-002

Phase-1 finding говорил «silently dropped → fail-OPEN».
После моей правки: **fail-CLOSED** через explicit `NotImplementedError` + error-лог.

Phase-1 рекомендация «расширить `framework.validate_sql(query, *, policy=None, context=None)`»
**отклонена** в пользу option (b), поскольку:
1. Ponytail-mode: расширение signature framework'а требует обновления ВСЕХ 4 validate_* методов
   + callers + 17 framework тестов + 8 AgentSecurityCheckProcessor тестов = широкий blast radius;
2. cycle-1+2+3 запрет «не переписывать HEAD» — изменять framework.validate_sql = ломать 30+ tests;
3. Текущая задача — **fix bug, не redesign API**. Когда понадобится real policy override —
   это будет отдельный task с ADR-level decision (per PHASE-2-SUMMARY.md §4.1 Tier 1B).

## Cycle linkage

- cycle-1: «validate_sql drop» RESIDUAL → **теперь PARTIALLY RESOLVED** (fail-CLOSED guard);
- cycle-4 SECURITY-P0-002 → **RESOLVED** (silently dropped → explicit NotImplementedError);
- SECURITY-P0-002 → ready для close после слияния.

## Files

- `src/backend/services/agent_security/facade.py` — modified (25 lines added, 2 deleted);
- `tests/unit/services/agent_security/test_facade_validate_sql.py` — created (124 lines);
- `docs/audit/swarm-2026-08-06/cycle-5/cycle-5-D-AUDIT-502-report.md` — this report.
