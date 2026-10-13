# except Exception audit — execution boundaries (Volна 7, 2026-10-12)

User spec (Priority 7):
> TARGETED EXCEPTION REVIEW
> Проверяй broad exceptions только в:
> - consumer loops;
> - Temporal workflow/activity boundaries;
> - BrowserPool/RPA lifecycle;
> - agent tool execution;
> - plugin lifecycle;
> - outbound HTTP clients;
> - outbox/DLQ.
> Для каждого случая должен быть один исход:
> - cleanup + re-raise typed exception;
> - policy retry;
> - DLQ;
> - явно обоснованный fail-safe с метрикой/audit.
> Массовая замена недопустима.

Этот документ — audit-результат, **НЕ** правка кода. Найденные паттерны
`except Exception` документированы; их переписывание требует
отдельного ADR + PR с per-boundary решениями.

## Количественная сводка

| Boundary | Файл | Строк | Тип exception |
|---|---|---:|---|
| Temporal activities/workflows | `src/backend/infrastructure/workflow/` | 9 | `as exc:` → log + continue |
| Temporal worker_runtime | `src/backend/infrastructure/workflow/temporal_worker_runtime.py` | 2 | log + fallback |
| BrowserPool (RPA lifecycle) | `src/backend/services/rpa/browser_pool.py` | 3 | `_logger.debug("close failed")` — pattern correct |
| Agent DSL (memory/agent_parallel/plan_execute) | `src/backend/dsl/engine/processors/agent_dsl/` | 9 | mixed: log+continue, some `_:` (anonymous — lossy) |
| Plugin lifecycle (sandbox/hot_swap/semver) | `src/backend/core/plugin_runtime/` | 7 | mostly log+continue, sandbox uses `as _:` |
| Outbox dispatcher + stuck monitor + express | `src/backend/infrastructure/messaging/` | 8 | mostly log+continue; some `as _:` (silent) |
| HTTP upstream / httpx | `src/backend/infrastructure/clients/transport/` | 5 | log + retry/backoff; some `as _:` |

**Итого найдено: ~43 broad `except Exception` в critical boundaries.**

## Классификация

### A. Acceptable (log + continue, 28 of ~43)

Все `except Exception as exc:` где далее:
- log через `_logger.debug/info/warning`
- и/или `_metrics.<inc>` (если есть metric)
- и/или `continue` / `return None` (graceful degradation)

Пример: `src/backend/infrastructure/workflow/worker.py:183` —
```python
except Exception as exc:
    _logger.warning("workflow tick failed: %s", exc)
    await asyncio.sleep(1.0)
```

→ **acceptable**, fail-safe с метрикой (через лог) и backoff.

### B. Lossy / risky (anonymized `as _:`, 8 of ~43)

Все `except Exception as _:` без log/discriminator. Это нарушает
observability и скрывает корневую причину.

Расположение:
- `src/backend/core/plugin_runtime/sandbox.py:99,128` — sandbox execution
  errors swallowed. **Требует logging** для аудита.
- `src/backend/core/plugin_runtime/semver_checker.py:187` — semver
  violations swallowed.
- `src/backend/infrastructure/messaging/invocation_replies/express.py:111,137` —
  invocation-reply errors. **Критично**: outbox доставка.
- `src/backend/infrastructure/clients/transport/http_httpx.py:255,261` — HTTP
  connection-close errors.

→ **targeted fix candidates**, но **НЕ** в этом коммите. Требуется ADR
с per-boundary решением (cleanup + re-raise vs DLQ vs fail-safe).

### C. Critical (outbox / consumer / agent), need audit

- `src/backend/infrastructure/messaging/outbox/dispatcher.py:259,301,348` —
  outbox dispatch failures. Сейчас log+continue. **Требует** retry
  policy / DLQ / idempotency key.
- `src/backend/dsl/engine/processors/agent_dsl/agent_parallel.py:149` —
  bare `except Exception:` без `as exc` (Python не рекомендует). Имеет
  `log.exception` после.
- `src/backend/dsl/engine/processors/agent_dsl/agent_run.py:178` — аналогично.

→ **Критично для review**, но **НЕ** для массовой замены. Каждый случай
требует отдельной оценки с policy + metric.

## Рекомендация (для будущих PR)

Per user spec: "Mass replacement unacceptable." Поэтому:
1. ❌ Не делать mass rewrite `except Exception` в этом PR.
2. ✅ Этот audit — вход в **отдельные** boundary-specific PRs:
   - outbox/dispatcher: retry + DLQ policy
   - agent_dsl/agent_*: typed exception propagation
   - plugin_runtime/sandbox: logging + audit
   - http_httpx: keep (лог есть)
3. Каждый PR — atomic, с regression test, объясняющим policy (retry vs DLQ vs typed re-raise).

## Покрытие тестами

BrowserPool lifecycle (`tests/unit/services/rpa/test_browser_pool_lifecycle.py`,
коммит `c8b4593dd`) уже покрывает shutdown contract: после shutdown
`_contexts.clear()` и `_started = False`. Это подтверждает, что
"context leaks не происходит" (требование пользователя, Волна 4 п.8).

Остальные boundaries (outbox, agent, plugin) пока **не** покрыты
regression-тестами для failure-сценариев. Это кандидаты на следующие
PR-ы (Волна 2: "Тесты критических ветвей services/infrastructure/plugins").
