# Cycle 1 · Phase 3 — Plan (минимальный и исполнимый)

**Дата:** 2026-08-06
**Baseline commit:** `b69d6b49bc62918a02e47dc20ab81615fd8500b1`
**HEAD на момент планирования:** требует preflight (см. T-0.1; ожидаемо `2f620910951a727f50d4539b998375b0c0bda55d` — 1 коммит после baseline)
**Источник:** только `docs/audit/swarm-2026-08-06/cycle-1/BASELINE.md` + `docs/audit/swarm-2026-08-06/cycle-1/PHASE-2-SUMMARY.md`. Source/test/git diff/Phase 1 отчёты — НЕ читал.
**Scope:** cycle 1, Phase 3 — план на **8 задач**: 1 preflight + 5 P0 + 1 P1 + 1 P3 + 1 P4.
**Не закрыто в cycle 1:** ~205 findings (32 P0, 56 P1, 61 P2, 28 P3, 28 P4) — полный список в §6.

> **Честные оговорки (Phase 2 summary §1 / §10.4, BASELINE §"Ограничения"):**
> 1. **Source не читал.** Все пути и описания взяты из `PHASE-2-SUMMARY.md`.
>    Developer ОБЯЗАН выполнить T-0.1 preflight и подтвердить, что пути
>    соответствуют текущему HEAD (после concurrent activity).
> 2. **HEAD diverged.** Phase 2 summary зафиксировал `2f620910951a727f50d4539b998375b0c0bda55d`
>    (1 коммит после baseline: S183 W2 #1, S3 multipart abort). Любая задача
>    должна работать на актуальном HEAD, не на baseline.
> 3. **Working tree contradiction (§5.1).** BASELINE говорит `s3.py + uv.lock`;
>    6 агентов Phase 1 через `git status --short` видели
>    `pyproject.toml + tests/unit/dsl/transforms/test_dataframes.py`.
>    **Нужна preflight-верификация** обоих утверждений.
> 4. **12 разных формул readiness (§5.4).** Числа self-assessed несопоставимы.
>    Этот план опирается на нормализованные finding IDs, не readiness-числа.
> 5. **Не доверять журналам без проверки source** (BASELINE §"Ограничения").

---

## 0. Общие gates (для всех задач cycle 1)

Эти gates проверяются на T-0.1 (полный preflight) и **перед каждой задачей**
как минимальный preflight script (см. T-0.1 §"Пере-используемый preflight script").

| Gate | Baseline | Цикл 1 gate | Команда |
|---|---|---|---|
| Layer checker | `175 legacy`, `0 new` | **no-growth**: legacy ≤ 175, new = 0 | `python tools/check_layers.py --root src` |
| Active security allowlist | `35 active IDs` (НЕ 37; BASELINE §"Security allowlist" + §5.2) | **no-new-CVE**: новых строк ≤ 0; удалять разрешено только stale | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` |
| Pre-existing dirty tree | `s3.py + uv.lock` (BASELINE) — но см. §5.1 | **не роутить uv.lock**; `s3.py` — только если задача явно требует | `git status --short` |
| Docstring gate | `0 missing` (FW7 ratchet complete) | **остаётся 0** | `make check-docstrings MAX_ALLOWED=0` |
| Mocks vs real runtime | (n/a) | **не подменять моки реальным кодом**; **xfail-тесты должны стать passing** (8 готовых для SSE) | `pytest --strict-markers -m xfail` |
| `except Exception` (BASELINE §"Ограничения" + DLQ pattern) | (n/a) | **запрещено удалять** без concrete handling + `logger.error(...)` ИЛИ `DLQWriter.enqueue(...)` | manual review в PR |
| Русские docstrings | (BASELINE §"Ограничения") | **не переводить** | manual review в PR |

> **Предупреждение по uv.lock:** pre-existing `uv.lock` diff — НЕ предписывать
> его роутить (BASELINE явно: "не трогать без явной необходимости"). Любая
> dependency change в T-3.1 использует **stdlib** или библиотеку **уже
> зафиксированную** в `pyproject.toml` lockfile.

---

## 1. Wave 0 — Developer preflight (обязательный gate)

### T-0.1 — Preflight verification против текущего HEAD

**Finding IDs:** n/a (preflight gate, не закрывает finding)
**Priority:** n/a (gate; блокирует все остальные задачи)
**Domain:** process / cross-cutting
**Паттерн:** evidence preservation (per BASELINE §"Ограничения")

**Что делать (минимальный diff; 1 новый файл):**

1. `git rev-parse HEAD` — зафиксировать текущий HEAD; ожидаемо
   `2f620910951a727f50d4539b998375b0c0bda55d` (1 после baseline) ИЛИ
   `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (если concurrent activity
   откатилась). Если иначе — STOP, эскалация.
2. `git status --short` — зафиксировать pre-existing modifications;
   ожидаемо один из вариантов (см. §5.1):
   - `s3.py + uv.lock` (BASELINE)
   - `pyproject.toml + tests/unit/dsl/transforms/test_dataframes.py` (то,
     что видели 6+ агентов Phase 1)
   **Любой другой список — STOP.**
3. `python tools/check_layers.py --root src` — exit 0; legacy = 175,
   new = 0. Зафиксировать baseline в PREFLIGHT-REPORT.
4. `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` —
   должно быть **35** (НЕ 37 — комментарий пользователя не подтверждён).
   Если 37 — зафиксировать расхождение.
5. `make check-docstrings MAX_ALLOWED=0` — exit 0.
6. `pytest --collect-only -q -m xfail | head -50` — зафиксировать список
   xfail-тестов; **T-1.2 требует снять 8 xfailed SSE-тестов**.
7. **Создать пере-используемый preflight script** `tools/cycle-1-preflight.sh`,
   повторяющий шаги 1–6 в exit-code-only режиме — developer запускает его
   перед каждой последующей задачей T-1.* / T-2.* / T-3.* / T-4.*.
8. **Запрещено** на preflight: любые изменения в source/test/lockfile/docs
   кроме `PREFLIGHT-REPORT.md` и `tools/cycle-1-preflight.sh`.
9. **Запрещено** мерджить PR любой задачи до завершения T-0.1 — это gate
   для всех остальных задач.

**Пути файлов:**

- *Новые:*
  - `docs/audit/swarm-2026-08-06/cycle-1/PREFLIGHT-REPORT.md` (новый, ~50 LOC)
  - `tools/cycle-1-preflight.sh` (новый, ~30 LOC; bash, exit 0/1)
- *Read-only verification:*
  - `tools/check_layers.py`
  - `.security/pip-audit-allowlist.txt`
  - `Makefile` (для `make check-docstrings`)
- *Source/test/lockfile:* **не трогать**.

**Dependencies:** нет.
**Параллельно с:** ни с чем (gate).
**LOC:** 0 source change; 2 новых файла (~80 LOC).
**Готово когда:**
- `PREFLIGHT-REPORT.md` существует и заполнен;
- `tools/cycle-1-preflight.sh` существует, `bash tools/cycle-1-preflight.sh` exit 0;
- HEAD = один из ожидаемых (зафиксирован);
- working tree status зафиксирован (любой из 2 ожидаемых вариантов);
- layer check baseline зафиксирован (175/0);
- allowlist count = 35 (или расхождение зафиксировано);
- xfail-список зафиксирован;
- docstring gate = 0.

**Rollback:** n/a (только чтение + 2 новых файла).
**Docstring marker:** n/a.

---

## 2. Wave 1 — Security/Reliability P0 (5 задач)

### T-1.1 — Composition root crash (composition-root DI)

**Finding IDs:**
- `business-logic:DOMAIN-P0-001` (`core/di/module_registry.py:136-137` + `core/di/providers/db.py:53-58`)
- `business-logic:DOMAIN-P0-002` (`plugins/composition/workflow_setup.py:76-83`)
- `api:API-P0-003` (`entrypoints/api/generator/setup.py:12-14`)
- `workflow:DOMAIN-WF-P0-003` (`dsl/workflow/compiler/activity_bridge.py:155-169` + `infrastructure/workflow/worker.py:225-301`)

**Priority:** P0
**Domain:** business-logic + api + workflow (3 домена)
**Паттерн:** composition-root DI

**Что менять (минимальный diff):**

1. `src/backend/core/di/module_registry.py:136-137` — удалить/закомментировать
   mapping `repos.files` и `repos.orders` (ведут на несуществующие модули;
   extensions должны импортировать свои repo-модули напрямую — composition
   root не должен знать о contents extensions).
2. `src/backend/plugins/composition/workflow_setup.py:76-83` — убрать импорты
   несуществующих `extensions.core_entities.orders.workflows.orders_saga` и
   `extensions.credit_pipeline.workflows.payments_saga`. Если saga-модули не
   реализованы — `logger.warning(...)` с actionable сообщением (НЕ bare `pass`).
3. `src/backend/entrypoints/api/generator/setup.py:12-14` — удалить dead
   import `src.backend.workflows.workflows_service`; проверить, что
   `register_action_handlers()` не падает.
4. `src/backend/infrastructure/workflow/worker.py:225-301` — вызвать
   `register_langgraph_checkpoint_activities` после создания Temporal Worker.

**Пути файлов:**

- *Implementation:*
  - `src/backend/core/di/module_registry.py`
  - `src/backend/plugins/composition/workflow_setup.py`
  - `src/backend/entrypoints/api/generator/setup.py`
  - `src/backend/infrastructure/workflow/worker.py`
  - `src/backend/dsl/workflow/compiler/activity_bridge.py` (read-only verification)
- *Tests:*
  - `tests/unit/core/di/test_module_registry.py` (extend: composition root smoke)
  - `tests/integration/workflow/test_activity_bridge_wiring.py` (new, xfail→pass)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-B-01-report.md` (новый)

**Dependencies:** нет (формально). T-1.3 частично использует результат T-1.1
(OutboxBackend DI injection упрощается), но T-1.3 не блокируется.
**Параллельно с:** T-1.2, T-1.3, T-1.4, T-1.5, T-2.1, T-3.1, T-4.1.
**Рекомендуется первым в Wave 1**, потому что composition root fix разблокирует
`python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"`
как smoke-тест для остальных веток.
**LOC:** ~30-50 source; +1 integration test ~50 LOC.
**Готово когда:**
- `python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"` exit 0;
- `python tools/check_layers.py --root src` exit 0, legacy ≤ 175, new = 0;
- `pytest tests/integration/workflow/test_activity_bridge_wiring.py -v` exit 0;
- `pytest tests/unit/core/di/test_module_registry.py -v` exit 0.

**Rollback:** revert коммита; composition root снова падает, но это восстановимое
baseline поведение.
**Docstring marker:** `cycle-1/B-01` в затронутых русских docstrings (НЕ переводить).
**Compatibility risk:** low (composition root сейчас сломан — fix восстанавливает baseline).

---

### T-1.2 — SSE/HITL auth gap (pure ASGI)

**Finding IDs:**
- `entrypoints:DOMAIN-P0-001` (`entrypoints/sse/handler.py:188-236` — 8 xfailed TDD-тестов готовы)
- `api:API-P0-004` (`entrypoints/api/v1/endpoints/hitl.py:24-129`)
- `security:DOMAIN-P0-002` (`entrypoints/middlewares/auth_required.py:177-182`)

**Priority:** P0
**Domain:** entrypoints + api + security (3 домена)
**Паттерн:** pure ASGI

**Что менять:**

1. `src/backend/entrypoints/middlewares/auth_required.py:177-182` — заменить
   deprecated-shim import `entrypoints/api/dependencies/auth_selector.verify_request`
   на canonical импорт (S99+ single-point-of-failure при удалении shim).
2. `src/backend/entrypoints/sse/handler.py:188-236` — extract `principal`/
   `permissions` из `request.state.auth` (ASGI scope set by middleware),
   прокинуть в `dispatch_action_or_dsl`. Снять 8 xfailed TDD-тестов.
3. `src/backend/entrypoints/api/v1/endpoints/hitl.py:24-129` — добавить
   router-level `dependencies=[Depends(require_auth(...))]` + permission check.
   Убрать docstring-ложь про JWT (не переводя существующие русские).

**Пути файлов:**

- *Implementation:*
  - `src/backend/entrypoints/middlewares/auth_required.py`
  - `src/backend/entrypoints/sse/handler.py`
  - `src/backend/entrypoints/api/v1/endpoints/hitl.py`
- *Tests:*
  - `tests/unit/entrypoints/sse/test_handler.py` (снять 8 xfailed)
  - `tests/unit/entrypoints/api/v1/endpoints/test_hitl.py` (new, ≥3 auth cases)
  - `tests/unit/entrypoints/middlewares/test_auth_required.py` (extend)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-B-02-report.md`

**Dependencies:** нет.
**Параллельно с:** T-1.1, T-1.3, T-1.4, T-1.5, T-2.1, T-3.1, T-4.1.
**Conflict-area:** единственная задача, трогающая `auth_required.py` —
merge первым среди security-веток.
**LOC:** ~30-50 source; ~80 LOC tests.
**Готово когда:**
- `pytest tests/unit/entrypoints/sse/test_handler.py -v -m xfail` → 0 xfailed (8 сняты);
- `pytest tests/unit/entrypoints/api/v1/endpoints/test_hitl.py -v` exit 0;
- `grep -rn "auth_selector.verify_request" src/` → 0 hits (deprecated shim убран).

**Rollback:** revert; SSE/HITL снова unprotected — но это текущее baseline
поведение, не регрессия относительно baseline.
**Docstring marker:** `cycle-1/B-02`.
**Compatibility risk:** medium (auth — breaking change для незащищённых callers;
**требуется feature flag или gradual rollout**, например через существующий
`tenancy.require_auth` или env-toggle `auth_required_strict=true`).

---

### T-1.3 — MQ DLQ bypass (canonical DLQ + logger.error, DATA-LOSS)

**Finding IDs:**
- `entrypoints:DOMAIN-P0-002` (`entrypoints/stream/subscribers.py:21-51`,
  `entrypoints/stream/invoker_subscribers.py:57-93`)
- cross-corr `services:DOMAIN-P2-005` (DLQ silent_loss в audit) — НЕ закрывается
  в этом PR, оставлен для cycle 2

**Priority:** P0 (data-loss path)
**Domain:** entrypoints
**Паттерн:** canonical DLQ envelope + `logger.error(...)`

**Что менять:**

1. `src/backend/entrypoints/stream/subscribers.py:21-51` — при exception в
   handler'е enqueue в `OutboxBackend` через `DLQWriter` Protocol (canonical
   envelope из `infrastructure.messaging.dlq.dlq_base:61-99`), **не** ack'ать
   сразу.
2. `src/backend/entrypoints/stream/invoker_subscribers.py:57-93` — то же.
3. Добавить `logger.error(..., extra={"poison_message": ..., "tenant_id": ...})`
   перед enqueue.
4. **Запрещено** (§0 + user constraints) удалять `except Exception` без
   concrete handling — текущие `except Exception: pass` блоки должны быть
   заменены на
   `except Exception as e: logger.error(...); await dlq_writer.enqueue(...)`.

**Пути файлов:**

- *Implementation:*
  - `src/backend/entrypoints/stream/subscribers.py`
  - `src/backend/entrypoints/stream/invoker_subscribers.py`
  - `src/backend/core/messaging/outbox.py` (read-only verification)
  - `src/backend/infrastructure/messaging/dlq/dlq_base.py` (read-only verification)
- *Tests:*
  - `tests/integration/entrypoints/stream/test_subscribers_dlq.py` (new, **REAL runtime**, НЕ mock DLQ)
  - `tests/unit/entrypoints/stream/test_invoker_subscribers.py` (extend, mock DLQWriter Protocol)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-B-03-report.md`

**Dependencies:** частичная на T-1.1 (OutboxBackend DI injection). Если
T-1.1 уже сделан — DI упрощается; если нет — допустимо использовать
существующий `core.messaging.outbox` через module-level lookup (но это
нарушит no-new-module-level-import — задокументировать trade-off).
**Параллельно с:** T-1.1 (желательно merge T-1.1 первым), T-1.2, T-1.4, T-1.5,
T-2.1, T-3.1, T-4.1.
**LOC:** ~30-50 source; ~80 LOC integration test.
**Готово когда:**
- `pytest tests/integration/entrypoints/stream/test_subscribers_dlq.py -v` exit 0;
- integration test enqueues **реальное** сообщение в DLQ backend (НЕ mock;
  если backend недоступен — test помечается `@pytest.mark.xfail(reason="real DLQ backend required")` и заносится в `RAG-RUNTIME-REPORT.md` аналог — `DLQ-RUNTIME-REPORT.md`);
- `grep -nE "except Exception.*:\s*pass" src/backend/entrypoints/stream/` → 0 hits;
- `grep -nE "logger.error.*poison_message" src/backend/entrypoints/stream/` → ≥2 hits.

**Rollback:** revert; data-loss path восстановлен, но это текущее baseline
поведение.
**Docstring marker:** `cycle-1/B-03` (data-loss fix).
**Compatibility risk:** low (data-loss fix — current behavior broken, fix
restores baseline guarantees).

---

### T-1.4 — DSL Multicast TypeError + Python-2 syntax (per-plugin lifecycle)

**Finding IDs:**
- `dsl:DOMAIN-P0-001` (`dsl/engine/processors/eip/routing/multicast.py:172`)
- `dsl:DOMAIN-P0-002` (`dsl/engine/processors/eip/reliability/redelivery_policy.py:145`)

**Priority:** P0
**Domain:** DSL
**Паттерн:** per-plugin lifecycle patterns

**Что менять:**

1. `src/backend/dsl/engine/processors/eip/routing/multicast.py:172` — убрать
   `route_registry=...` kwarg из `ExecutionEngine(...)` (kwarg не существует;
   все unit-тесты мокают — production упадёт с TypeError).
2. `src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py:145`
   — заменить Python-2 `except TypeError, ValueError:` на
   `except (TypeError, ValueError):`.

**Пути файлов:**

- *Implementation:*
  - `src/backend/dsl/engine/processors/eip/routing/multicast.py`
  - `src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py`
- *Tests:*
  - `tests/unit/dsl/engine/processors/eip/routing/test_multicast.py`
    (extend: real `ExecutionEngine` — **не** mock constructor)
  - `tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py`
    (extend: ValueError path)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-B-04-report.md`

**Dependencies:** нет.
**Параллельно с:** всеми.
**LOC:** ~5-10 source; ~30 LOC tests.
**Готово когда:**
- `pytest tests/unit/dsl/engine/processors/eip/routing/test_multicast.py -v` exit 0 (no TypeError);
- `pytest tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py -v` exit 0;
- `python -c "import ast; ast.parse(open('src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py').read())"` exit 0.

**Rollback:** revert.
**Docstring marker:** `cycle-1/B-04`.
**Compatibility risk:** low (current code broken на Python 3.14; fix restores
baseline behavior).

---

### T-1.5 — AIGateway capability TypeError + bare fallback (composition-root DI + tenant ContextVar)

**Finding IDs:**
- `agents:DOMAIN-P0-001` (`core/ai/gateway_pipeline_mixin/policy_mixin.py:100`)
- `agents:DOMAIN-P0-002` (`services/ai/gateway_adapter.py:130`)

**Priority:** P0
**Domain:** agents
**Паттерн:** composition-root DI + tenant ContextVar/post-filter

**Что менять:**

1. `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:100` —
   `_check_capability` вызывает `gate.check(capability)` с 1 аргументом;
   исправить на
   `gate.check(layer="core", capability=capability, workflow_id=request.workflow_id)`
   в `try/except TypeError` с `logger.error(...)`.
2. `src/backend/services/ai/gateway_adapter.py:130` — fallback
   `return AIGateway()` без DI заменить на composition-root DI lookup;
   если DI не удаётся — `raise` вместо silent return (или feature flag
   `dev_only_bare_gateway`, по умолчанию OFF в dev/staging).
3. Использовать `tenant_id` из `ContextVar` (per `tenancy` module) для
   post-filter в agent invocations.

**Пути файлов:**

- *Implementation:*
  - `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py`
  - `src/backend/services/ai/gateway_adapter.py`
- *Tests:*
  - `tests/unit/core/ai/gateway_pipeline_mixin/test_policy_mixin.py`
    (extend: 3-arg case)
  - `tests/unit/services/ai/test_gateway_adapter.py` (extend: DI failure case)
  - `tests/integration/agents/test_tenant_contextvar.py` (new)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-B-05-report.md`

**Dependencies:** нет.
**Параллельно с:** всеми.
**LOC:** ~20-30 source; ~50 LOC tests.
**Готово когда:**
- `pytest tests/unit/core/ai/gateway_pipeline_mixin/test_policy_mixin.py -v` exit 0;
- `pytest tests/unit/services/ai/test_gateway_adapter.py -v` exit 0 (DI failure raises);
- `pytest tests/integration/agents/test_tenant_contextvar.py -v` exit 0;
- `grep -nE "return AIGateway\(\)" src/backend/services/ai/gateway_adapter.py` → 0 hits
  (без feature flag) ИЛИ hit присутствует только под `if settings.dev_only_bare_gateway:`.

**Rollback:** revert.
**Docstring marker:** `cycle-1/B-05`.
**Compatibility risk:** medium (dev/staging может ломаться, если bare gateway
был нужен; **требуется feature flag** `dev_only_bare_gateway` или equivalent).

---

## 3. Wave 2 — P1 Architecture/Layer Track (1 задача)

### T-2.1 — Reverse-layer cleanup (no-growth gate)

**Finding IDs:**
- `services:DOMAIN-P1-002` (`services/integrations/skb.py:16`)
- `services:DOMAIN-P1-003` (`services/io/files.py:11`)
- `agents:DOMAIN-P1-005` (`dsl/agents/fastmcp_server.py:36-39`)
- `business-logic:DOMAIN-P1-001` (importlib infrastructure import)
- `business-logic:DOMAIN-P1-002` (core-shim layer violation)

**Priority:** P1
**Domain:** services + agents + business-logic (3 домена)
**Паттерн:** exact imports + `tools/check_layers.py` test (no-growth gate)

**Что менять:**

1. `src/backend/services/integrations/skb.py:16` — удалить reverse-layer import
   `extensions.skb.services.waf_route`. Перенести callers на canonical path
   через facade.
2. `src/backend/services/io/files.py:11` — удалить reverse-layer import
   `extensions.core_entities.files.services.files`. Перенести callers.
3. `src/backend/dsl/agents/fastmcp_server.py:36-39` — удалить прямой import
   `src.backend.infrastructure.workflow.registry`; вынести `WorkflowDescriptor`
   в core facade (per `core/facades.py`).
4. **NO-GROWTH GATE** (§0): `python tools/check_layers.py --root src` →
   legacy ≤ 175, new = 0. Любое увеличение — блокирует merge.

**Пути файлов:**

- *Implementation:*
  - `src/backend/services/integrations/skb.py`
  - `src/backend/services/io/files.py`
  - `src/backend/dsl/agents/fastmcp_server.py`
  - `src/backend/core/facades.py` (extend: WorkflowDescriptor facade method)
- *Tests:*
  - `tests/unit/tools/test_check_layers.py` (extend: **no-growth** test)
  - `tests/unit/services/integrations/test_skb.py` (extend: layer check)
  - `tests/unit/services/io/test_files.py` (extend: layer check)
  - `tests/unit/dsl/agents/test_fastmcp_server.py` (extend)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-P1-01-report.md`

**Dependencies:** нет.
**Параллельно с:** T-1.1..T-1.5, T-3.1, T-4.1. **Conflict-area:** обе задачи
T-1.1 и T-2.1 трогают `tools/check_layers.py` — merge order:
T-1.1 → T-2.1 (или наоборот, но не одновременно).
**LOC:** ~20-40 source; ~40 LOC tests.
**Готово когда:**
- `python tools/check_layers.py --root src` exit 0, legacy ≤ 175, new = 0;
- `pytest tests/unit/tools/test_check_layers.py -v` exit 0 (no-growth test passes);
- все reverse-layer imports удалены (verify через `tools/check_layers.py --report`).

**Rollback:** revert; legacy layer violations возвращаются, но baseline
значение 175 не нарушено.
**Docstring marker:** n/a (P1 architecture, не security/data-loss).
**Compatibility risk:** medium (reverse-layer cleanup может сломать callers,
которые импортировали через эти пути; требуется миграция callers).

---

## 4. Wave 3 — Library Replacement (1 задача)

### T-3.1 — `cachetools.TTLCache` для embedding cache

**Finding IDs:**
- `infra:DOMAIN-P3-001` (`infrastructure/cache/rag/embedding_cache.py:17-64`)

**Priority:** P3
**Domain:** infrastructure
**Паттерн:** library replacement (уже в deps; stdlib не подходит — нужен TTL+LRU+eviction)

**Library:**

- `cachetools>=5.3.0,<8.0.0`
- **Уже в `pyproject.toml` core deps** (per Phase 2 §7); не требует нового lockfile.
- **Maturity:** активно поддерживается; последние релизы 2024+.
- **License:** MIT (низкий риск для банковского продукта).
- **Pre-existing uv.lock diff (§0):** использовать **уже зафиксированную версию**;
  **не менять** `uv.lock` (запрет из §0).

**Что менять:**

1. `src/backend/infrastructure/cache/rag/embedding_cache.py:17-64` — заменить
   custom TTL+LRU (64 LOC) на `cachetools.TTLCache(maxsize=..., ttl=...)`.

**Пути файлов:**

- *Implementation:*
  - `src/backend/infrastructure/cache/rag/embedding_cache.py`
- *Tests:*
  - `tests/unit/infrastructure/cache/rag/test_embedding_cache.py`
    (extend: TTL expiration, LRU eviction, maxsize overflow)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-P3-01-report.md`
- *pyproject:*
  - `pyproject.toml` — verify `cachetools>=5.3.0,<8.0.0` уже в core deps;
    **не менять** `uv.lock` (pre-existing diff не должен расти).

**Dependencies:** нет.
**Параллельно с:** всеми.
**LOC delta:** −49 source (64 → ~15); +библиотечные тесты через cachetools
(внешний test suite).
**Готово когда:**
- `pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py -v` exit 0;
- TTL expiration test passes (через `time.sleep` или `freezetime`);
- LRU eviction test passes (insert > maxsize, verify oldest evicted);
- `git diff uv.lock | wc -l` → 0 (lockfile **не тронут**);
- `grep -nE "from cachetools import TTLCache" src/backend/infrastructure/cache/rag/embedding_cache.py` → ≥1 hit.

**Rollback:** revert коммита; custom TTL+LRU восстановлен через revert.
**Docstring marker:** n/a (P3 replacement, не security/data-loss).
**Compatibility risk:** low (cachetools.TTLCache API совместим с текущим
custom API; единственное отличие — thread-safety: cachetools.TTLCache НЕ
thread-safe по дизайну — убедиться, что все вызовы из async-контекста через
`asyncio.Lock` или что текущий код уже async-safe).

---

## 5. Wave 4 — Organic Feature/Optimization (1 задача)

### T-4.1 — Text-RAG E2E test (LangGraph/DSPy-aligned pipeline)

**Finding IDs:**
- `rag:RAG-P4-001` (Phase 2 §5.9, §8)

**Priority:** P4
**Domain:** RAG
**Паттерн:** тест (НЕ новая платформа), inspired by LangGraph/DSPy RAG pipelines

**Evidence (§5.9 PHASE-2-SUMMARY):** только multimodal E2E существует
(`tests/e2e/test_multimodal_rag_e2e.py:255-340` — image ingest → BLIP2 stub
→ embed → search → LiteLLM stub pipeline). Text-RAG E2E
(ingest→chunking→embedding→retrieval→rerank→LLM) — НЕ существует.

**Что менять:**

1. Создать `tests/e2e/test_text_rag_e2e.py` (~150-200 LOC) с реальным
   pipeline: ingest → chunking (`services/ai/chunkers/RecursiveChunker`,
   per `rag:RAG-P3-001`) → embedding → Qdrant/Chroma retrieval → rerank →
   LiteLLM stub LLM.
2. **Не использовать моки** для chunker/embedding/retrieval — только stub для
   LLM (per existing multimodal pattern в `test_multimodal_rag_e2e.py`).
3. Если live Qdrant/Chroma/Redis недоступны — добавить marker
   `@pytest.mark.xfail(reason="real runtime required")` и явно перечислить
   в `docs/audit/swarm-2026-08-06/cycle-1/RAG-RUNTIME-REPORT.md`.

**Пути файлов:**

- *Tests (новый):*
  - `tests/e2e/test_text_rag_e2e.py` (~150 LOC)
- *Docs:*
  - `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-P4-01-report.md`
  - `docs/audit/swarm-2026-08-06/cycle-1/RAG-RUNTIME-REPORT.md` (если runtime недоступен)

**Dependencies:** нет.
**Параллельно с:** всеми.
**LOC:** ~150-200 новый test file.
**Готово когда:**
- `pytest tests/e2e/test_text_rag_e2e.py --collect-only -q` → ≥5 tests collected;
- `pytest tests/e2e/test_text_rag_e2e.py -v` exit 0 (или все тесты помечены xfail с runtime report);
- `grep -nE "Mock|mock\(" tests/e2e/test_text_rag_e2e.py` → только LLM-related
  stubs (per multimodal pattern; chunker/embedding/retrieval — real);
- Pipeline покрывает: ingest → chunking → embedding → retrieval → rerank → LLM.

**Rollback:** revert; новый test удалён.
**Docstring marker:** n/a (P4 feature, не security/data-loss).
**Compatibility risk:** low (только test, не production code).

---

## 6. Wave N — Deferred to cycle 2+ (НЕ закрывается в cycle 1)

### 6.1. Оставшиеся P0 (32 из 37) — cycle 2+

| Finding ID | Причина deferral |
|---|---|
| `infra:DOMAIN-P0-001` unbounded asyncio.Queue (OOM) | Требует capacity planning + eviction policy; не local; cycle 2 |
| `infra:DOMAIN-P0-002` ConnectorRegistry thread-unsafe singleton | Требует ADR (lock strategy); cycle 2 |
| `infra:DOMAIN-P0-003` PII `_safe_sanitize` fail-open | Требует audit-event wiring; cycle 2 |
| `infra:DOMAIN-P0-004` Rate limiter fail-open при Redis падении | Требует ADR для fallback; cycle 2 |
| `infra:DOMAIN-P0-005/P0-006` Module-level infra→DSL imports | Требует lazy-import refactor; cycle 2 |
| `infra:DOMAIN-P0-007` Race в dispatcher | Требует `_active_executions` check + lock; cycle 2 |
| `security:DOMAIN-P0-001` validate_sql drops `policy_override` | Требует framework API change; cycle 2 |
| `api:API-P0-001/P0-002` admin mock-fallback | Зависит от T-1.1 composition root fix; cycle 2 |
| `api:API-P0-005` Mobile BFF demo-auth | Требует ADR (real JWT vs feature flag OFF); cycle 2 |
| `dsl:DOMAIN-P0-003` ScanFileProcessor AV fail-open | Требует policy decision; cycle 2 |
| `workflow:DOMAIN-WF-P0-001/P0-002` WorkflowFlags docstring + 4 missing `@processor` | Частично покрыто T-1.1 (ActivityBridge); cycle 2 для остатка |
| `agents:DOMAIN-P0-003` 3 процессора hardcode `tenant_id` | Требует ContextVar propagation audit; cycle 2 |
| `agents:DOMAIN-P0-004` fastmcp_server infrastructure import | Покрыто в T-2.1 (partial); cycle 2 для полного cleanup |
| `rag:RAG-P0-002` RagCachePrewarmer no-op | Требует service API design; cycle 2 |
| `business-logic:DOMAIN-P0-003` credit scoring fail-open | Требует policy decision (`raise` vs `score=0`); cycle 2 |
| `business-logic:DOMAIN-P0-004` OSINT fail-open | Требует policy decision (search/LLM-failure); cycle 2 |
| `dependencies:DOMAIN-P0-001..004` allowlist drift + wrong comments | Требует 4-way reconciliation (CI + gate + manifest); cycle 2 |
| `settings-env:ENVSET-P0-001/P0-002` Granian CLI flag + dup shutdown timeout | Требует settings refactor; cycle 2 |

### 6.2. Оставшиеся P1 (56 из 57) — cycle 2+

Все P1 кроме T-2.1:
- 4 security downward-layer violations
- 11 API (mock-fallback, importlib bypass, RCE, `_mock_actions`, `stub: True`)
- 10 DSL (missing imports, kwargs filter, side_effect contract, Resequencer
  memory leak, RedisLock never releases, WindowedDedup fail-open,
  telemetry swallow, XXE fallback, stale docstring, top-level re-export gap)
- 5 workflow (SemVer silent fallback, Guardrail fail-open, sensor infinite
  polling, namespace mismatch warning-only, WatchError tight loop)
- 5 agents (try/except placement, DI без config-injection,
  `get_ai_agent_service` NotImplementedError factory,
  `LiteLLMModel.request_stream` NotImplementedError)
- 3 RAG (layer violation `_RAGFacade`, naive chunker, дубль
  `_resolve_effective_tenant_id`)
- 4 business-logic (orders_dsl disconnected, workflow YAML dead refs)
- 5 settings-env (compose без CPU/memory limits, k8s без preStop,
  hardcoded `task_registry timeout=10`, subprocess без exit validation)
- 8 infrastructure (singletons, locks, asyncio.wait_for churn,
  `EmbeddingVectorCache` без тестов)

### 6.3. P2 (61 запись) — cycle 2+

Dead code, `NotImplementedError` в `__init__`, `pass` после `except`,
deprecated shims, broad except без narrowing. Серия удалений после
стабилизации P0/P1.

### 6.4. P3 (28 из 29) — cycle 2+

11+ кандидатов library replacement (§7 PHASE-2-SUMMARY):
- `asyncio.timeout` (stdlib 3.11+; `dsl/engine/processors/eip/resilience.py:455`) — cycle 2
- `asyncio.TaskGroup` (stdlib 3.11+; MulticastRoutes+ScatterGather) — cycle 2
- `defusedxml.ElementTree.fromstring` (3× copies в format_convert) — cycle 2
- `httpx.AsyncClient` (lineage) — cycle 2
- `polars.write_excel` — cycle 2
- `PresidioAnalyzer` (≥2.2.362) — cycle 2 (trade-off: +1.5GB spaCy model)
- `redis-py Redis.lock` (`redis_lock_processor.py:78-121`) — cycle 2 (bug fix)
- `redis-streams` consumer-group — cycle 2
- `tiktoken` / `RecursiveChunker` — cycle 2
- `spiffworkflow` для BPMN import — **ОТКЛОНЁН** (новый lockfile)
- `graphviz` Python binding — cycle 2 (DOT injection fix, 0 LOC delta)
- `jsonschema>=4.21.0,<5.0.0` pin — cycle 2 (supply-chain risk)
- `functools.lru_cache` (stdlib; LDAP client) — cycle 2 (very small)
- `Pydantic v2 model_validate` — cycle 2
- `llm-guard` / `neuraly/enola` — **ОТКЛОНЕНЫ** (новый lockfile, +100MB)

Только `cachetools.TTLCache` (T-3.1) в cycle 1.

### 6.5. P4 (28 из 29) — cycle 2+

Только T-4.1 (text-RAG E2E test) в cycle 1. Остальные:
- DSPy integration (`agents:DOMAIN-P4-001`) — consolidation scope
- Temporal `start_child_workflow` (`workflow:DOMAIN-WF-P4-001`) — HITL production
- Camel `doTry/doCatch/doFinally` (`dsl:DOMAIN-P4-001`) — DSL extension
- BPMN boundary events (`dsl:DOMAIN-P4-005`) — DSL extension
- StatefulSaga checkpoint (`dsl:DOMAIN-P4-004`) — DSL extension
- DSPy Signature (`dsl:DOMAIN-P4-003`) — DSL extension
- `VersionedRouter` v2 (`api:API-P4-002`) — roadmap
- OPA policy DSL-style (`security:DOMAIN-P4-001`) — Sprint planning
- DLQ-replay UI (`entrypoints:DOMAIN-P4-001`) — post Sprint 36
- V15 GAP Slice 1 (`business-logic:DOMAIN-P4-001`) — Sprint 38+
- … (полный список в §8 PHASE-2-SUMMARY)

---

## 7. Порядок выполнения и параллельные группы для Phase 4 developers

### 7.1. Критический путь

```
T-0.1 (Preflight — ОБЯЗАТЕЛЬНЫЙ GATE)
   │
   ▼
[Phase 4 developers — 8 параллельных веток]
   │
   ├─► T-1.1 (Composition Root) [рекомендуется первым]
   ├─► T-1.2 (SSE/HITL Auth)
   ├─► T-1.3 (MQ DLQ — data-loss)
   ├─► T-1.4 (DSL Multicast/Redelivery)
   ├─► T-1.5 (AIGateway Capability)
   ├─► T-2.1 (Reverse-Layer Cleanup, no-growth gate)
   ├─► T-3.1 (cachetools.TTLCache)
   └─► T-4.1 (text-RAG E2E test)
```

### 7.2. Параллельные группы для Phase 4 (рекомендация)

**Группа 1a (CRITICAL — желательно первым):** T-1.1 (composition root).
Разблокирует `register_action_handlers()` smoke-тест для остальных веток.

**Группа 1b (security — параллельно после T-1.1 merge):**
- T-1.2 (SSE/HITL auth) — pure ASGI, 3 домена
- T-1.5 (AIGateway capability) — composition-root DI + tenant ContextVar

**Группа 1c (data-loss — параллельно после T-1.1 merge):**
- T-1.3 (MQ DLQ) — canonical DLQ + logger.error

**Группа 1d (correctness/maintenance — параллельно):**
- T-1.4 (DSL syntax)
- T-2.1 (reverse-layer cleanup, no-growth gate)
- T-3.1 (cachetools.TTLCache)
- T-4.1 (text-RAG E2E test)

### 7.3. Top dependencies между задачами

| Task | Depends on | Blocks | Notes |
|---|---|---|---|
| T-0.1 | — | **все остальные** | gate; developer запускает перед каждой задачей `bash tools/cycle-1-preflight.sh` |
| T-1.1 | T-0.1 | (composition root fix упрощает другие, но формально не блокирует) | рекомендуется первым |
| T-1.2 | T-0.1 | — | единственная задача, трогающая `auth_required.py` |
| T-1.3 | T-0.1 (частично T-1.1 для OutboxBackend DI) | — | data-loss fix |
| T-1.4 | T-0.1 | — | smallest diff (~5-10 LOC) |
| T-1.5 | T-0.1 | — | feature flag требуется для dev/staging |
| T-2.1 | T-0.1 | — | conflict с T-1.1 по `tools/check_layers.py` — merge order |
| T-3.1 | T-0.1 | — | stdlib/cachetools; не трогает lockfile |
| T-4.1 | T-0.1 | — | новый test file |

### 7.4. Conflict-areas для merge (порядок merge)

1. **T-0.1** (preflight) — первым.
2. **T-1.1** (composition root) — желательно вторым, до security-веток.
3. **T-1.2** (auth) — до того, как auth-related branches T-1.3 / T-1.5
   смогут полагаться на canonical auth chain.
4. **T-1.3, T-1.5** — параллельно.
5. **T-1.4** — независимо (только DSL).
6. **T-2.1** — после T-1.1 (чтобы избежать conflict в `tools/check_layers.py`).
7. **T-3.1, T-4.1** — независимо, в любом порядке.

### 7.5. Параллельные группы — итоговая таблица

```
Группа 1 (после T-0.1, все параллельно):
   ├── T-1.1 ─► критический путь (composition root)
   ├── T-1.2 ─► security (SSE/HITL auth)
   ├── T-1.3 ─► data-loss (MQ DLQ)
   ├── T-1.4 ─► correctness (DSL syntax)
   ├── T-1.5 ─► security (AIGateway capability)
   ├── T-2.1 ─► architecture (no-growth gate)
   ├── T-3.1 ─► library replacement (cachetools.TTLCache)
   └── T-4.1 ─► organic feature (text-RAG E2E)
```

Все 8 веток **формально независимы** после T-0.1; merge order
определяется conflict-areas (§7.4).

---

## 8. Definition of Done для cycle 1

Cycle 1 считается **завершённым**, когда **все 8 задач** (T-0.1..T-4.1)
закрыты со следующими метриками:

### 8.1. Functional DoD

| Метрика | Baseline | Цикл 1 ожидание | Команда |
|---|---|---|---|
| Composition root startup | crashes on lifespan | `register_action_handlers()` exit 0 | `python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"` |
| Layer checker | 175 legacy / 0 new | **≤ 175 legacy / 0 new** (no-growth gate) | `python tools/check_layers.py --root src` |
| Active security allowlist | 35 | **≤ 35** (no-new-CVE gate) | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` |
| Pre-existing dirty tree | s3.py+uv.lock | s3.py+uv.lock OR pyproject.toml+test_dataframes.py | `git status --short` |
| Docstring gate | 0 missing | 0 missing | `make check-docstrings MAX_ALLOWED=0` |
| xfailed SSE tests | 8 | **0** (все passing) | `pytest tests/unit/entrypoints/sse/test_handler.py -v` |
| `except Exception: pass` в MQ handlers | ≥1 | 0 | `grep -nE "except Exception.*:\s*pass" src/backend/entrypoints/stream/` |
| ActivityBridge wiring | not connected | wired to Temporal Worker | `grep -nE "register_langgraph_checkpoint_activities" src/backend/infrastructure/workflow/worker.py` |
| `cachetools.TTLCache` usage | absent | present в `embedding_cache.py` | `grep -nE "from cachetools import" src/backend/infrastructure/cache/rag/embedding_cache.py` |
| `uv.lock` diff churn | pre-existing | **0 new lines** | `git diff uv.lock \| wc -l` |
| Text-RAG E2E | absent | present (passing или marked xfail) | `pytest tests/e2e/test_text_rag_e2e.py --collect-only` |

### 8.2. Quality DoD

- Каждый PR имеет `cycle-1/B-XX` (T-1.1..T-1.5) или `cycle-1/PX-XX`
  (T-2.1, T-3.1, T-4.1) docstring marker для security/data-loss fixes.
- Русские docstrings **НЕ переведены**.
- Каждая задача имеет
  `docs/audit/swarm-2026-08-06/cycle-1/cycle-1-*-report.md` с описанием:
  что изменилось, какие тесты, какие метрики.
- `make lint && make type-check && make test` exit 0 перед merge.
- `make format` (ruff) exit 0 перед merge.
- `bash tools/cycle-1-preflight.sh` exit 0 перед merge каждой задачи.

### 8.3. Process DoD

- T-0.1 preflight выполнен **ДО** любой другой задачи.
- `docs/audit/swarm-2026-08-06/cycle-1/PREFLIGHT-REPORT.md` существует.
- `tools/cycle-1-preflight.sh` существует и exit 0.
- Каждая задача фиксирует preflight verification в своём report.
- Никакие `except Exception` блоки не удалены без concrete handling
  (logger.error ИЛИ DLQWriter.enqueue).

---

## 9. Причины, по которым потребуется cycle 2

Cycle 2 понадобится по следующим причинам:

1. **Scope discipline:** cycle 1 закрывает только **8 задач из 213 findings**
   (~4% от общего объёма). Остаётся ~205 findings (32 P0, 56 P1, 61 P2,
   28 P3, 28 P4) для cycle 2+.

2. **Cap rule:** ни один из 12 доменов не достигнет self-assessed ≥80 даже
   после cycle 1 (cap rule запрещает ≥80 при наличии P0/P1; cycle 1
   закрывает только 5 P0 из 37).

3. **P0 оставшиеся (32):** composition root частично, mobile BFF,
   AV fail-open, OSINT fail-open, dependency governance drift, workflow
   `@processor` decorators, agent `tenant_id` hardcode. Это блокеры
   production readiness.

4. **P1 оставшиеся (56):** architectural cleanup (4-way drift,
   layer violations, capability-gate consistency, workflow SemVer),
   settings (compose limits, preStop). Без них maintainability деградирует.

5. **P2 batch (61):** dead code, `NotImplementedError` stubs, deprecated
   shims, broad `except: pass`. Требуется серия удалений после
   стабилизации P0/P1.

6. **P3 library replacements (28):** `asyncio.timeout`, `asyncio.TaskGroup`,
   `defusedxml`, `httpx.AsyncClient`, `PresidioAnalyzer`, `redis-py
   Redis.lock`, `tiktoken` chunker, `functools.lru_cache`. Только
   `cachetools.TTLCache` в cycle 1.

7. **P4 features (28):** DSPy integration, Temporal `child_workflow`,
   `WorkflowDeclaration` converter, Camel `doTry/doCatch/doFinally`,
   OPA policy DSL, DLQ-replay UI, text-RAG eval artifacts, V15 GAP Slice 1.
   Только `text-RAG E2E test` в cycle 1.

8. **Runtime evidence (§10.2):** RAG agent не верифицировал live
   Qdrant/Chroma/Redis; Workflow agent не запускал реальный Temporal cluster;
   Business Logic — Temporal runtime не запускал; Services — runtime pytest
   заблокирован; DSL — vault/redis недоступны. Cycle 2 должен включать
   dedicated **runtime verification phase** (real Temporal cluster, real
   Qdrant/Chroma/Redis, real MQ brokers).

9. **Dependency governance (4-way drift):** `pip-audit-allowlist.txt`
   ↔ GitHub Actions ↔ GitLab CI � `pip_audit_gate.py` — требует full
   reconciliation; cycle 1 не покрывает.

10. **Documentation gaps (§8):** docs audit (V15 GAP Slice 1, OPA policy
    DSL-style, DLQ-replay UI) — все deferred.

### 9.1. Realistic estimate

Per Phase 2 §9: **3-5 sprints** для full P0/P1 closure.
Cycle 1 закрывает ~4% от общего объёма;
Cycle 2 — следующие ~20-30% (critical path composition root + оставшиеся P0/P1
high-impact) ожидаемо за **1 sprint**;
Cycle 3-5 — remaining P1 + P2 + P3 + P4 + runtime verification.

### 9.2. Definition of "cycle 2 needed"

Cycle 2 определённо потребуется, если **хотя бы один** из следующих критериев
остаётся открытым после cycle 1:

- ≥1 P0 из §6.1 не закрыт (32 открытыми остаются);
- ≥1 P1 high-impact (admin mock-fallback, OSINT/credit fail-open) не закрыт;
- runtime evidence phase не выполнен (real Temporal, real Qdrant);
- layer checker legacy > 175 или new > 0 (regression).

На момент завершения cycle 1 **все 4 критерия останутся** — cycle 2 обязателен.

---

## 10. Сводка для родителя (кратко)

* **Статус:** Phase 3 plan COMPLETE. Файл — `docs/audit/swarm-2026-08-06/cycle-1/PHASE-3-PLAN.md` (этот файл).
* **Количество задач:** **8** (1 preflight + 5 P0 + 1 P1 + 1 P3 + 1 P4).
* **Не закрыто в cycle 1:** ~205 findings (32 P0, 56 P1, 61 P2, 28 P3, 28 P4).
* **Параллельные группы (после T-0.1):** все 8 веток формально независимы;
  рекомендуемый merge order — T-0.1 → T-1.1 → {T-1.2, T-1.5} ∥ {T-1.3} ∥ {T-1.4} ∥ {T-2.1} ∥ {T-3.1} ∥ {T-4.1}.
* **Top dependencies:**
  - T-0.1 (preflight gate) → блокирует все остальные;
  - T-1.1 (composition root) — рекомендуется первым в Wave 1;
  - T-1.2 (SSE/HITL auth) — до T-1.3/T-1.5 (canonical auth chain);
  - T-2.1 (no-growth gate) — merge после T-1.1 (conflict в `tools/check_layers.py`).
* **Gates (cycle 1 baseline):** layer ≤175/0; allowlist ≤35; uv.lock diff = 0;
  docstrings = 0; `except Exception: pass` = 0 в MQ handlers; 8 xfailed SSE
  сняты; ActivityBridge wired; cachetools.TTLCache present; text-RAG E2E present.
* **Docstring markers:** `cycle-1/B-01..B-05` для 5 security/data-loss fixes;
  `cycle-1/P1-01`, `cycle-1/P3-01`, `cycle-1/P4-01` для P1/P3/P4.
* **Cycle 2 обязателен:** 4 критерия (см. §9.2) останутся открытыми.

---

*Phase 3 architect (read-only). Не правил ничего, кроме этого файла.
Не читал source/test/git diff/Phase 1 reports/CLAUDE/PLAN/KNOWN_ISSUES.*
