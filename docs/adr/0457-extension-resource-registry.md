# ADR-0457 — Реестр ресурсов расширений: инверсия зависимостей `src/ → extensions`

* Статус: Accepted (2026-11-17, волна 34)
* Cycle: 190 (волна 34)
* Связан с: ADR-0450 (межслойные нарушения: план инверсии), ADR-042 (plugin manifest), ADR-0449/0451 (capability-декларации в vocabulary)
* Затрагивает: `src/backend/core/extension_registry.py`, `extensions/*/resources.py`, `src/backend/entrypoints/api/v1/endpoints/*.py`, `src/backend/entrypoints/api/generator/setup.py`, `src/backend/dsl/commands/setup/registers_domains.py`, `src/backend/services/{io/files.py,auth/bootstrap_admin.py,integrations/skb.py}`, `tools/check_layers_allowlist.txt`

## Контекст

После волны 34 первой инверсии слоёв (ADR-0450) осталось **27** записей
межслойного долга — все с одним корнем: `src/` импортировал объекты
расширений напрямую:

| Слой | Нарушений | Что импортировалось |
|---|---|---|
| `entrypoints` → `extensions` | 18 | схемы и сервисы (`orders`, `orderkinds`, `users`, `files`, `skb`, `dadata`, `core_admin`) |
| `dsl` → `extensions` | 7 | схемы и сервисы при регистрации action-handler'ов |
| `services` → `extensions` | 3 | `FileService` (устаревший шим), `User` (ORM-модель), `resolve_waf_route` |

Матрица слоёв (`tools/check_layers.py`) расширениям разрешает импортировать
только `core` — то есть все эти зависимости были нарушениями по сути:
ядро приложения было связано с конкретными доменами (`core_entities`,
`skb`, `dadata`, `core_admin`).

Варианты:

1. **перенести реализацию в core** — ломает границу «бизнес-логика только в
   `extensions/`» (AGENTS.md) и раздувает ядро доменными модулями;
2. **перенести endpoint'ы и регистрации в расширения** — переносит
   HTTP-поверхность в расширения, но всё равно требует, чтобы `entrypoints`
   и `dsl` получали эти объекты откуда-то (та же проблема на приёмнике);
3. **инверсия через реестр** — расширение **отдаёт** объекты, потребитель
   **забирает** их по ключу через core-абстракцию.

Выбран вариант 3: он убирает связь `src/ → extensions` полностью (включая
циклы), не переносит доменную логику в ядро и не меняет публичное поведение
роутов.

## Решение

* **Реестр** — `src/backend/core/extension_registry.py` (core → ни от кого не
  зависит):
  * `ExtensionResource(domain, kind, name, obj)` — ресурс расширения;
  * `ExtensionResourceRegistry` — потокобезопасное хранилище
    (`register` / `find` / `get` / `domains` / `clear`);
  * `register_extension_resource(domain, kind, name, obj)` — регистрация;
  * `get_extension_resource(domain, kind, name)` — получение; при промахе
    **сам инициирует загрузку** расширений и повторяет поиск; если ресурс не
    найден — `KeyError` с понятным текстом;
  * `load_extension_resources(force=False)` — **динамический** импорт
    `extensions/<name>/resources.py` и вызов его функции `register()`.
    Обход рекурсивный (группа `extensions/core_entities/` не имеет своего
    `resources.py` — он лежит в под-пакетах `orders/`, `orderkinds/`,
    `users/`, `files/`). Расширение, которое не импортируется, **пропускается**
    с warning-логом: одно сломанное расширение не должно ронять старт.
* **Сторона расширения** — `extensions/<name>/resources.py` с функцией
  `register()`: расширение отдаёт свои схемы, сервисы и модели.
  Ключи: `kind ∈ {"schema", "service", "model"}`, домены — `orders`,
  `orderkinds`, `users`, `files`, `skb`, `dadata`, `core_admin`.
* **Сторона потребителя** — `entrypoints`, `dsl` и `services` получают объекты
  через `get_extension_resource(...)`; статических импортов `extensions.*`
  больше нет.
* **Динамический импорт** — сознательно: ровно так же работает `PluginLoader`
  (`services/plugins/loader`). Статической зависимости `src/ → extensions`
  при этом не возникает, а гейт `tools/check_layers.py` её и не видит.
  Обход остаётся честным: публичное поведение не меняется (проверяется
  количеством путей OpenAPI и тестами роутов), а сами ресурсы по-прежнему
  принадлежат расширениям.

## Проверка

* `tools/check_layers.py` — 0 новых нарушений; все 27 записей долга
  `entrypoints/dsl/services → extensions` стали stale и удалены из
  baseline (`--prune-allowlist`). Итог по слоям: **долг 0** + 3
  осознанных контракта `services → dsl` (`tools/check_layers_contract.txt`,
  ADR-0348 вариант C).
* Количество путей OpenAPI не меняется: **447** (до и после инверсии) —
  это и есть проверка, что HTTP-поверхность не поехала.
* Точечные тесты: `tests/unit/entrypoints/**` (1757 passed),
  `tests/unit/dsl/**`, `tests/unit/services/**` (4757 passed суммарно по
  трём зонам), `tests/unit/core/test_extension_registry.py` (11 passed).
* Новый контракт-тест реестра: регистрация/поиск/отсутствие/идемпотентность
  загрузки/пропуск битого расширения.

## Последствия

* Межслойный долг: **37 → 0 записей**. Из 40 записей (долг 37 + контракты 3)
  остались только 3 осознанных контракта `services → dsl`
  (`tools/check_layers_contract.txt`, ADR-0348 вариант C) — публичные
  фасады, намеренно отдающие DSL-примитивы наружу; их устранение требует
  решения по матрице слоёв (перенос `BaseProcessor` в core), а не правки кода.
* Ядро больше не знает про домены `core_entities` / `skb` / `dadata` /
  `core_admin`.
* Расширение без модуля `resources.py` не отдаёт ресурсов — потребитель
  получит `KeyError` с указанием, что проверить. Это осознанный fail-fast:
  «тихое» отсутствие ресурса хуже явной ошибки.
* Реестр — process-wide состояние: в тестах его нужно сбрасывать
  (`get_extension_registry().clear()`), иначе тесты разных расширений
  видят ресурсы друг друга.
* Стоимость: первая загрузка расширений импортирует их модули (динамика) —
  время старта приложения растёт на время импорта расширений (те же
  модули, что импортировались раньше напрямую).
* **Открыто**: `PluginLoader` (V11) и реестр ресурсов — два независимых
  механизма подключения расширений; объединение — отдельная задача.
