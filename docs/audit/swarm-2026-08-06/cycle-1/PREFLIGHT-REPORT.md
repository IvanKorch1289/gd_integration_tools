# T-0.1 — Developer preflight report (cycle 1)

Date: 2026-08-06
Цикл: 1, фаза 4, task T-0.1.
Назначение: зафиксировать фактическое состояние HEAD/working tree и подтвердить, что
сводка Фазы 2 + план Фазы 3 применимы к текущему коду. Только read-only проверки +
создание двух новых файлов.

## 1. Зафиксированный baseline (реальный)

| Gate | Ожидание | Факт | Статус |
|---|---|---|---|
| HEAD | b69d6b49 или +1 (2f620910) | `ca5bff93` (HEAD на 16 ahead of origin/master) | WARNING: между baseline и текущим HEAD +16 коммитов; plan был рассчитан на +1. Не блокер — план использует пути файлов, а не коммиты. |
| `python tools/check_layers.py --root src` | 175 legacy, 0 new | `175 legacy, 0 new` | PASS |
| `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | 35 | 35 | PASS |
| `make check-docstrings MAX_ALLOWED=0` | 0 missing | 0 missing (838 files) | PASS |
| Working tree | любой из двух сценариев | только `M uv.lock` (-15 lines, `svcs` пакет удалён; не в `pyproject.toml`) | OK — не раутим uv.lock |
| s3.py modified | упоминается в BASELINE | **не modified** (origin local +16 без локальных правок) | Роу s s3.py не нужен |

## 2. Дрейф BASELINE → реальность

- BASELINE упоминал `M src/backend/infrastructure/storage/s3.py + M uv.lock`.
  Текущий git status показывает только `M uv.lock`. Утверждение про s3.py —
  устаревшее, ров его не трогает.
- План и отчёты Фазы 1 ссылаются на несуществующий модуль
  `src.backend.core.ai.capability_gate`. Фактическая иерархия:
  `src/backend/core/security/capabilities.py` → `CapabilityGate` (через DI);
  `src/backend/services/capabilities/facade.py` → `CapabilityFacade.check(plugin, capability, scope)`.
  Plan reference `policy_mixin.py:100` вызывает `gate.check(capability)` с 1
  аргументом — этот callsite остаётся, но Developer при фиксе T-1.5 должен
  смотреть на canonical CapabilityFacade (3-arg) или DI через
  `services/capabilities/facade.get_capability_facade()`.
- `src/backend/dsl/engine/execution.py` (упомянуто в plan) — не существует;
  канонический модуль `src/backend/dsl/engine/execution_engine.py`. `multicast.py:172`
  действительно передаёт `ExecutionEngine(route_registry=...)` →
  `__init__` принимает только `(self, middleware, validate_before_execute, pool)` → **bug реален**.
- `extensions/core_entities/orders/workflows/` содержит только `__init__.py` и
  `orders_dsl.py`; `orders_saga` модуль отсутствует.
- `extensions/credit_pipeline/workflows/` содержит только YAML без
  `payments_saga.py` Python-модуля.
- `src/backend/workflows/` — каталог отсутствует → `from src.backend.workflows.workflows_service import ...` всегда падает (даже с `# type: ignore`).
- `tools/check_layers_allowlist.txt` (180 lines) и `.security/pip-audit-allowlist.txt`
  (35 active IDs) подтверждены. S3.py — не modified. uv.lock — pre-existing diff не атрибутируется рою.

## 3. Запреты на роут (распространяются на все T-1..T-4)

1. Не править `uv.lock` (pre-existing -15 lines).
2. Не править `.security/pip-audit-allowlist.txt` (35 → не расти).
3. Не удалять `except Exception` без concrete handling (logger.error / DLQWriter.enqueue).
4. Не переводить русские docstrings/comments.
5. Не делать `git push` / force-push.
6. Каждый security/data-loss фикс сопровождается docstring-маркером `cycle-1/B-XX` (русские docstrings оставлять как есть).
7. Не трогать `src/backend/infrastructure/storage/s3.py`.
8. Не использовать broad `# type: ignore` без комментария с причиной.

## 4. Пере-используемый preflight script

`tools/cycle-1-preflight.sh` создаётся ниже (в этом же коммите). Developer
запускает его **перед каждой** задачей T-1.* / T-2.* / T-3.* / T-4.*.

## 5. Verdict по T-0.1

- READY для запуска Phase 4 developers.
- Каждый dev-агент получает уточнённые пути и запреты (см. промпт).
- Plan §3.2 (cachetools.TTLCache): cachetools **уже в core deps**
  (`pyproject.toml`); lockfile-уровень менять не нужно.
