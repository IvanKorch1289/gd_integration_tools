# ADR-0145 — Sprint 65 closure: P0 cleanup (lazy imports, dead enforcement, dsl/workflows LAYERS) (3 commits, 3/3 substantive)

* Статус: Accepted (Autonomous work cycle S65, 2026-06-12)
* Связано с: `c88bb50f` (S65 W2 lazy imports), `4847c053` (S65 W3 dead cleanup), `e2ce292c` (S65 W4 dsl/workflows LAYERS)
* Контекст: comprehensive audit report (2026-06-11), P0-P2 plan

## Контекст

Comprehensive audit (10 аналитических агентов) выявил 5 P0-задач.
S65 закрывает 3 из них (W1 W5 не в scope — W1 = проверка W2 S64
multi-instance safety, выполнена в S64 цикле; W5 = closure, этот ADR).
Оставшиеся 2 P0 (`AgentSpec.tools` runtime enforcement, JupyterHubClient)
deferred S66+ (см. S65 honest gaps).

**Fact-check findings** (против исходного аудита):
- `JupyterHubClient` УЖЕ используется в `services/jupyter/execution_service/__init__.py:30,65` (анализ врёт: P0-5 moot).
- `check_no_tests.py` НЕ подключен к pre-commit/CI (dead enforcement, не active blocker).
- 40 (не 39) lazy imports core/ → other layers.

## Решения

### W2: `tools/check_layers.py` — lazy imports под проверкой (commit `c88bb50f`)

**P0-1**: AST-линтер skip'ал lazy imports (`if is_lazy: continue`, S27
marker, 2026 baseline) → blind spot для ~40 нарушений.

**Fix**:
```python
# До:
for module, lineno, is_lazy in _imports(tree):
    if is_lazy:
        continue  # S27 skip — blind spot
# После:
for module, lineno, is_lazy in _imports(tree):
    # S27 marker удалён S65 W2
    if _is_in_type_checking_block(tree, lineno):
        continue  # TYPE_CHECKING imports — НЕ нарушения
```

**Effect**: 42 новых нарушений найдено, 4 stale удалено. Allowlist
`check_layers_allowlist.txt`: 47 → 82 entries.

### W3: Dead enforcement cleanup (commit `4847c053`)

**P0-3**: Мёртвый код, противоречащий реальности проекта.

Удалено:
1. `tools/check_no_tests.py` (67 LOC) — `HARD-BLOCK` политика,
   противоречит 1135 существующим тестам. НЕ подключен к
   `.pre-commit-config.yaml` или CI (dead enforcement).
2. `src/backend/infrastructure/cache/aiocache_poc.py` — S59 W4 PoC,
   docstring явно говорит "НЕ production-готовый".
3. `tests/unit/infrastructure/cache/test_s59_w4_aiocache_poc.py` —
   тест для удалённого PoC.

`aiocache` ОСТАВЛЕН в `pyproject.toml:94` для ADR-0086 future migration
(1778 LOC custom cache → aiocache, eval по ADR scope).

### W4: dsl/workflows в LAYERS (commit `e2ce292c`)

**P0-2**: `dsl/` и `workflows/` (280+ файлов) были вне `LAYERS` →
все импорты из них невидимы для линтера.

**Fix**:
```python
LAYERS = (
    "core", "infrastructure", "services", "entrypoints", "schemas",
    "dsl",        # S65 W4: meta-layer, импортирует всё
    "workflows",  # S65 W4: meta-layer, импортирует всё
)
ALLOWED["dsl"] = ALLOWED["workflows"] = {
    "core", "infrastructure", "services", "entrypoints", "schemas",
}
```

**Effect**: 119 новых violations найдено (все ВИДИМЫ теперь). Allowlist
82 → 201 entries. `--strict` mode готов (exit 1 при 201 violations,
default exit 0 если все в allowlist).

**Worst offenders** (S66+ backlog):
- `core/ai/agent_registry.py` → `dsl.workflow.spec` (core → dsl: BAD)
- `core/interfaces/batch_capable.py` → `dsl.engine.context`
- `entrypoints/_action_bridge.py` → `dsl.service`

## Honest gaps (deferred S66+)

| Gap | Source | Severity |
|---|---|---|
| Pre-existing import bugs (DatabaseInitializer, graphql_router, redis_client) | TD-S64-W3 | P1 |
| `AgentSpec.tools` runtime enforcement (analysis P0-4) | comprehensive audit | P1 |
| 119 dsl/workflows violations (фикс в S66+ refactoring) | S65 W4 | P1 |
| 35 core → other layers violations (S65 W2) | S65 W2 | P1 |
| BatchUpdateProcessor (cycle per item) | analysis P1-5 | P1 |
| Per-row advisory lock (S64 W1) | TD-S64-W1 | P1 |
| Scheduler lock auto-extend (S64 W2) | TD-S64-W2 | P1 |
| RedisDedupeStore fail-closed (S64 W4) | TD-S64-W4 | P1 |

## Quality gates (S65 scope)

- **mypy**: S65 changes clean.
- **ruff**: clean.
- **7 unit-тестов** для `check_layers.py` (lazy detection, top-level,
  TYPE_CHECKING, key format, dsl/workflows в LAYERS, file_layer detection).
- **3 dead files** удалены без замены (truly dead, не переиспользуются).
- Sibling WIP outstanding: ~1700 mypy errors (не наш scope).

## Lessons learned

1. **"Hard-block" policies** без enforce-механизма (pre-commit/CI) —
   dead code, удалять. Документация ≠ enforcement.
2. **PoC файлы** с docstring "НЕ production-готовый" — кандидаты
   на удаление после подтверждения production-реализации.
3. **LAYERS** должны покрывать ВСЕ директории backend'а, иначе
   blind spot.
4. **Allowlist** (не fail) для legacy violations — incremental
   improvement, не breaking change.
5. **Comprehensive audit ≠ ground truth** — нужна verification
   (2 из 5 P0 в анализе были неточными/неверными).
