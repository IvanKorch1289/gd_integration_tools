# ADR-002: svcs как единый DI-контейнер

* Статус: accepted
* Дата: 2026-04-21
* Автор: claude
* Связанные фазы: A3 (DI consolidation)

## Контекст

В репозитории сосуществовали два параллельных DI-механизма:

1. `app.core.service_registry.ServiceRegistry` — простой name-based
   реестр (threading.Lock + dict). Используется в `service_setup.py`
   и `admin.py`.
2. `app.core.svcs_registry` — обёртка над `svcs` с дополнительным
   `_FallbackRegistry` (dead-code копия реестра на случай отсутствия
   `svcs`).

Ни один из механизмов не решал задачу целиком:

- `service_registry` не поддерживал type-based lookup, нужный для async
  кода и Protocol-driven архитектуры.
- `svcs_registry._FallbackRegistry` был мёртвым кодом (svcs уже указан
  как обязательный в pyproject через транзитивные deps).
- Два источника правды ломают Discoverability и ревью.

## Решение

1. `svcs_registry.py` становится единственным источником правды.
   `_FallbackRegistry` удалён полностью; `svcs` добавлен как direct-dep в
   `pyproject.toml`.
2. В `svcs_registry` введён универсальный `Hashable`-ключ: строка
   ("orders") и тип (`OrderService`) работают одинаково. Singletons
   кешируются в локальном `_singletons`-dict (svcs создаёт новый
   Container на операцию).
3. `service_registry.py` превращён в **deprecation shim** на один
   релиз — проксирует старый API в `svcs_registry` и выдаёт
   `DeprecationWarning`. Строка добавлена в `docs/DEPRECATIONS.md` с
   плановой датой удаления 2026-07-01 (в H3 Cleanup).
4. `service_setup.py` переписан на `register_factory(name, factory)`.
5. `services/core/admin.py` — заменён `ServiceRegistry.list_services()`
   на `svcs_registry.list_services()`.

## Альтернативы

- **Dependency-injector (Google-style)** — отвергнуто: heavyweight,
  навязывает декларативный `@provide` и конфиги XML-like.
- **FastAPI Depends только** — отвергнуто: работает только в HTTP-context,
  не покрывает background tasks, CLI tools, Streamlit pages.
- **punq / rodi** — отвергнуто: менее популярны, мало maintenance.
- **Сохранить оба реестра** — противоречит принципу «один источник
  правды» и увеличивает cognitive load новых разработчиков.

## Последствия

- Публичный API регистрации сервисов сужается до одного импорта
  (`app.core.svcs_registry`).
- Старые импорты `from app.core.service_registry import ...` продолжают
  работать один релиз, но выдают `DeprecationWarning`.
- В H3 (Cleanup) shim удаляется, запись в `DEPRECATIONS.md` переезжает в
  «Удалённые».
- Поиск мёртвого DI-кода в CI через `creosote` становится детерминированным.
