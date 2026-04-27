# Фаза A3 — DI consolidation (svcs only)

* **Статус:** done
* **Приоритет:** P0
* **Связанные ADR:** ADR-002
* **Зависимости:** A1, A2

## Цель

Устранить дубль DI-механизмов: удалить name-based `ServiceRegistry` и
dead-code `_FallbackRegistry`, оставить `svcs` как единственный
DI-контейнер.

## Выполнено

- `src/core/svcs_registry.py` — переписан:
  - `_FallbackRegistry` удалён.
  - Поддержка name-based и type-based ключей (`Hashable`).
  - Собственный `_singletons`-кеш для lazy-singleton-семантики без
    накладных расходов svcs Container-а на операцию.
  - Публичный API: `register_factory`, `get_service`, `has_service`,
    `list_services`, `clear_registry`.
- `src/core/service_registry.py` — превращён в **deprecation shim** на
  один релиз (удаление 2026-07-01). Все вызовы проксируются в
  `svcs_registry`; выдаётся `DeprecationWarning`.
- `src/core/service_setup.py` — переписан на
  `register_factory(name, factory)`. Все 14 сервисов регистрируются там
  же.
- `src/services/core/admin.py` — заменён `ServiceRegistry.list_services()`
  на `svcs_registry.list_services()`.
- `pyproject.toml` — `svcs` не нужно было добавлять руками: он уже был
  в транзитивах; всё равно добавим direct, чтобы решение было явным
  (см. raw-диффы в A2 — deps-matrix update перенесён в A3 для чёткой
  границы).
- `docs/DEPRECATIONS.md` — добавлены 3 строки shim с плановой датой
  удаления.

## Definition of Done

- [x] `_FallbackRegistry` полностью удалён.
- [x] `svcs_registry` поддерживает name/type lookup и singleton cache.
- [x] `service_registry.py` — deprecation shim с `DeprecationWarning`.
- [x] `service_setup.py` использует только `svcs_registry`.
- [x] `admin.py` использует только `svcs_registry`.
- [x] `docs/DEPRECATIONS.md` обновлён (3 строки, дата 2026-07-01).
- [x] ADR-002 создан.
- [x] `docs/phases/PHASE_A3.md` создан.
- [x] PROGRESS.md / PHASE_STATUS.yml (A3 → done).
- [x] Коммит `[phase:A3]` с упоминанием ADR-002.

## Как проверить вручную

```bash
# Deprecation warning виден:
python -W error::DeprecationWarning -c "
from src.core.service_registry import service_registry
"
# → DeprecationWarning (exit 1 с -W error)

# _FallbackRegistry нигде нет:
grep -r '_FallbackRegistry' src/ && echo FOUND || echo CLEAN

# svcs_registry принимает и name, и type:
python -c "
from src.core.svcs_registry import register_factory, get_service
class Foo: pass
register_factory('foo', lambda: Foo())
register_factory(Foo, lambda: Foo())
print(get_service('foo'), get_service(Foo))
"
```

## Follow-up

- A4: перевод resilience-инфраструктуры на svcs_registry
  (BulkheadRegistry, RateLimiterRegistry).
- H3: финальное удаление shim `service_registry.py`.
