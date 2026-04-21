# Deprecation Log

Регистр deprecation-shim и планируемых к удалению публичных путей/модулей.

Формат строки таблицы:

| Путь/Имя | Заменён на | Введён (фаза/дата) | Плановое удаление | Тип |
|---|---|---|---|---|

## Активные shim

| Путь/Имя | Заменён на | Введён (фаза/дата) | Плановое удаление | Тип |
|---|---|---|---|---|
| `app.core.service_registry` (module) | `app.core.svcs_registry` | A3 / 2026-04-21 | 2026-07-01 (H3 Cleanup) | module |
| `app.core.service_registry.ServiceRegistry` | `app.core.svcs_registry.register_factory/get_service/list_services` | A3 / 2026-04-21 | 2026-07-01 | class |
| `app.core.service_registry.service_registry` (singleton) | `app.core.svcs_registry.register_factory/get_service` | A3 / 2026-04-21 | 2026-07-01 | singleton |

## Удалённые (для истории)

_Пусто._

---

**Правила:**

1. Любой shim должен содержать `warnings.warn(DeprecationWarning, ...)` с указанием фазы удаления.
2. Удаление — не позже 1 релиза (или в фазе H3 Cleanup, что раньше).
3. Строка из «Активные shim» переносится в «Удалённые» одновременно с коммитом, удаляющим shim.
4. Пропущенная дата удаления — основание для нового тикета cleanup и фейла `creosote`/`vulture` в CI.
