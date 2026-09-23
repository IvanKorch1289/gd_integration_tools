# ADR-0342 — AIPolicySpec S76 tool_policy → tools migration

## Статус

**Accepted** (2026-09-23, cycle 158+). Закрывает pre-existing schema
violation в `ai_policies/agent_basic.policy.yaml` (discovered gate
`check_ai_policy_schema.py` в RED-exit1 state).

## Контекст

`check_ai_policy_schema.py` (gate) валидирует каждую YAML в `ai_policies/`
против Pydantic-схемы `AIPolicySpec` (`src/backend/core/ai/policy/spec.py`).

**Pre-fix state (RED-exit1)**:
- 3 policy-файла в `ai_policies/`:
  - `agent_basic.policy.yaml`
  - `credit_check_strict.policy.yaml` ✅
  - `rag_default.policy.yaml` ✅
- `agent_basic.policy.yaml` содержит `tool_policy: { allow, deny, max_calls_per_run }`,
  но `AIPolicySpec.tools: ToolsSpec` (S76 W1 миграция) ожидает
  `{ whitelist, blacklist, on_violation, allow_all_tools }`.
- Pydantic fail-closed: "Extra inputs are not permitted [type=extra_forbidden]"
  → gate exit 1 → "1 файл не прошёл валидацию".

**S76 W1 (FINAL_REPORT_V2 P0-B) миграция**: заменено `tool_policy.{allow,deny}`
на `tools.{whitelist,blacklist}` для консистентности с security terminology.
Pre-S76 YAML-файлы остались не обновлены (orphan schema debt).

## Решение

Мигрировать `ai_policies/agent_basic.policy.yaml` от pre-S76 schema к S76:

```yaml
# PRE-S76 (broken):
tool_policy:
  allow: [...]
  deny: [...]
  max_calls_per_run: 20

# POST-S76 (working):
tools:
  whitelist: [...]   # formerly allow
  blacklist: [...]   # formerly deny
  on_violation: "fail"
  allow_all_tools: false  # explicit, не implicit
```

**Что НЕ сохранилось**:
- ❌ `max_calls_per_run: 20` — не имеет эквивалента в current `ToolsSpec`.

## Альтернативы рассмотрены

### 1. Ничего не делать
- ❌ Отвергнуто: gate остаётся RED, agent_basic — невалидный policy.
- ❌ Это означает, что при runtime YAML load → `PydanticValidationError`.

### 2. Добавить `max_calls_per_run` обратно в `ToolsSpec`
- ⚠️ Considered, отложено: требует отдельного ADR для schema-extension
  (новое поле в Pydantic + runtime enforcement в AIGateway).
- Текущая сессия не имеет достаточного контекста для design decision
  (что значит "max calls per run" — per workflow, per session, per agent
  loop iteration? какая метрика для подсчёта?).

### 3. Backward-compat shim: принять `tool_policy` и migrate в `tools`
- ❌ Отвергнуто: v4 §10 P1 «Удалять shim только после 0 importers,
  migration window и contract test». Введение нового shim без telemetry
  audit = debt-creation, не debt-reduction.

## Последствия

### Позитивные

- ✅ `check_ai_policy_schema.py` exit 0 (gate green).
- ✅ Pre-existing schema violation зафиксирован и resolved.
- ✅ `agent_basic` policy теперь usable на runtime.
- ✅ Документирован loss-of-functionality для `max_calls_per_run`
  (honest status, не silent).

### Негативные

- ⚠️ Loss of `max_calls_per_run` enforcement: если была runtime-проверка
  лимита 20 tool-calls per run, она теперь не действует.
  - Митигация: ADR-0342 ссылается на необходимость отдельного ADR для
    schema-extension (`max_calls_per_run` per `ToolsSpec` или per
    `AIPolicySpec` напрямую).
- ⚠️ Один из 3 policy-файлов нуждался в миграции → возможно, другие
  extensions/<name>/ai_policies/*.policy.yaml также pre-S76.
  Рекомендация: sweep по extensions/ + re-run gate.

### Нейтральные

- YAML-файл изменён: 9 строк заменены структурно.
- Никаких runtime-side changes в Python-коде.

## Что НЕ покрыто (deferred to next ADR cycle)

- ❌ Sweep по extensions/<name>/ai_policies/*.policy.yaml — pre-S76?
- ❌ Schema-extension для `max_calls_per_run` (требует design decision).
- ❌ Audit других pre-S76 → S76 миграций в `AIPolicySpec` (новые поля
  добавлены в S76+, требуют review).

## Verification

| Измерение | Результат |
|---|---|
| `python3.14 tools/checks/check_ai_policy_schema.py` | exit 0 (3 files validated, 0 errors) |
| `python3.14 -c "from src.backend.core.ai.policy.spec import AIPolicySpec; AIPolicySpec.model_validate_yaml(open('ai_policies/agent_basic.policy.yaml').read())"` | OK (no exception) |
| `ruff check ai_policies/agent_basic.policy.yaml` | (YAML не линтится ruff, skip) |
| `python3.14 -m compileall -q ai_policies/` | n/a (YAML-only) |

## Ссылки

- v4 §10 P1 (запрет на слепые fixes)
- v4 §3 «мерь до работы» (discover → measure → fix, не наоборот)
- S76 W1 (FINAL_REPORT_V2 P0-B) — ToolsSpec introduction
- ADR-NEW-20 (AIPolicySpec первоначальный design)
- PROGRESS_LEDGER §Cycle 158+ v4 §10 sweep
