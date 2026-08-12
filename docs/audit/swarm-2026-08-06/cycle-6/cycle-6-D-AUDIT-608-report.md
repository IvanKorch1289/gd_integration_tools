# Cycle-6 D-AUDIT-608 — admin_cron RCE fix

**Task**: T-C6-08-ADMIN-CRON | fix admin_cron RCE
**Plan ref**: cycle-4 phase-1/05-api.md → API-P0-002 (DOMAIN-P0-002, RESIDUAL с cycle-3 API-P1-003)
**Marker**: `cycle-6/D-AUDIT-608`
**Status**: ✅ DONE — whitelist реализован, verified runtime.

---

## 1. Уязвимость (подтверждена)

`src/backend/entrypoints/api/v1/endpoints/admin_cron.py:86-94` (до фикса):

```python
def _resolve_callable(ref: str) -> Any:
    import importlib
    module_path, _, attr = ref.partition(":")
    if not attr:
        raise ValueError(...)
    module = importlib.import_module(module_path)  # ← arbitrary module
    return getattr(module, attr)                   # ← arbitrary attribute
```

Pydantic-паттерн `callable_ref: pattern=r"^[\w.]+:[\w]+$"` (`admin_cron.py:53-56`) допускает
`os:system`, `builtins:exec`, `subprocess:check_output`, `shutil:rmtree` — whitelist отсутствовал.

**Цепочка эксплуатации**: `POST /admin/cron/schedule` (guard = `OPERATOR|SUPER_ADMIN`,
`admin_cron.py:28-30`) → `_resolve_callable` резолвит произвольный callable →
`scheduler_manager.add_job` → немедленное выполнение через `POST /admin/cron/{id}/run-now`
(`admin_cron.py:185-195`). Для OPERATOR-роли это RCE уровня сервера.

## 2. Выбор варианта: (a) whitelist

Вариант (b) `raise NotImplementedError` **отклонён** — router реально смонтирован
(`src/backend/entrypoints/api/v1/routers.py:26-27, 215`) и используется frontend'ом
(`src/frontend/streamlit_app/pages/13_Конструктор_Cron.py`, `pages/_groups/cron/builder/render.py`).
Заглушка сломала бы рабочий сценарий регистрации cron-job. Реализован вариант **(a)**.

## 3. Изменения

### `src/backend/entrypoints/api/v1/endpoints/admin_cron.py` (+25/-2)

- Добавлен модуль-level `ALLOWED_CALLABLE_MODULES: frozenset` с единственным
  реально существующим модулем задач `src.backend.infrastructure.scheduler.scheduled_tasks`
  (экспортирует `check_all_services`, `consolidate_idle_sessions`).
- `_resolve_callable`: проверка `module_path not in ALLOWED_CALLABLE_MODULES` → `ValueError`
  **до** вызова `importlib.import_module`, поэтому import-time side-effect недостижим.
- Дополнительно: `callable(resolved)` guard — whitelisted модуль, но не-callable атрибут → `ValueError`.
- Обработка не менялась: `schedule_cron_job` уже ловит `ValueError` → HTTP 400 (`admin_cron.py:115-119`).
  `except Exception` блоки не удалялись.

Whitelist намеренно минимален; расширение — добавление строки в frozenset, без изменения логики.

### `tests/unit/entrypoints/api/v1/endpoints/test_admin_cron.py` (новый, 22 теста)

| Тест | Проверка |
|---|---|
| `test_resolve_callable_rejects_non_whitelisted_module` (×6) | `os:system`, `builtins:exec`, `builtins:eval`, `builtins:__import__`, `subprocess:check_output`, `shutil:rmtree` → `ValueError` |
| `test_resolve_callable_does_not_import_rejected_module` (×6) | `importlib.import_module` **не вызывается** для отклонённых |
| `test_schedule_rejects_malicious_callable_ref` (×6) | `POST /schedule` → 400, `manager.schedule_cron` не вызван |
| `test_schedule_accepts_whitelisted_callable_ref` | легитимный ref → 201 (regression guard) |
| `test_whitelisted_module_resolves_to_callable` | whitelist указывает на существующий callable |
| `test_whitelist_contains_only_project_modules` | нет stdlib/3rd-party в whitelist |
| `test_resolve_callable_rejects_non_callable_attribute` | не-callable атрибут → `ValueError` |

