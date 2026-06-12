# ADR-0149 — TD-S65-W2 audit: 34 core→other violations classified + 1 sample refactor (RetryPolicy)

* Статус: Accepted (Autonomous work cycle S68 W2, 2026-06-12)
* Связано с: S65 W2 (initial 35 violation detection), S68 W2 (this refactor)
* Working dir: /home/user/dev/gd_integration_tools

## Контекст

S65 W2 фактчек показал: **35 lazy imports** из `core/` в `services/`,
`infrastructure/`, `entrypoints/`. Все попали в `tools/check_layers_allowlist.txt`.

S68 W2 — рефакторинг архитектурного долга. Subagent выполнил investigation
(read allowlist, classify по tier), но **не сделал execution phase** —
достигнут `max_iterations=50` на стадии planning. Orchestrator взял
execution phase вручную (`subagent-parallel-coverage-batch` skill, pitfall #49).

## Tier classification (subagent's investigation)

| Tier | Count | Примеры | S68 W2 подход |
|---|---|---|---|
| **Tier 1 (XS)** | 4 | `core/ai/agent_registry.py:113` (lazy `RetryPolicy`); `core/ai/agent_spec.py:173` (same import mislocated at EOF); `core/ai/pydantic_ai_client.py:360,363` (lazy `GatewayRateLimited/GatewayUnavailable`) | S68 W2: 2/4 fixed (RetryPolicy move) |
| **Tier 2 (S)** | 6+ | `core/ai/gateway_pipeline_mixin/*.py` (4 mixin-файла, каждый 1 dep); `core/ai/policy/enforcer/input_guard_mixin.py` (2 deps) | S69+ backlog |
| **Tier 3 (M)** | 3+ | `core/di/providers/ai.py` (3 deps — god-DI provider); `core/messaging/dlq.py` (2 deps); `core/scaling/bulkhead_scaler.py` (2 deps) | S70+ backlog |
| **Tier 4 (L, skip)** | 3+ | `core/auth/ldap_client_factory.py` (full AdDirectoryClient import); `core/di/providers/cache.py` (entrypoints crossing); `core/interfaces/ratelimit_gateway.py` (entrypoints) | Deferred to P1 epic |

**Распределение по target-слою:**
- core → dsl.workflow.spec: 2 entries (S68 W2 fixed)
- core → services.*: 16 entries
- core → infrastructure.*: 15 entries
- core → entrypoints.*: 1 entry

## Sample refactor: RetryPolicy move

**Files changed (5):**
1. `src/backend/core/ai/retry_policy.py` (NEW, 47 LOC): verbatim copy of
   `RetryPolicy` class из `dsl/workflow/spec/policies.py:36-61`.
2. `src/backend/dsl/workflow/spec/policies.py` (`RetryPolicy` re-export
   с `# noqa: E402` для backward compat).
3. `src/backend/core/ai/agent_spec.py:173`: `from src.backend.core.ai.retry_policy
   import RetryPolicy` (теперь top-of-file import с `# noqa: E402` для
   bottom-of-file positioning).
4. `src/backend/core/ai/agent_registry.py:113`: lazy import заменён на
   `from src.backend.core.ai.retry_policy import RetryPolicy` (внутри
   метода — function-local import сохраняется для circular safety).
5. `tools/check_layers_allowlist.txt`: 2 entries удалены (S68 W2 closed
   these violations). Total 201 → 199.

**Tests (1 NEW, 9 tests):**
- `tests/unit/core/ai/test_retry_policy.py` (9 tests):
  1. `test_retry_policy_importable_from_core_ai`
  2. `test_retry_policy_backward_compat_via_dsl`
  3. `test_retry_policy_defaults`
  4. `test_retry_policy_custom_values`
  5. `test_retry_policy_max_attempts_must_be_positive`
  6. `test_retry_policy_backoff_must_be_at_least_one`
  7. `test_retry_policy_jitter_bounded`
  8. `test_retry_policy_extra_forbid`
  9. `test_retry_policy_serialization_roundtrip`

Verified: 9/9 NEW + 0 regression в `tests/unit/core/ai/`.
ruff clean.

## Honest scope (S68 W2)

- **Fixed**: 2/35 violations (Tier 1, RetryPolicy). Allowlist 201 → 199.
- **Remaining**: 33 violations (Tier 2-4).
- **Sample chosen because**:
  - Class is self-contained (6 Pydantic fields, ZERO internal deps)
  - Both usages are lazy/imported-once, easy to flip
  - Trivial to test (defaults, constraints, serialization)
  - Backward compat guaranteed via dsl re-export

## S69+ backlog (33 remaining core→other violations)

| Tier | Count | Estimated effort | Suggested sprint |
|---|---|---|---|
| Tier 1 (XS) | 2 | 1 sprint | S69 W1 |
| Tier 2 (S) | 6+ | 2-3 sprints | S69 W2-3 |
| Tier 3 (M) | 3+ | 2 sprints | S70 |
| Tier 4 (L) | 3+ | 1-2 quarters | Deferred to P1 epic |

**Best next candidates (Tier 1):**
- `core/ai/pydantic_ai_client.py:360,363` — lazy `GatewayRateLimited`/
  `GatewayUnavailable` exceptions. These are likely exception classes
  in `core/exceptions.py` or similar. Trivial to make top-level imports
  (or move exceptions to `core/exceptions.py` if not already there).

## Lessons learned

1. **Subagent did investigation (40%), orchestrator did execution (60%)** —
   classic pitfall #49 from `subagent-parallel-coverage-batch` skill.
   Investigation produced tier classification + best candidate identification.
   Orchestrator executed the actual refactor + tests + allowlist update.

2. **`__all__` accuracy matters** — subagent/investigation didn't have
   `__all__` (it was missing). When I added `__all__` for the re-export,
   I incorrectly included `IdempotencyPolicy` и `TimeoutPolicy` (которые
   НЕ существуют в этом файле — only `SlaPolicy` и `MemoryScope` are
   real classes здесь). F822 error caught by ruff. Fix: enumerated real
   classes, fixed `__all__`.

3. **E402 baseline** — `policies.py` уже имел E402 errors (imports after
   docstring) pre-existing. My refactor didn't introduce them, but I
   added `# noqa: E402` для consistency (чтобы мой новый import не
   репортился как new E402).

4. **Backward compat via re-export** — moving class entirely would break
   ~10+ existing imports. Re-export pattern (class lives in new location,
   `from new import X` in old location) maintains zero-call-site-change
   refactor. Subagent suggested this; orchestrator executed it.

5. **Function-local imports in agent_registry.py preserved** — even
   though we moved `RetryPolicy` в core, agent_registry keeps
   `from src.backend.core.ai.retry_policy import RetryPolicy` ВНУТРИ
   метода (function-local) для circular import safety. Class-level
   import would be safe now, но существующий pattern оставлен (minimal
   change, S68 W2 scope discipline).
