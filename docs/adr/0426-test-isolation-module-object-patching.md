# ADR-0426 — Тестовая изоляция: патч по объекту модуля, без `sys.modules.pop`

* Статус: Accepted (2026-11-03, волна 26)
* Cycle: 186 (волна 26)
* Связан с:
  - ADR-0404 (изоляция order-dependent падений; банк xfail — только для
    ограничений окружения),
  - ADR-0410 (регрессионный гейт порядка; «палец» вместо банка),
  - ADR-0284 (новых межслойных нарушений не добавляем)
* Затрагивает:
  - `tests/unit/dsl/test_action_registry_permissions.py`,
  - `tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py`,
  - `tests/unit/core/test_no_audit_proxy.py`

---

## Контекст

Полный прогон `tests/unit` давал **23 setup-ERROR** в двух файлах (0 failed при
этом), т.е. тесты не доходили до тела:

```
ERROR tests/unit/dsl/test_action_registry_permissions.py   (18)
ERROR tests/unit/plugins/composition/lifecycle/test_outbox_dispatcher_cutover.py (5)
```

Причина — не сами тесты, а способ адресации:

1. **Dotted-путь в `monkeypatch.setattr`.** Pytest резолвит
   `"pkg.sub.attr"` через `getattr(parent, "sub")`; если объект родительского
   пакета был пересоздан (например, после `sys.modules.pop` в другом тесте),
   атрибут подмодуля на новом объекте не выставлен → `AttributeError` в setup.
   Канонический пакет `src.backend.core.config.services` — с lazy
   `__getattr__` и статической картой символов: имя подмодуля (`outbox`) в
   ней отсутствует, оно появляется только как побочный эффект импорта.
2. **Bare `sys.modules.pop` без восстановления.**
   `tests/unit/core/test_no_audit_proxy.py` вычищал
   `src.backend.core.audit` и `src.backend.core.audit.facade` из
   `sys.modules` — состояние не возвращалось, кэш модулей оставался
   «полусвежим» для остальных тестов сессии.

---

## Решение

1. **Патчить объект модуля, а не dotted-путь.** Вместо
   `monkeypatch.setattr("pkg.sub.attr", value)` —
   `monkeypatch.setattr(importlib.import_module("pkg.sub"), "attr", value)`.
   Так патч не зависит от того, кто и когда пересоздал пакет.
2. **Не чистить `sys.modules` там, где это не требуется.** Proxy
   `core.audit.get_audit_log` удалён из исходников → проверка «импорт не
   работает» проходит и без очистки кэша. Если очистка всё же нужна —
   только через `monkeypatch.delitem` (восстанавливает исходное значение) или
   `patch.dict(sys.modules)` (ADR-0404/0410: order-dependent загрязнение
   устраняется, а не банкуется).
3. **Изолированная загрузка модулей в тесте** (`test_outbox_dispatcher_cutover.py`)
   обязана восстанавливать и `sys.modules`, и атрибуты, выставленные на
   реальные модули-родители: заглушка, оставшаяся в реальном модуле, ломает
   чужие тесты (наблюдалось: 64 падения в чужих файлах).

---

## Последствия

* Setup-ERROR устранены; полный прогон: **0 failed, 0 errors**.
* Правило «патч по объекту модуля» применяется к новым тестам, которые
  подменяют атрибут вложенного модуля (audit, config-сервисы, workflow).
* Регрессионный гейт порядка (`tests/unit/test_order_dependent_pollution_gate.py`)
  продолжает запрещать голый `sys.modules[...] =`/`pop` в новых тестах.