Закрывает пробел из аудита: старый `tests/unit/entrypoints/test_admin_cron.py:96-105`
проверял только «модуль не найден → 400», не «модуль опасный → reject».

## 4. Verify — malicious module → reject

```
$ .venv/bin/python -c "... _resolve_callable(ref) ..."
REJECT os:system                -> Модуль 'os' не входит в cron-whitelist (разрешено: ['sr
REJECT builtins:exec            -> Модуль 'builtins' не входит в cron-whitelist (разрешено
REJECT subprocess:check_output  -> Модуль 'subprocess' не входит в cron-whitelist (разреше
REJECT shutil:rmtree            -> Модуль 'shutil' не входит в cron-whitelist (разрешено:
OK    <function check_all_services at 0x7c124a9b5170>
```

## 5. Gates

| Gate | Результат |
|---|---|
| `pytest` (new + existing admin_cron) | **30 passed** (22 new + 8 pre-existing), 1 warning, 4.17s |
| `make check-docstrings MAX_ALLOWED=0` | **exit 0** — 0 missing, 840 files |
| layer checker | **0 new, 175 legacy** (≤175/0 ✅) |
| allowlist active IDs | **27** (≤27 ✅) |
| uv.lock | **не тронут** — diff stat идентичен baseline (1 insertion/16 deletions, net-негативный) |
| `ruff check` (обоих файлов) | All checks passed |
| `mypy` (admin_cron.py) | Success: no issues |
| `bash tools/cycle-1-preflight.sh` | **exit 1 — без изменений от baseline** (см. ниже) |

### Preflight exit 1 — pre-existing, не регрессия

Baseline **до** любых моих правок уже давал exit 1 с теми же двумя FAIL:

```
[FAIL] working tree — 17 entries (разобраться)     ← до правок
[FAIL] uv.lock churn — 45 lines (проверить не растёт ли)
```

После правок: `working tree — 32 entries`, `uv.lock churn — 45 lines` (не вырос).
Рост 17→32 — это untracked-файлы других cycle-6 агентов, работающих параллельно в том же
worktree (`test_auth_selector_saml_fail_closed.py`, правки `auth_selector.py`, `di/providers/`,
`sse/handler.py`, `agent_memory.py` и др.). **Мой вклад в working tree — ровно 2 файла**:
1 modified (`admin_cron.py`) + 1 untracked (`tests/.../test_admin_cron.py`).
Ни один OK-гейт (layer / allowlist / docstring / s3.py) не деградировал.

## 6. Ограничения соблюдены

- Не изменялись: `uv.lock`, `.security/pip-audit-allowlist.txt`, `s3.py`, `tools/blue_green.sh`,
  `tests/unit/tools/test_blue_green_switch.py`.
- Правки cycle 1–5 (HEAD `4b5831e4`) не переписывались.
- `services/ai/gateway_adapter.py:128-129` не тронут.
- `except Exception` не удалялись.
- Русские docstrings не переводились; маркер `cycle-6/D-AUDIT-608` проставлен.
- `git push` не выполнялся.

## 7. Остаточный риск (вне scope T-C6-08)

- Pydantic-паттерн `^[\w.]+:[\w]+$` по-прежнему пропускает опасные строки на уровне схемы —
  отказ теперь происходит в `_resolve_callable` (400 вместо 422). Функционально безопасно;
  ужесточение паттерна до whitelist-prefix — опционально, отдельной задачей.
- `AdminRole.OPERATOR` сохраняет доступ к `/schedule`. Аудит отмечал, что OPERATOR
  «НЕ privileged enough»; сужение guard до `SUPER_ADMIN` — отдельное решение (breaking change
  для frontend), в задачу не входило. Whitelist снимает RCE-вектор независимо от роли.
