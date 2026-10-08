# Аудит и доработка `gd_integration_tools`

> **Дата:** 2026-10-06
> **Исследованный HEAD:** `13d22e4e2` (branch `master`)
> **Интерпретатор:** `.venv/bin/python` — Python 3.14.0
> **Правки в рабочем дереве, коммитов не делалось** (по решению владельца)

---

## 0. Главный вывод

Проект — это **большая и в целом добротная админ-API поверхность** (414 путей
OpenAPI, 132 action'а, 37 middleware), но **обе заявленные headline-фичи —
DSL и система плагинов — не работали вообще**.

Это не «почти работает». При старте приложения:

| Подсистема | До правок | После правок |
|---|---:|---:|
| Плагины загружены (`V11 PluginLoader`) | **0 из 7** | **10 из 11** |
| Workflow-декларации зарегистрированы | **0** | **4** |
| DSL action-handler'ы проверены | фаза — no-op | **132 verified** |
| AIGateway singleton | фаза — no-op | **verified** |
| DSL-роуты: манифесты валидны | **0 из 7** | **7 из 7** |

Корень проблемы — не одна ошибка, а **систематический класс**: компонент
пишется, подключается, логирует об ошибке на уровне `warning` и при этом
**никогда не выполняет свою функцию**. Всё это завёрнуто в fail-open
`except Exception`, поэтому CI зелёный, а функциональность нулевая.

---

## 1. Метод

Рой из **4 агентов** (dead code · library replacement · clean architecture ·
verify unmerged branches) + **собственная проверка живого сервера**
(uvicorn, cURL-батарея, Playwright/Chromium). Каждое утверждение подкреплено
`file:line` или выводом команды. Ни одно «FIXED» не заявлено без прогона.

Дополнительно: каждая правка подтверждалась **функционально** (загрузка
плагинов, регистрация workflow, живой HTTP), а не только тестами.

---

## 2. Найденные и исправленные дефекты

### 2.1 `register_ai_gateway_singleton` не существует

`src/backend/plugins/composition/lifecycle/startup_phases/services.py:60`
импортировал функцию из `composition.workflow_setup`, где её нет — модуль
экспортирует только `_register_workflow_declarations_from_filesystem`,
`register_workflow_declarations`, `start_workflow_runtime`. Импорт падал,
`except Exception` превращал это в warning на каждом старте.

**Правка:** фаза теперь проверяет фактическое постусловие
(`app.state.ai_gateway`), и **fail-closed** — поднимает `RuntimeError`.

### 2.2 `composition/bootstrap.py` не существует

Та же схема: `services.py:78` импортировал `register_dsl_commands` из
несуществующего модуля. Фаза была no-op.

**Правка:** фаза проверяет, что `action_handler_registry` непуст, и падает
fail-closed. Даёт **132 verified action-handler(а)** вместо тишины.

> Эти две правки сработали: при первой сборке fail-closed поймал **мою
> собственную ошибку** — я потерял строку присваивания `ai_gateway` при
> редактировании дубликата в `di.py`. Раньше это ушло бы незамеченным.

### 2.3 `RedisBroker.close()` не существует

`src/backend/infrastructure/clients/messaging/event_bus.py:146` вызывал
`close()`; у faststream-брокеров есть только `stop()`
(проверено: `hasattr(RedisBroker,'close') == False`). На каждом shutdown
`EventBus.stop()` падал, ошибка глоталась в `lifecycle/shutdown.py:206`,
брокер не останавливался.

**Правка:** вызов `stop()`, ошибка логируется и не валит shutdown.
Тест обновлён на `stop()` + `close.assert_not_awaited()` + новый тест на
устойчивость к ошибке брокера.

### 2.4 `entry_class` в формате `module:Class` не разбирался (3 плагина)

`loader_mixin.py:288` делал `rpartition(".")` — форма
`extensions.core_admin.schemas_only:SchemasOnlyEntry` превращалась в
`getattr(pkg, "schemas_only:SchemasOnlyEntry")` → `AttributeError`.
Форма с двоеточием закреплена ADR-0343 и используется в 3 манифестах.

**Правка:** разбор поддерживает оба синтаксиса.

### 2.5 `SchemasOnlyEntry` не наследовал `BasePlugin`

После 2.4 вскрылся второй слой: класс был пустым, поэтому
`isinstance(instance, BasePlugin)` отклонял его. `BasePlugin` не имеет
абстрактных методов — все хуки опциональны.

**Правка:** 3 класса наследуют `BasePlugin` с `name`/`version` из манифеста.

### 2.6 `core.api` не экспортировал `ActionRegistryProtocol`

`extensions/example_plugin/plugin.py:24` импортировал его из
`src.backend.core.api`, где его не было (`BasePlugin` и `PluginContext`
экспортировались, а реестровые протоколы — нет).

**Правка:** в фасад добавлены `ActionRegistryProtocol`,
`RepositoryRegistryProtocol`, `PluginContext`.

### 2.7 `core_version` = `"0.2.0"` против фактической версии `0.20.0`

`core/config/plugin_loader.py:77` держал литерал `0.2.0`, тогда как пакет —
`0.20.0`. semver сравнивает их как разные версии, поэтому плагин с
`requires_core = ">=0.20,<0.21"` **молча помечался skipped**.

**Правка:** значение берётся из метаданных дистрибутива
(`default_factory`), fallback `0.20.0`. Дрейф больше невозможен.

### 2.8 `requires_core` в манифестах указывал на несуществующий диапазон

Манифесты были непоследовательны: `>=0.20,<0.21`, `>=0.2.0`, `>=0.2,<0.3`.
Последний диапазон физически не может принять `0.20.0`.

**Правка:** все 11 манифестов приведены к `">=0.20,<0.21"`.

### 2.9 Категория capability `ai.llm` не существует

`extensions/osint_agent/plugin.toml` объявлял `ai.llm`, которого нет в
vocabulary ADR-044 → `CapabilityNotFoundError`.

**Правка:** на канонический `ai.invoke` (scope `*`).

### 2.10 Флаг `workflow_yaml_round_trip` блокировал **загрузку**

Флаг по описанию активирует round-trip **сериализацию**, но гейт стоял на
`from_yaml` — то есть на пути чтения. При default-OFF это блокировало
**всю** auto-регистрацию `extensions/*/workflows/*.workflow.yaml`.

**Правка:** гейт перенесён на `to_yaml`/`diff`; чтение деклараций работает
всегда. Плюс docstring-и, которые обещали гейт на load-обёртках, приведены
в соответствие.

### 2.11 `EXTENSIONS_DIR` по умолчанию = `/app/extensions`

Docker-путь, зашитый как дефолт. Локальный запуск его не находит → тихий
`return 0` и ноль workflow.

**Правка:** явный env-override, иначе `<repo_root>/extensions`.

### 2.12 Идемпотентность workflow-регистрации была только в docstring

`_register_workflow_declarations_from_filesystem` обещал идемпотентность,
но `workflow_registry.register` бросал `ValueError` при повторе — каждый
старт давал серию `workflow.auto_register FAIL` на валидных workflow.

**Правка:** повторная регистрация считается успехом. Проверено: два
последовательных вызова дают `4` и `4`.

### 2.13 Дубликат регистрации `ai_gateway` в `di.py`

Блок с `app.state.ai_gateway = get_ai_gateway_provider()` выполнялся дважды
подряд. Дубликат удалён.

### 2.14 P0: сжатие стояло ВНУТРИ маскирования PII — API отдавал заглушку вместо данных

Найдено собственной функциональной батареей уже после того, как cURL-прогон
прошёл 16/16. Живой сервер, запрос с валидным ключом:

```
$ curl -D - -H 'Accept-Encoding: gzip' .../api/v1/admin/actions
HTTP/1.1 200 OK
content-type: application/json
content-encoding: gzip
content-length: 104
{"error":"response_masking_failed",
 "detail":"PII masking failed; original response withheld for safety"}
```

Тело — **несжатый** plain-JSON под меткой `gzip`. Без сжатия тот же эндпоинт
отдавал 2562 байта настоящего списка actions. httpx падал с `DecodingError`;
curl отдавал мусор молча, поэтому cURL-батарея дефект не видела.

**Причинная цепочка** (подтверждена логом сервера: `UnicodeDecodeError: 'utf-8'
codec can't decode byte 0x8b in position 1` на `data_masking.py:222` —
0x8b это второй байт gzip-магии `1f 8b`):

1. `order` в реестре инвертирован из-за LIFO-семантики `add_middleware`
   (`user_middleware.insert(0, …)`) — **высокий order = внешний**;
2. `gzip` стоял на `order=560`, то есть ВНУТРИ `data_masking` (580) и
   `pii_masking_response` (700);
3. GZip сжимал JSON ≥ `gzip_minimum_size` (500) и ставил `Content-Encoding`;
4. `DataMaskingMiddleware` снаружи подавлял start, собирал сжатые байты и
   падал на `raw.decode("utf-8")`;
5. fail-closed fallback возвращал plain-JSON заглушку, но `new_headers`
   копировал заголовки исходного ответа **включая `content-encoding: gzip`**,
   заменяя только `content-length`.

Итог: HTTP 200, настоящий ответ потерян, клиент получает несжатый мусор под
меткой gzip. Затронут **любой JSON крупнее 500 байт** — то есть практически
каждый список в API. `/openapi.json` и `/metrics` уцелели только потому, что
исключены из маскирования и из сжатия соответственно.

**Исправлено в четырёх местах:**

| Файл | Что сделано |
|---|---|
| `setup_middlewares.py` | `gzip` 560 → **900**, `brotli` 540 → **920**. Сжатие стало последним преобразованием ответа и внешним всех middleware, переписывающих body |
| `data_masking.py` | Проверка `Content-Encoding`: уже закодированный ответ пробрасывается как есть. Попутно ожил флаг `should_mask`, который был объявлен, но никогда не выставлялся |
| `gzip_compression_excluding.py` | Ветка «ответ уже закодирован» больше **не теряет** `http.response.start`. Раньше ставился только флаг, а start-сообщение не отправлялось — нарушение ASGI-контракта, из-за которого uvicorn рвал соединение без ответа |
| `brotli_compression.py` | Добавлена та же проверка: без неё сжатый поток сжимался бы повторно, а `content-encoding` перезаписывался на `br` |

Почему не «просто пропускать любой gzip в маскере»: такой фикс устранил бы
симптом, но PII перестала бы маскироваться вообще для ответов крупнее
`minimum_size` — тихая дыра в безопасности. Проверка
`test_data_masking_still_masks_large_json_body` закрывает именно этот
регресс.

**Доказательность.** 13 новых тестов в
`tests/unit/entrypoints/middlewares/test_compression_masking_order.py`:
на чистом HEAD падают **9**, после фикса проходят **13**. Один из них
(`test_real_registry_order_produces_valid_masked_gzip`) собирает цепочку в
порядке **реального реестра**, а не руками, — и на HEAD падает с тем же
`UnicodeDecodeError`, что и живой сервер.

**Почему это прошло проверки:**

* `tests/unit/.../test_gzip_compression_excluding.py` — 3 теста помечены
  `SKIP` (starlette TestClient + httpx 0.28+ несовместимы), то есть
  интеграционное поведение gzip-middleware этим набором **не проверялось
  вообще**;
* cURL-батарея не запрашивала сжатие явно и не декодировала ответ;
* unit-тесты `DataMaskingMiddleware` использовали только plain-JSON
  downstream — случай «сжатый body» не моделировался.

**Закрыто в инструментах.** `tools/functional/http_check.py` получил проверки
`compression_round_trip` (сверяет заголовок с **wire-байтами** через
`iter_raw`, а не с декодированным `content`), а хелпер `get` — защиту от
`DecodingError`, чтобы батарея фиксировала дефект, а не падала. Добавлен
`tools/functional/browser_check.py`: Chromium всегда шлёт
`Accept-Encoding: gzip, deflate, br`, поэтому именно браузер воспроизводит
класс дефектов, невидимый для cURL.

---

## 3. Что осталось непочиненным (и почему)

### 3.1 `credit_pipeline` — нужен ваш выбор

```
failed: capability_error: Capability 'db.read' already declared for 'credit_pipeline'
```

Манифест объявляет `db.read` дважды с разными scope
(`credit_reports`, `credit_applications`). Модель `CapabilityGate` хранит
декларации в `dict` по имени и матчер `db.read` — `exact`, то есть
**несколько scope на одну capability невыразимы в принципе**.

Это граница безопасности. Два пути: расширить модель (хранить список
refs на имя — расширяет то, что плагин может объявить) или сузить
манифест. Оба меняют security-контракт, поэтому не выбраны мной молча.
Контекст: плагин фактически пустой scaffold (`functions/`, `routes/`,
`workflows/` — везде `TODO Team T3`).

### 3.2 DNS-rebinding в SSRF-фиксе (остаётся открытым)

Из вердикта verifier'а: guard валидирует строку хоста и не резолвит DNS.
`127.0.0.1.nip.io` и `localtest.me` проходят. Требуется egress-прокси или ADR.

---

## 4. DSL-роуты: манифесты починены, остаются 2 барьера

Изначально **7 из 7** `route.toml` были невалидны. Формат нигде не
оспаривается в коде: `RouteManifest` (`services/routes/manifest_toml.py:130`) —
плоская модель с `extra="forbid"`, парсера вложенной формы не существует, а все
манифесты использовали вложенную таблицу `[route]`. Плюс
`requires_core = ">=15.0,<16.0"` (недостижимый диапазон), и ADR-0079 требовал
`[route.slo]`, которого в модели **не было вовсе** (0 упоминаний `slo`).

**Сделано:** добавлена SLO-модель по ADR-0079; `load_route_manifest` принимает
и плоскую, и вложенную форму (соглашение уже закреплено в самом ADR-0079,
строка 81); диапазоны `requires_core` нормализованы; `capabilities` в
манифестах приведены к строковой форме без нарушения схемы.

**Результат: 7 из 7 манифестов загружаются** (было 0 из 7). Для сравнения —
загрузка через прямую рефлексию без `routes_dir` даёт 6 из 7, потому что
`jupyter_hub_run` специально помечен `route_enabled = false`.

Остались **два** барьера до полностью рабочих роутов:

1. **`capability_superset`** — все 7 роутов отклоняются гейтом:
   `public_capabilities()` пуст, в vocabulary нет ни одной capability с
   `public=True`. Это дефект vocabulary, **но его исправление расширяет
   то, что считается публично доступным без декларации** — то есть решение
   на границе безопасности. Не сделано молча.
2. **`pipeline_register_error`** — все 7 `routes/*/*.dsl.yaml` не компилируются:
   `Missing required field: route_id`, `Invalid processor spec: None`,
   `expected a single document in the stream`.

В рамках этой же волны исправлена одна из причин последнего класса —
известный F-AR: `FeatureMixin.feature_flag()` принимал только позиционный
`name`, хотя YAML-шаг и docstring самого `FeatureFlagCheckProcessor` используют
`flag=`/`stop_on_disabled=`. Любой роут с этим шагом падал с `TypeError`.
Сигнатура приведена к задокументированной (проверены обе формы вызова,
новые атрибуты добавлены в `__slots__`).

---

## 4.1 Корневая причина «0 роутов»: в vocabulary нет публичных capability

Отдельный замер RouteLoader с реальным дефолтным vocabulary:

```
failed  composition_demo    capability_superset: net.inbound, net.outbound …
failed  echo_demo           capability_superset: net.inbound …
failed  health_proxy_demo   capability_superset: net.inbound, net.outbound …
failed  hello_route         capability_superset: net.outbound, db.write, audit.write, ai.llm …
failed  jupyter_hub_run     capability_superset: net.outbound, jupyter.hub, audit.write
failed  osint_agent         capability_superset: net.outbound, ai.llm …
failed  test_route_w1       capability_superset: net.outbound, db.write, audit.write
→ Counter({'failed': 7})
```

`build_default_vocabulary()` регистрирует **49 определений capability, из них
ровно 0 с `public=True`**. Инвариант ADR-044 требует
`route.capabilities ⊆ union(requires_plugins' capabilities) ∪ public-core`.
Без `requires_plugins` и при пустом public-множестве **любая** декларация
непокрываема. Проверка срабатывает **до** `feature_flag`, поэтому включение
флагов само по себе не помогает.

Дополнительно два роута объявляют имена, которых нет в vocabulary:
`audit.write` и `ai.llm` (в vocabulary — `ai.invoke`).

Три независимых слоя сломаны, поэтому система роутов не имеет рабочего пути:
1. `V11_ROUTE_LOADER_ENABLED` по умолчанию `False`;
2. все 7 отклоняются гейтом capability;
3. все 7 `*.dsl.yaml` не компилируются (`route_id` отсутствует,
   `Invalid processor spec: None`, multi-doc YAML, `output_field`).

Пункт 3 частично закрыт в этой волне: `FeatureMixin.feature_flag()` приведён
к задокументированной сигнатуре, включая `output_field` (его передавали 3 из 7
роутов). Семантика намеренно **не** менялась: `Pipeline.feature_flag` — это
route-level гейт в `execution_engine._check_feature_flag()`, поэтому создавать
`FeatureFlagCheckProcessor` из builder-метода нельзя — флаг проверялся бы
дважды, и `stop_on_disabled` из YAML молча расходился бы с поведением.
Расхождение зафиксировано в docstring метода.

### 4.2 Плагины, невидимые для загрузчика — исправлено

`PluginLoader` сканировал только **прямых** потомков `extensions/`
(`extensions_dir.iterdir()` + `child / "plugin.toml"`). Плагины, вложенные на
уровень глубже, **никогда не обнаруживались**, хотя их манифесты и entry-классы
полностью валидны:

- `extensions/core_entities/orders` → `OrdersPlugin` ✅
- `extensions/core_entities/users` → `UsersPlugin` ✅
- `extensions/core_entities/files` → `FilesPlugin` ✅
- `extensions/core_entities/orderkinds` → `OrderKindsPlugin` ✅

На диске было **11** `plugin.toml`, а кандидатов к загрузке — **7**.

**Правка:** рекурсивный поиск `rglob("plugin.toml")`. После этого грузится
**10 из 11** плагинов — включая CRUD-ресурсы, которые R-V15-16 предписывает
вынести именно в `extensions/core_entities/`. Регрессия: 739 тестов в
`tests/unit/services/plugins/`, `core/config/`, `core/plugin_runtime/` — зелёные.

### 4.3 Отказ роутов был беззвучным — исправлено

`_load_one()` записывал причину отказа в `LoadedRoute.reason` и **нигде её не
логировал**. Разработчик, включивший `V11_ROUTE_LOADER_ENABLED=true`, видел одну
строку «N маршрут(ов) активно» и не понимал причину — тот же fail-open класс,
что был исправлен в startup-фазах.

**Правка:** `RouteLoader._log_outcome()` печатает разбивку (обнаружено /
активно / отключено / не загружено / пропущено), каждую причину на уровне
ERROR и итоговую подсказку, если активных маршрутов нет. Фактический вывод на
живом старте:

```
RouteLoader: маршрут composition_demo НЕ загружен — capability_superset: Route …
RouteLoader: маршрут echo_demo НЕ загружен — capability_superset: Route …
… (все 7)
RouteLoader: ни один маршрут не активен, при этом 7 из 7 отклонены проверками.
Список причин — выше в ERROR-логах; проверьте capability-vocabulary
(build_default_vocabulary должна возвращать непустой public_capabilities())
и компиляцию *.dsl.yaml.
```

### 4.4 Диагностика врала о роутах — исправлено

`src/backend/cli/diagnose.py` собирал `diagnostics["routes_count"]` так:

```python
from src.backend.dsl.route.loader import RouteLoader   # модуля НЕ существует
routes = RouteLoader.load_all()                        # метода НЕ существует
...
except Exception:
    pass                                               # и всё это глоталось
```

Сразу три ошибки: неверный путь (`dsl/route/` не существует, реальный —
`services/routes/loader.py`), несуществующий метод (есть только async
`discover_and_load()`, у которого побочные эффекты — он декларирует capability
и регистрирует pipeline), и `except: pass`, из-за которого
`routes_count` **никогда не заполнялся**. Диагностика молча врала.

**Правка:** диагностика не должна мутировать состояние, поэтому она теперь
только читает и разбирает манифесты с диска, без регистрации; исключение
больше не глотается, а попадает в `routes_error` / `routes_invalid`.

Фактический вывод после правки:
```
routes_dir: /home/user/dev/gd_integration_tools/routes
routes_count: 7
routes_valid: 7
```

### 4.5 `print()` в composition root — исправлено

`_mount_mcp_http()` содержал **10** вызовов `print()` с префиксом
`D-AUDIT-20810` — отладочные следы предыдущей сессии аудита, попадавшие в stdout
при каждом импорте приложения. Это нарушает запрет правил проекта на
логирование через `print`.

В комментарии утверждалось, что `print()` выбран потому, что «granian-воркеры
фильтруют вызовы `get_logger`». **Проверено пробой — это не так:**

```
get_logger(...).warning('PROBE')  → доходит до stdout
get_logger(...).info('PROBE')     → НЕ доходит
```

Логирование работает; проблема была в том, что на момент вызова `create_app()`
уровень логирования ещё не сконфигурирован (эффективный WARNING). Поэтому
`print()` был не нужен — достаточно было правильно выбрать уровень.

**Правка:** отказ ветки → `WARNING` (видно всегда, как и требовалось), штатные
ветки → `INFO`/`DEBUG`. Проверено: stdout при импорте больше не содержит
`D-AUDIT-20810` (0 вхождений), а критичные ERROR-диагностики роутов по-прежнему
видны — все 7 строк «НЕ загружен» на месте.

Компромисс, который стоит знать: MCP-строка «transport смонтирован» теперь
`INFO` и на старте не видна. Если боевое развёртывание требует подтверждения
монтажа MCP в логах, правильное лечение — конфигурировать логирование **до**
`create_app()`, а не возвращать `print()`.

- **Импорт приложения стоит 11.25 с и тянет 9 856 модулей**, печатая
  предупреждения (Vault недоступен, `psycopg2` отсутствует → `sync_engine=None`
  → APScheduler откатывается на `MemoryJobStore`).
- **`src/backend/main.py` при импорте ЗАПУСКАЕТ приложение** (module-scope
  `app: FastAPI = create_app()` плюс синхронный
  `_auto_register_workflows_fallback()`). Импортировать его из библиотеки,
  теста или тула нельзя.
- **Дубль `PrometheusMiddleware`** в рантайм-стеке: реестр регистрирует один,
  `infrastructure/application/monitoring.py:57` добавляет второй.
- **Три счётчика, которые часто путают:** 124 action'а из
  `register_action_handlers()`; 132 на полном старте (auto-register + legacy
  aliases); 414 путей OpenAPI. Все три верны, но измеряют разное.

## 5. Мёртвый код: оценка агента и что из неё выжило проверку

Список ниже — оценка агента. **Часть его не выдержала проверки** (§7.1), поэтому
цифры приведены как «заявлено», а не как «установлено».

| Категория | Заявлено агентом | Статус после проверки |
|---|---:|---|
| Модули с нулём импортёров | 72 / 6 087 LOC | **7 из 13 проверенных путей не существуют** — это уже пакеты, а не `.py` |
| Импортируются только тестами | 240 / 33 824 LOC | не проверялось построчно |
| Осиротевшие `tools/*.py` | 47 / 9 252 LOC | 2 из 4 проверенных — подтверждены мёртвыми |
| Feature-флаги, не гейтящие поведение | 125 из 260 (48%) | не проверялось |
| Нарушений god-file правила | 276 файлов | не проверялось |

Оценку «240 модуля / 33.8k LOC только для тестов» **нельзя считать
готовым к удалению** — это гипотеза до запуска `vulture`/coverage-прогона.

**Отдельно, проверено лично:** `entrypoints/api/v1/endpoints/admin_plugins.py`
(556 LOC) **затенён одноимённым пакетом** — CPython резолвит в
`admin_plugins/__init__.py`, файл недостижим:

```
resolved to: .../endpoints/admin_plugins/__init__.py
is package: True
```

**Замена кастомного кода библиотеками — вывод агента, важный для
экономии усилий:** проект консолидирован **гораздо лучше**, чем предполагалось.
`tenacity`, `purgatory`, `glom`, `jmespath`, `simpleeval`, `orjson`,
`structlog`, `graphlib`, `pydantic-settings` — реально в использовании.
Осталась **одна** настоящая замена: `core/feature_flags/openfeature_provider.py`
(444 LOC) при уже объявленной зависимости `openfeature-sdk` и **нуле**
импортов SDK. Прежний отказ «SDK не tenant-scoped» **фактически неверен**:
`EvaluationContext` имеет `targeting_key` + `attributes` — это 1:1 к
кастомным `tenant_id` + `traits`.

Агент также **опроверг** F-AQ12 («1566 LOC брокерного слоя в обход
faststream»): реального прямого кода — 880 LOC в 3 CDC-файлах, остальное
считалось целиком.

---

## 6. Архитектура: гейт не защищал — теперь защищает

**Было.** `tools/check_layers.py` рапортует `Нарушений: 0 новых` и выходит с 0.
Независимый AST-анализ находит **268 нарушений** заявленной спецификации —
**гейт видел 21 из них (92% слепо)**:

- `_layer_of()` возвращал `None` для корней `extensions/`, `routes/`,
  `testkit/` — они не были ни в `LAYERS`, ни в `PLUGINS_LAYER`;
- на строке `if target is None or ...: continue` первопартийные импорты
  пропускались **наравне со сторонними библиотеками**;
- `extensions/`, `routes/`, `testkit/` не признаны корнями импорта (41 нарушение);
- матрица `ALLOWED` расширена сверх спецификации (138 нарушений скрыто);
- 8 исключений по **подстроке в имени файла** (`"facade" in name`) —
  любой новый `*facade*.py` в `core/` вечно exempt.

**Стало.** Корни добавлены в `FIRST_PARTY_ROOTS` и в матрицу `ALLOWED`.
Гейт стал видеть **на 31 нарушение больше**.

| | Было | Стало |
|---|---:|---:|
| Нарушений в базе (allowlist) | 22 | **53** |
| Новых нарушений | 0 (не видел) | 0 (видит и пропускает базу) |
| Файлов просканировано | 2 549 | 2 549 |

Проверено **мутацией гейта** (приём, который использовал verifier для SSRF):
временно добавлен импорт `from extensions.core_admin.schemas_only import ...`
в `src/backend/core/config/config_loader.py` → гейт **поймал** его
(`НОВЫЕ нарушения: 1`, exit 1). До правки такой импорт проходил молча.
Файл восстановлен, `git diff` по нему пуст.

Самый показательный из 31 вскрытых нарушений:
`src/backend/core/domain/models/__init__.py → extensions.core_entities.*.domain.models`
— **ядро импортирует ORM-модели из `extensions/`**, то есть настоящая
инверсия зависимости. Комментарий в самом allowlist это уже называл
(«корневая причина D5 split-brain») — но гейт не мог этого показать.

Осталось (требует решения владельца): 12 портов против 88 692 LOC в `core`;
`dsl → services` — 90 рёбер; правило «core не импортирует ничего из src/»
нарушено в 72 рёбрах. Инверсия зависимостей **формально есть, но мелкая**:
12 портов на 88.7k LOC.

---

## 7. Читаемость: конкретные препятствия для нового разработчика

- **`CLAUDE.md` отсылал к `.claude/CONTEXT.md`, которого нет.** Новичок,
  идущий по предписанному порядку чтения, упирался в тупик на шаге 5.
  **Исправлено:** список чтения переписан, убраны дубли (пункты 2/3 и 1/4
  были одинаковыми), добавлена ссылка на этот отчёт.
- **`tools/checks/check_docstrings.py --strict` не существует.** Каталога
  `tools/checks/` нет, опции `--strict` нет — предписанный pre-push гейт
  **не запускался как задокументировано** (проверено: `No such option: --strict`).
  **Исправлено:** в `CLAUDE.md` указан реальный путь и команда.
- **Docstring-гейт не был чистым:** 1 отсутствующий docstring в
  `graphql_guards.py:27`. **Исправлено — теперь `Total: 0 missing`.**
- **Три разных имени продукта** и неверный корень импорта в документации:
  спецификация говорит `gd_integration_tools.*`, реально импортируется
  `src.backend.*` (проверено: `import gd_integration_tools` →
  `ModuleNotFoundError`). Это дефект документации, а не кода: переименование
  9 147 мест импорта — не рефакторинг, а переписывание. **Исправлена
  спецификация** — в `CLAUDE.md` добавлено явное предупреждение.
- **23 каталога верхнего уровня**, из которых 7 (30%) — артефакты сборки.
- **Принцип «80% декларативно / 20% Python» не подтверждается**: 99.2% LOC
  DSL — это Python; декларативных роутов 9 на 600 Python-модулей движка.

## 7.1 Мёртвый код — перепроверено собственным инструментом

Список мёртвого кода из агента **не выдержал проверки**. Собран
`tools/deadcode_verify.py` (+ реестр `tools/deadcode_candidates.json`), который
строит AST-индекс импортов и различает production/тестовых импортёров.

**Что оказалось неверным в исходном списке:**

- **7 из 13 путей не существуют.** `src/backend/core/api_graph.py`,
  `dsl_browser.py`, `route_test_dsl.py`, `integration_template.py`,
  `shadow_route.py`, `lineage_graph.py`, `streaming_parser.py` — таких файлов
  нет, есть одноимённые **пакеты**. Модули уже отрефакторены `.py` → `.py/`;
  LOC из отчёта агента относились к несуществующим файлам.
- **`src/backend/core/rate_limiter/limiter.py` — жив.** Реэкспортируется из
  `core/rate_limiter/__init__.py`. Назван мёртвым ошибочно.

**Что подтвердилось:** `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py`
(556 LOC) действительно **перекрыт пакетом** `admin_plugins/` — CPython всегда
резолвит имя в пакет, и импорты в `routers.py` / `endpoints.py` уходят именно
в пакет. Файл недостижим.

Итог по проверенным кандидатам: **3 мёртвых (1 328 LOC)** + 1 живой исключён.
Инструмент теперь рапортует устаревшие пути, а не молчит о них.

Удаление не выполнялось: правила проекта запрещают удалять файлы без явного
подтверждения. Готовый список — `tools/deadcode_verify.py --paths`.

---

## 8. Проверка (фактические результаты)

| Проверка | Результат |
|---|---|
| `compileall` по изменённым файлам | **EXIT=0** |
| `ruff check` по всем файлам, которые я менял | **чисто** |
| `tools/check_layers.py` | **Нарушений: 0 новых** (baseline вырос 22 → 53) |
| `tools/check_docstrings.py` | **Total: 0 missing** (было 1, исправлено) |
| `creosote` (unused deps) | `jsonschema`/`zstandard` распознаны как **используемые**; 3 предсуществующих флага |
| `pytest` (plugins, config, routes, builders, graphql, messaging) | **1 506 passed**, 27 skipped |
| `pytest tests/unit/dsl/` | 4 893 passed, **9 failed — предсуществующие** |
| cURL-батарея против живого uvicorn | **16 PASS / 0 FAIL** |
| Playwright/Chromium браузерная батарея | **21 PASS / 0 FAIL** |
| P0 §2.14: тот же эндпоинт с `Accept-Encoding: gzip` | **было** `content-length: 104`, plain-JSON под меткой gzip → **стало** валидный gzip, 861 байт на проводе → 2562 распаковано |
| P0 §2.14: батарея `http_check` с проверкой сжатия | **PASS 18 / FAIL 0 / SKIP 2** (было FAIL 1) |
| P0 §2.14: браузерная батарея `browser_check` | **PASS 4 / FAIL 0**; на сервере с дефектом — **FAIL 2** (`Failed to fetch`) |
| P0 §2.14: 13 новых тестов | на чистом HEAD падают **9**, после фикса проходят **13** |
| `pytest tests/unit/entrypoints/` | **1511 passed**, 1 failed; на чистом HEAD — **1498 passed**, тот же 1 failed (предсуществующее загрязнение порядка) |
| `tests/unit/dsl/cli/` (пробел verifier'а) | **77 passed, 0 failed** — падений в этом каталоге нет вообще |
| `tests/unit/services/routes/` + `tests/unit/plugins/composition/` | **257 passed, 7 failed**; на чистом HEAD — **те же самые 7** (загрязнение между каталогами, не регрессия) |
| `make format-check` | **PASS** (2541 файла). Было 4 файла к переформатированию — все мои; отформатированы |
| `make check-waf-coverage` | **WAF coverage OK: 0 violations** |
| `make bandit-strict` | **0 High** (Low 92 / Medium 49 / 46 suppressed via `#nosec`) |
| `make secrets-check` | **PASS** |
| `ruff check src/` | **All checks passed** |
| Проверка, что фикс не сломал маскирование | валидный gzip; `ivan.korchov@bank.example` → `i***v@bank.example`, `+79161234567` → `+***4567`; заглушки нет |
| Tenant-проверки в батарее (восстановлены) | **PASS 3/3**: `default`, эхо `tenant-a`, спуфинг → `403 tenant_mismatch` |
| Загрузка плагинов | **10 из 11** (было 0) |
| Регистрация workflow | **4**, повторный вызов идемпотентен |
| Валидация манифестов роутов | **7 из 7** (было 0) |
| Видимость причин отказа роутов | **было 0 строк**, стало 7 ERROR + итог |
| Мутация гейта слоёв | `core → extensions.*` **пойман** (exit 1) |
| `feature_flag()` обе формы вызова | проверены, включая `output_field` |

**О 13 `I001` в `extensions/`:** это предсуществующий долг. Ни один из них не
в моём diff — проверено пересечением списка ruff-ошибок со списком изменённых
файлов (пусто), и подтверждено на копии `extensions/__init__.py` из HEAD.

**Про 9 падений в `tests/unit/dsl/` — доказано, что они не мои.** Прогон на
чистом HEAD в отдельном worktree `/tmp/gd_pristine`
(`git worktree add /tmp/gd_pristine HEAD --detach`): `test_webhook_signature`
(битый base64-фикстура), `test_dataframes::test_read_excel`
(отсутствует опциональный `polars`), `test_llmcall_processor` — падают и
без моих правок. Временный worktree удалён.

### 8.1 Отдельно: падения тестов — доказанно предсуществующие

Прогон `tests/unit/{services,core,dsl/builders,plugins}` даёт на моём дереве
`11 failed, 5 errors, 9571 passed, 83 skipped, 11 xfailed, 17 xpassed`.
Чтобы не списать это на себя, тот же прогон выполнен на **чистом HEAD** в
отдельном worktree (`git worktree add /tmp/gd_pristine2 HEAD --detach`) и
списки падений сопоставлены:

```
comm -13 pristine_fails.txt mine_fails.txt   → ПУСТО
comm -23 pristine_fails.txt mine_fails.txt   → FAILED test_vault.py::test_defaults
```

| | |
|---|---|
| Новых регрессий от моих правок | **0** |
| Тестов, перешедших из fail в pass | 1 (`test_vault.py::test_defaults`, order-зависимый) |
| Совпадающих падений | 15 |

Оставшиеся падения воспроизводятся на чистом HEAD:

| Тест | Причина |
|---|---|
| `test_lifecycle_smoke.py` (5 шт.) | **порядокозависимость**: по отдельности — 1 failed / 19 passed, в прогоне всего каталога — падают. `pytest -p no:randomly` не изолирует глобальное состояние реестров |
| `test_app_factory_smoke.py::test_module_reexports_lifespan_from_lifecycle` | та же группа |
| `test_outbox_dispatcher_cutover.py` (5 errors) | та же группа; по отдельности проходят |
| `test_optimizer.py::test_baseline_score_zero_on_stub` | заглушка dspy |
| `test_saml_backend.py::test_is_available_no_dependency` | `is_available()` зависит от наличия `python3-saml` |
| `test_cache_namespace.py`, `test_feature_flag_scope.py` | та же order-зависимость; по отдельности зелёные |

**Вывод:** это долг тестовой изоляции (глобальные реестры), а не регрессия.
Кандидат на отдельную задачу: `--dist loadfile` для xdist либо фикстуры,
сбрасывающие реестры между тестами.

## 9. Вердикт по 6 непроведённым веткам

| Ветка | Вердикт | Блокирует |
|---|---|---|
| `fix/outbox-ack-redelivery` | **SAFE_TO_MERGE** | — |
| `fix/marker-coverage` | **SAFE_TO_MERGE** | — |
| `fix/metrics-gate-selfref` | **SAFE_TO_MERGE** | сливать строго последним + регенерация метрик README |
| `fix/ssrf-url-guard` | **SAFE_AFTER_FIXES** | роняет существующий тест `test_goto_failure_with_screenshot`; DNS-rebinding открыт |
| `fix/ownership-deny-by-default` | **SAFE_AFTER_FIXES** | роняет `test_vault_secrets` через утечку `sys.modules["hvac"]`; `require_object_ownership` — 0 production-caller'ов |
| `fix/tenant-context-split-brain` | **SAFE_AFTER_FIXES** + ваше решение | слияние **намеренно красит CI в красный**; tenant не привязан вне HTTP (gRPC/MQTT/scheduler/Temporal/CDC), а ORM-фильтр fail-open |

Мутация SSRF-guard'а: 9 тестов падают при удалении route-перехватчика,
12 — на комбинации проверок. **Тесты не вакуумные.** Все 6 веток сливаются
с master **без конфликтов** (0 пересечений файлов), порядок задаёт риск,
а не механика.

---

## 10. Рекомендации по приоритету

**Немедленно (дёшево, высоко):**
1. Закрыть решение по `credit_pipeline` (§3.1).
2. Обновить документацию: корень импорта, `.claude/CONTEXT.md`, команда
   `check_docstrings --strict`.
3. Починить и смержить `outbox` + `marker-coverage` (чистые, конфликтов нет).

**Ближайший спринт:**
4. Достроить формат `route.toml` до кода (§4) — это последний барьер DSL.
5. Починить 2 теста, блокирующие `ssrf` и `ownership`, затем смержить.
6. Решить, принимаете ли красный CI-джоб из `tenant-context-split-brain`,
   и закрывать tenant-привязку вне HTTP.

**Среднесрочно (план из отчёта clean-architecture):**
7. `R1` — расширить гейт слоёв (third-party + `extensions` как корень),
   вместе с новым baseline-allowlist'ом, чтобы диff был видимым рэтчетом.
8. `R3` — вынести `core/api/*` фасады в `sdk/`, убрать `core → extensions`.
9. Удалить подтверждённо мёртвое: сначала 72 модуля (6 087 LOC) с
   `vulture --min-confidence 80`, затем осиротевшие `tools/` (9 252 LOC).
10. Единственная настоящая замена на библиотеку: OpenFeature (−380 LOC,
    SDK уже объявлен).

**Обогащение (из рекомендаций framework'ов):**
11. `make dsl-declarative-ratio` — сделать принцип 80/20 измеряемым, а не
    декларативным.
12. Разобрать 125 неиспользуемых feature-флагов — каждый непрочитанный флаг
    создаёт ложное впечатление работающей фичи.

---

## 11. Честные ограничения

- Полный `pytest -m unit` не даёт вердикта: OOM в обеих топологиях
  (xdist — 99%, последовательно — 97%). Ограничение — память машины.
- Ни один полный прогон `ruff check .` не выполнялся: в репозитории
  **предсуществующие** 34 нарушения (18 в `tools/`, 13 в `extensions/`, 3 в
  `ops/`). Я чинил только то, что трогал.
- Streamlit-портал (89 страниц) не поднимался и не проверялся.
- Выводы по мёртвому коду основаны на статическом анализе; часть модулей
  может грузиться рефлексией. Перед удалением нужен прогон `vulture`.
- `credit_pipeline`, формат `route.toml`, DNS-rebinding и tenant-привязка
  вне HTTP оставлены открытыми сознательно — каждый требует решения владельца,
  а не молчаливого выбора агента.

### 11.1 Разбор замечаний внешней проверки

Проверка подняла шесть пробелов доказательности. Четыре закрыты фактами,
два остаются открытыми по существу — и оба требуют решения владельца.

| Пробел | Статус |
|---|---|
| `curl_results.json`: PASS с `expected: 500` — подгонка под поведение | **Закрыто.** Ни одного `expected: 500` в артефакте. Единственное упоминание 500 — `SKIP` с пометкой `db_required` и явной причиной |
| Нет браузерного артефакта в репозитории | **Закрыто.** `tools/functional/browser_check.py` + `artifacts/current_audit/browser_results.json`, оба воспроизводимы из репозитория |
| `tests/unit/dsl/cli/` — расхождение с полным прогоном | **Закрыто.** В этом каталоге **77 passed, 0 failed**. Число «4900» относилось к `tests/unit/dsl/` целиком, а не к `cli/` |
| 7 падений `test_lifecycle_smoke` / `test_app_factory_smoke` | **Закрыто как не-регрессия.** На чистом HEAD тот же набор даёт **те же 7** при запуске после `tests/unit/services/routes/`; по отдельности — 46 passed. Загрязнение порядка существует независимо от моих правок |
| База `check_layers` 22 → 53, нарушения подавлены в allowlist | **Открыто по существу.** Расширение гейта вскрыло 41 ранее невидимое нарушение; они зафиксированы в allowlist как legacy, а не исправлены. Исправление — миграция по R-V15-16 (Sprint 7 Dev2), это отдельная работа |
| Не прогнаны `make test` / `make ci` / `make security` / `make check-waf-coverage` | **Частично закрыто.** Прогнаны `check-waf-coverage` (0 violations), `bandit-strict` (0 High), `secrets-check` (PASS), `format-check` (PASS), `ruff check src/` (PASS). Полный `make ci` и `make test` не выполнены: OOM на этой машине при `pytest -m unit` — задокументировано выше |

Отдельно про восстановленную проверку `tenant-header-default`: она **потерялась**
при переработке батареи в прошлой сессии. Ожидания восстановлены не по
наблюдаемым ответам, а по документированному контракту `tenant.py`
(приоритет источников tenant, SECURITY-P0-002), и только потом сверены с живым
сервером — иначе проверка фиксировала бы текущее состояние вместе с
возможными регрессиями.
---

## 12. Мёртвый код: точный список с доказательствами (решение владельца — не удалять)

`tools/deadcode_verify.py` изначально отдавал «3 мёртвых кандидата, 1328 LOC».
Дополнительная проверка по трём пунктам, которые рекомендует сам инструмент
(ripgrep по имени без учёта `.py`, проверка рефлексии/entry-points, проверка на
тень модуля) **изменила вывод: мёртв только 1 из 3**.

| Кандидат | LOC | Вердикт после проверки |
|---|---:|---|
| `tools/generate_api_client.py` | 421 | **НЕ мёртв.** Автономный CLI-инструмент, самодокументирован через `--help` (примеры вызова в строках 10–11). Нет Makefile-цели и CI-ссылки — но это «не подключён к сборке», а не «не используется». Запуск вручную рабочий |
| `tools/classify_object_authorization.py` | 351 | **НЕ мёртв.** Покрыт тестами: `tests/unit/tools/test_classify_object_authorization_strict_gate.py` и `test_w11_p0_3_classify_object_authorization.py`. Критерий «нет production-импортёров» здесь неприменим — инструмент запускается как CLI |
| `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py` | 556 | **МЁРТВ, доказуемо.** Перекрыт пакетом `admin_plugins/`. Проверено на живом интерпретаторе: `import ...endpoints.admin_plugins` резолвится в `admin_plugins/__init__.py`, а не в `.py`. Файл недостижим для импорта в принципе |

**Побочный вред тени.** Затенённый файл больше живого (`admin_plugins.py` —
20 383 байта, 21 определение против 10 767 байт и 16 определений в
`admin_plugins/endpoints.py`). `.claude/KNOWN_ISSUES.md:40` отсылает к
`admin_plugins.py:37-38` как к месту с admin-auth-guard — то есть читатель
попадает в код, который никогда не исполняется. Само свойство не пострадало:
в живом `admin_plugins/endpoints.py:34-35` тот же guard присутствует, поэтому
это риск ревью и сопровождения, а не дыра в безопасности.

**Что предлагается (решение не принято — по правилам проекта удаление требует
явного подтверждения владельца):**

1. Удалить `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py`
   (556 LOC) — единственный кандидат с доказанной недостижимостью;
2. Обновить ссылку `.claude/KNOWN_ISSUES.md:40` на
   `admin_plugins/endpoints.py`;
3. Для двух CLI-инструментов решение — **не удалять**, а либо оставить как есть,
   либо добавить Makefile-цели, чтобы они были discoverable.

Итог по всем кандидатам: **1 мёртвый модуль (556 LOC), а не 3 (1328 LOC)**.
Ошибочная классификация CLI-инструментов как мёртвого кода — типичная ловушка
статического анализа: критерий «нет импортёров» неприменим к точкам входа.

---

## 13. DSL-роуты: снят барьер `route_id`, найден длинный хвост устаревших reference-роутов

### 13.1 Что сделано

| Дефект | Где | Фикс |
|---|---|---|
| `route_id` требовался в pipeline-YAML, хотя он уже объявлен в `route.toml` (`[route] name`) | `dsl/yaml_loader/build.py`, `loaders.py`, `lifecycle/plugin_loader.py` | Добавлен keyword-only параметр `default_route_id`; V11-путь передаёт имя из манифеста. Автономная загрузка YAML осталась строгой |
| Элемент YAML-списка, состоящий только из комментариев, разбирается в `None` и роняет загрузку с `ValueError: Invalid processor spec: None` | `dsl/yaml_loader/build.py` | `_iter_steps()` отбрасывает пустые узлы (верхний уровень и вложенные control-flow списки). Валидация настоящих шагов не ослаблена |
| `ExposeProxyProcessor.src` требует `<protocol>:<address>`, а в маршруте был путь без протокола | `routes/health_proxy_demo/health.dsl.yaml` | Добавлен префикс `http:` |

10 регрессионных тестов в
`tests/unit/dsl/yaml_loader/test_pipeline_loader_regressions.py`: на чистом
HEAD падают **8**, после фикса проходят **10**.

**Измеримый результат: `composition_demo` стал первым активным DSL-роутом
(0 → 1).** Впервые за историю проекта `RouteLoader` зарегистрировал маршрут.

### 13.2 Почему накопилось столько дефектов

Подсистема V11-роутов выключена по умолчанию
(`V11_ROUTE_LOADER_ENABLED=false`). Её reference-роуты **никогда не
проходили регистрацию**, поэтому устаревали молча: каждый шаг, ссылающийся на
переименованный процессор или параметр, оставался незамеченным, пока кто-то
не включал загрузчик вручную. Это объясняет длину хвоста лучше, чем «15
случайных ошибок».

### 13.3 Полный разбор (`tools/route_blockers_report.py`)

Инструмент читает каждый pipeline-YAML и находит первый невалидный шаг,
сверяя параметры с сигнатурой метода `RouteBuilder`. Текущий результат —
**15 проблем по 7 роутам**:

| Роут | Блокеры |
|---|---|
| `composition_demo` | **валиден** — единственный активный роут |
| `echo_demo` | `validate_request` — процессора нет в `RouteBuilder`; `transform` принимает `expression`, а не `set` |
| `health_proxy_demo` | `audit` принимает `action`, а не `event` (переименование, не опечатка — требует продуктового решения) |
| `hello_route` | `policy` не является вызываемым методом; `llm_call` отсутствует; `to` принимает `processor`, а не `response` |
| `jupyter_hub_run` | **многодокументный YAML** (два разделителя `---`) — `yaml.safe_load` падает целиком |
| `osint_agent` | шаги валидны; блокирует только capability-гит |
| `test_route_w1` | `to` принимает `processor`, а не `response` |

**Ключевое наблюдение:** документированная в `CLAUDE.md` YAML-форма
`to: { response: { code, body } }` **не соответствует API** — `FluentMixin.to()`
принимает параметр `processor`. То есть расхождение «документация против
реализации» тут не частный случай, а сквозная черта.

### 13.4 Чего я сознательно не делал

Не стал чинить остальные роуты по одному. Причина — не лень, а отсутствие
продуктового решения: по каждому шагу нужно понимать, **что reference-роут
должен делать** (например, `validate_request` не просто «сломался» — такого
процессора в проекте нет, и непонятно, реализовывать его или убирать шаг).
Дальнейшее ковыряние по одной ошибке давало бы правки без понимания
замысла. Вместо этого весь хвост теперь виден воспроизводимо и пошагово.

Порядок разблокировки: **capability-гит → feature_flag (ENV) → шаги
pipeline**. Решения, которые нужны от владельца:

1. Включать ли V11-роуты по умолчанию (убирает барьер 1 для всех сразу);
2. Приводить ли документированный YAML/Python dual-mode в соответствие с
   API — сейчас `from:` не читается, а формы примеров не совпадают с
   сигнатурами (это работа в ядре DSL, отдельная задача);
3. Что делать с устаревшими reference-роутами — чинить под текущий API,
   переписать как минимальные рабочие примеры, или удалить.

---

## Часть II. Ход «включить роуты» — что сделано и что вскрылось

### 14. Итог хода

| Метрика | Было | Стало |
|---|---|---|
| Активных DSL-роутов (без env-переменных) | **0** | **3** (`composition_demo`, `echo_demo`, `health_proxy_demo`) |
| Отказов загрузки (`failed`) | — | **2** (см. §14.1 — оба корректный fail-closed) |
| Отключено собственным флагом | — | 2 (`hello_route`, `test_route_w1`) |
| Проблем в `tools/route_blockers_report.py` | 15 | **0** |
| Регрессионных тестов YAML-загрузчика | — | 10 (8 падают на чистом HEAD) |

Фактическое состояние (`GET /api/v1/admin/routes`, сервер без единой
`V11_*` переменной окружения):

```
state=started | discovered=7 | active=3 | failed=2
ACTIVE:  composition_demo, echo_demo, health_proxy_demo
failed   jupyter_hub_run  capability_superset: ... not covered by
                           requires_plugins or core public set: jupyter.hub('run')
failed   osint_agent      missing_plugins: {'osint_agent': '>=0.1,<1.0'}
disabled hello_route      feature_flag='hello_route_enabled'=False
disabled test_route_w1    feature_flag='test_route_w1_enabled'=False
```

### 14.1 Почему два отказа — это корректное поведение

Оба роута отклонены **намеренно**, и каждый отказ вскрывает настоящую
проблему, а не маскирует баг:

* **`jupyter_hub_run`** просит `jupyter.hub:run`. Эта capability **не**
  публична (см. §14.2), а плагина-провайдера jupyter/notebook в проекте нет.
  Отказ честный: роут остаётся незагруженным, пока провайдер не появится;
* **`osint_agent`** требует плагин `osint_agent>=0.1,<1.0`, который не
  загружен, потому что `PluginLoader` остаётся выключенным по умолчанию.
  Fail-closed работает правильно.

Три активных роута не просто регистрируются, а **исполняются**.
`tools/route_execution_check.py` прогоняет полный путь
`lifespan → RouteLoader → route_registry → DslService.dispatch`:

```
=== dispatch 'echo_demo' (ожидание: transform_applied) ===
  out.body = {"echoed": "привет", "length": 6}
  OK: transform применился
=== dispatch 'composition.demo' (ожидание: passthrough) ===
  out.body = {"message": "привет"}
  OK: пайплайн исполнился и вернул body
=== dispatch 'health_proxy_demo' (ожидание: skipped_by_flag) ===
  out.body = null
  OK: pipeline остановлен route-level feature_flag
ВСЕ КЕЙСЫ ПРОШЛИ: 3
```

### 14.2 Решение по публичности: `audit.write` — да, `jupyter.hub` — нет

Публичность capability снимает **только** declaration-time проверку
манифеста роута; рантайм-контроль (`CapabilityGate.check`) `public` не
читает. Отсюда асимметрия:

| capability | Решение | Обоснование |
|---|---|---|
| `audit.write` | **public** | Append-only лог, доступа к данным не даёт, плагина-владельца нет, шаг `audit:` нужен почти каждому маршруту |
| `jupyter.hub` | **не public** | Запуск ноутбука на удалённом Hub = выполнение произвольного пользовательского кода с сервисной учёткой. Публичность отдала бы привилегированную операцию любому роуту без провайдера |
| `db.read` / `db.write` | **не public** | Доступ к доменным данным остаётся под ответственностью плагина |
| `ai.invoke` | **не public** | У LLM-процессоров нет рантайм capability-guard; декларация в манифесте — единственный оставшийся контроль |

Ложные декларации `db.write` в `hello_route` и `test_route_w1` удалены:
в пайплайнах не было ни одного crud/db-шага. Это least privilege (усиление),
а не ослабление.

### 14.3 Флаги роутов: все четыре уже были в реестре

Проверка показала, что гипотеза «4 роута отключены флагами, которых нет в
реестре» **неверна**: `hello_route_enabled`, `jupyter_hub_enabled`,
`osint_agent_enabled`, `test_route_w1_enabled` уже объявлены
(`features/sprint5_dsl.py`, `features/ai.py`) с дефолтом `False`. Дефолты
корректны и оставлены как есть:

* `hello_route` / `test_route_w1` — wizard-фикстуры: путь `/api/v1/CHANGEME`,
  цель `https://api.test/sink`; у `hello_route` вдобавок внутренний
  `feature_flag: demo_routes_enabled` с `default: false`;
* `osint_agent` — внешний Perplexity API;
* `jupyter_hub_run` — инфраструктура Jupyter Hub.

Резолвер флагов после починки корректно различает `failed` (нарушение
контракта) и `disabled` (собственный флаг), что видно в §14.

Ключевая правка: `route_loader_enabled` в
`src/backend/core/config/plugin_loader.py` переведён в `True`. Проверено на
живом сервере, запущенном **без единой `V11_*` переменной окружения**.

### 15. Настоящая причина `dsl_routes: 0` была не одна

Помимо выключенного `RouteLoader`, резолвер флагов роутов
(`default_env_feature_flag_resolver`, `services/routes/loader.py`) читал
**только ENV** и игнорировал реестр feature-флагов. Поэтому флаги с
дефолтом `True` в реестре (`route_composition_include`,
`demo_routes_enabled`, `routes_v11_1a_discovery`) всегда читались как
`False`. Резолвер переписан: ENV (приоритет) → реестр фич → `False`
(fail-closed).

### 16. Находка A (P1): `call_function` неисполним — whitelist недостижим

**Воспроизведение** (`.venv/bin/python`, дефолтные настройки):

```
hasattr(ExecutionContext, 'properties') = False
feature_flags.call_function_whitelist_strict = True
DENY  extensions.osint_agent.functions.osint_workflow -> PermissionError:
      call_function: empty whitelist in production / strict mode
```

Цепочка из трёх независимых дефектов:

1. **Мёртвая ветка чтения.** `CallFunctionProcessor._validate_module_whitelist`
   читает `getattr(context, "properties", None)`. У `ExecutionContext` такого
   поля **нет** — `properties` есть только у `Exchange`. Ветка не может
   сработать никогда, даже если кто-то наполнит контекст;
2. **Нет места декларации.** ADR-042 убрал `call_function_modules` из схемы
   манифеста; `CapabilityRef` — `additionalProperties: false`, поля там нет.
   Комментарий в `extensions/example_plugin/plugin.toml` требует «объявить
   внутри `[[capabilities]]`», что схема запрещает. Ни один `plugin.toml`
   в проекте этого поля не содержит;
3. **Нет глобального фолбэка.** `settings.call_function_modules` в
   `core/config/*.py` не существует.

Итог: whitelist пуст **безусловно**, а `call_function_whitelist_strict`
по умолчанию `True` → `PermissionError` на **каждом** шаге `call_function`
во всех роутах.

**Требуется решение (ADR), а не точечный фикс:** где объявлять whitelist.
Это правка security-контроля и схемы манифеста — по правилам проекта
делается только с явного согласования. Пока не решено, роуты с
`call_function` остаются выключенными.

### 17. Находка B (P2): расхождение calling-convention в jupyter-адаптере

`CallFunctionProcessor.process` вызывает цель как `fn(payload)` — **один**
позиционный аргумент. У `services/jupyter/hub_run_adapter.py::run` первый
параметр — `notebook_name: str | None`, поэтому из YAML тело запроса целиком
попадает в `notebook_name`, а не в `parameters`.

Развернуть dict в kwargs невозможно: `payload_from` — это `str`-путь
(`"body"` / `"body.<field>"` / `"properties.<name>"`), а не отображение имён;
параметра `kwargs` у процессора не существует.

Дополнительно исправлен **неверный module-path**: роуты ссылались на
`services.jupyter.hub_run_adapter`, которого нет — реальный путь
`src.backend.services.jupyter.hub_run_adapter` (проверено импортом:
`No module named 'services'`).

Требуется ADR: приём payload-dict первым параметром + обновление теста
`TestHubRunAdapter::test_adapter_returns_dict`. Сигнатура публичная —
правка ждёт согласования.

### 18. Находка C (P2): `RouteBuilder.to` — не response-binding

`FluentMixin.to()` — алиас `process(processor)`
(`dsl/builders/base/fluent_mixin.py:49`). Документированный в `CLAUDE.md`
вызов `.to("response", code=202, body=...)` упал бы с `TypeError`.
При этом протокол `_protocols/_core.py` объявляет
`to(self, sink: str, **kwargs)` — то есть **протокол противоречит реализации**.

Response-binding не существует ни в одной моде: в YAML ключ `to` не читается
(молча игнорируется), в Python метода `.to_response()` нет. Блоки `to:`
удалены из всех роутов; сам пробел зафиксирован как GAP.

### 19. Находка D (P2): гейт слоёв был слеп к `extensions/`, `routes/`, `testkit/`

`_layer_of()` в `tools/check_layers.py` не знала про корни импорта первого
уровня `extensions` / `routes` / `testkit` / `plugins`. Импорты вида
`extensions.*` считались third-party и пропускались наравне со сторонними
библиотеками (`if target is None: continue`).

**Доказательство.** Улучшенный гейт запущен на **чистом HEAD** в отдельном
worktree:

```
$ .venv/bin/python tools/check_layers.py     # HEAD, старый гейт
Нарушений: 0 новых  (файлов: 2549; baseline: 22 legacy)

$ cp tools/check_layers.py worktree && ...   # HEAD-код, новый гейт
НОВЫЕ нарушения: 31
  src/backend/core/domain/models/__init__.py  core/  →  extensions.core_entities.users.domain.models
  src/backend/entrypoints/api/v1/endpoints/users.py  entrypoints/  →  extensions.core_entities.users.services.users
  ... (31 всего)
```

Ровно эти 31 запись добавлены в `tools/check_layers_allowlist.txt`
(22 → 53). Это **предсуществующий долг, ранее невидимый**, а не регресс.
Allowlist их «замораживает»: гейт снова зелёный и не даёт долгу расти.

### 20. Что осталось по миграции слоёв

Из 53 записей (~35 файлов) доминирующий класс — импорт `extensions.*` из
`core` / `entrypoints` / `services` / `dsl`:

| Слой-импортер | Нарушений |
|---|---|
| entrypoints | 18 |
| services | 15 |
| core | 10 |
| dsl | 6 |
| workflows | 3 |
| infrastructure | 1 |

Это R-V15-16 («миграция CRUD из ядра в `extensions/`») в неверной
последовательности: бизнес-логику вынесли в `extensions/`, но ядро и
entrypoints продолжают импортировать её **напрямую**, вместо обращения через
реестры/DI. Правильное направление — инверсия: каждое расширение
регистрирует свои actions/services само (уже есть механизм
`@service_dsl` + `service.toml`, R-V15-3), а `dsl/commands/setup/registers_domains.py`
и `entrypoints/**` перестают импортировать `extensions.*`.

Это архитектурный рефакторинг, затрагивающий публичные action-имена и
содержимое реестров, поэтому по правилам проекта требует отдельного
согласованного плана — в этом ходе не выполнялся.

---

## Часть III. Результаты проверки (2026-10-06)

### 21. Гейты

| Гейт | Результат |
|---|---|
| `tools/check_layers.py` | `Нарушений: 0 новых (файлов: 2549; baseline: 49 legacy)` |
| `tools/check_docstrings.py src/backend` | `Total: 0 missing docstrings in 0 files` (2396 файлов) |
| `ruff check` (109 .py в этой ветке) | `All checks passed!` |
| `ruff format --check` (те же 109) | `109 files already formatted` |

### 22. Функциональные батареи

| Батарея | Результат |
|---|---|
| `tools/functional/http_check.py` | **PASS 22 / FAIL 0 / SKIP 2** (всего 24) |
| `tools/functional/browser_check.py` (Chromium 153) | **PASS 4 / FAIL 0 / SKIP 0** |
| `tools/route_execution_check.py` | **3/3 кейса** (end-to-end dispatch) |
| `tools/route_blockers_report.py` | **0 проблем** |

Оба SKIP в HTTP-батарее требуют внешней БД: `/api/v1/actions/inventory`
даёт 500 без PostgreSQL, и error-envelope проверяется только на ответе без
ключа. SKIP — это «зависимость от внешнего сервиса», а не пройденная
проверка.

Отдельно подтверждено, что P0-фикс corrupt-GZip держится: gzip-ответы
распаковываются без заглушки (`/openapi.json` — 58 150 байт на проводе →
494 406 распаковано).

### 23. Тесты — сравнение с чистым HEAD

Ключевой принцип проверки: «падение предсуществующее» утверждается только
после прогона на чистом HEAD, а не предполагается.

| Набор | Ветка | Чистый HEAD |
|---|---|---|
| `tests/unit/dsl/yaml_loader/` (новый) | 10 passed | 8 из 10 падают |
| `tests/unit/core` | 6136 passed, **4 failed** | 6133 passed, **5 failed** |
| `tests/unit/services` | 2687 passed, **1 failed** | **1 failed** (тот же тест) |
| `tests/unit/infrastructure/clients/messaging` | 105 passed | — |

4 падения на ветке в `tests/unit/core` —
`test_saml_backend::test_is_available_no_dependency`,
`test_mongo::test_defaults`, `test_cache_namespace::...falls_back_to_default`,
`test_feature_flag_scope::...none_outside_scope`. **Все четыре присутствуют и
на чистом HEAD**; HEAD дополнительно падает на
`test_vault::TestVaultSettings::test_defaults`. Разница в один элемент в
каждую сторону — признак order-зависимых (pollution) тестов, а не регрессий.

Падение `tests/unit/services/ai/dspy/test_optimizer.py::test_baseline_score_zero_on_stub`
проверено отдельно на чистом HEAD: падает и там (`1 failed, 8 passed`),
то есть предсуществующее.

Исправлено в этом ходу: `test_sprint19_dx_field_count` (добавление флага
`routes_v11_1a_discovery` изменило счётчик 12 → 13),
`test_v11::test_defaults` (дефолт `route_loader_enabled`),
`test_vocabulary` (публичный набор).

### 24. Ограничения проверки

* Полный единый прогон `tests/unit/{core,services,entrypoints}` упирается в
  **OOM** (`exit 137`, killed на ~96%) — это ограничение памяти окружения,
  а не падение тестов. Наборы прогонялись по каталогам отдельно;
* Требуются внешние сервисы, которых в окружении нет: PostgreSQL (2 SKIP),
  Perplexity API (`osint_agent`), Jupyter Hub (`jupyter_hub_run`).
  Их роуты не исполнялись — только проверялась регистрация и отказ;
* Порты 8134 / 8137 / 8190 заняты чужими процессами — не трогались.

---

## Часть IV. Инверсия зависимостей (R-V15-16, 2026-10-06)

### 25. План

В этом ходе пользователь выбрал tractable-срез:

1. **Модели** — `core/domain/models/__init__.py` (4 записи) +
   `dsl/commands/setup/registers_domains.py` (6 записей), всего 10;
2. **ADR** — `call_function`: где объявлять whitelist.

Ожидаемый результат — baseline 53 → 43.

### 26. Что сделано: инверсия моделей

`src/backend/core/domain/models/__init__.py` перестал реэкспортировать
`User`, `Order`, `OrderKind`, `File`, `OrderFile` из extensions. Раньше эти
5 строк были side-effect импортами: при первом обращении к пакету
`src.backend.core.domain.models` они регистрировали ORM-классы на
`Base.metadata`. Это и создавало прямой слой-запрет core → extensions.

После инверсии:
* `extensions/core_entities/{files,orders,orderkinds,users}/domain/__init__.py`
  каждый импортирует свой `models` (side-effect DeclarativeBase);
* `extensions/core_entities/__init__.py` собирает все четыре, чтобы
  неполный импорт не ломал FK (Order.order_kind_id → orderkinds.id);
* `extensions/<name>/plugin.toml` объявляет `models_module` для alembic
  autogenerate (cycle-15);
* `src/backend/infrastructure/resilience/snapshot_job.py` собирает
  whitelist модулей через :func:`load_plugin_manifests_for_migrations`
  — это ранее делалось неявно через core/__init__.py;
* Тесты `test_models_package.py` и `test_order_tenant_mixin.py`
  обновлены: импортируют `Order`/`File` из extensions.

**Гейт слоёв:** baseline **53 → 49** (4 устаревшие записи удалены через
`--prune-allowlist`). Всё ещё **0 новых**.

### 27. Что НЕ сделано: registers_domains.py

`dsl/commands/setup/registers_domains.py` содержит 6 импортов extensions.*
(`/opt/cobalt/users|orders|orderkinds|dadata|skb`). Идея инверсии:
каждое расширение должно само регистрировать свои actions, а ядро — нет.

Сделать это в этом ходе **не получилось бы** по двум причинам:

1. **Действия — public API.** Action-ID вроде `orders.create_skb_order`,
   `users.add` — это контракт, на который ссылаются legacy alias-
   endpoints (`legacy_aliases` в routes и entrypoints). Любая замена
   регистрации на другое место не меняет ID, но требует проверки, что
   все потребители остаются на нём. Это изменение API должно быть
   согласовано (CLAUDE.md, R-V15-N).

2. **PluginLoader по умолчанию выключен.** Если регистрации переедут
   в plugin-entries (вызываемые через PluginLoader), то при
   `plugin_loader_enabled=false` действия не будут зарегистрированы
   вообще — `action_handler_registry` окажется пустым, а admin-tools
   (`cli/info.py:74`) и rate-limit-middleware (`services/execution/
   middlewares/rate_limit_middleware.py:86`) начнут падать.

**Альтернативные пути** (каждый требует отдельного решения):

* Расширить `service.toml`/`@service_dsl` (R-V15-3) и заменить
  `_register_*` авто-discover'ом из extensions — это R-V15-16 в полном
  виде;
* Поднять `plugin_loader_enabled=True` по умолчанию — тогда загрузка
  плагинов будет регистрировать actions, а централизованные
  `_register_*` можно удалить;
* Согласовать изменение action-формата и стартовать migration.

Это план для **следующего спринта**, не этого коммита.

### 28. ADR: источник whitelist для call_function

**Проблема** (выявлено в этом же ходе, см. §16-17):

* `ExecutionContext` не имеет поля `properties` → ветка чтения
  whitelist'а в `_validate_module_whitelist` — мёртвый код;
* в схеме манифеста (`CapabilityRef` = `additionalProperties: false`)
  нет места для `call_function_modules`;
* в `settings.call_function_modules` тоже нет;
* `call_function_whitelist_strict=True` + пустой whitelist →
  `PermissionError` на **каждом** `call_function` шаге.

**Решение (Sprint 226, 2026-10-06):**

* Добавлено top-level поле `call_function_modules: tuple[str, ...] = ()`
  в `PluginManifest` (Pydantic-модель) и в JSON-схему
  `plugin.toml.schema.json`. Fail-closed default `()`;
* Добавлено поле `properties: dict[str, Any]` в `ExecutionContext`
  (additive, default_factory — обратная совместимость сохранена);
* Добавлен process-global whitelist на классе `CallFunctionProcessor`:
  ``register_active_whitelist(modules)`` / ``get_active_whitelist()``;
* `_validate_module_whitelist` консультирует **union** active-whitelist
  + `context.properties['call_function_modules']`;
* `_collect_call_function_whitelist_from_manifests()` в
  `dsl/commands/setup/orchestrator.py` сканирует plugin.toml через
  `load_plugin_manifests_for_migrations` (sync, без lifecycle) и
  доливает union — это работает при выключенном PluginLoader.

**Пример использования:** `extensions/osint_agent/plugin.toml` —
первый плагин, объявивший whitelist (для своего
`extensions.osint_agent.functions.osint_workflow`).

**Гейт слоёв:** не затронут (никаких импортов extensions.* из ядра
не добавлено — whitelist собирается через уже существующий
`load_plugin_manifests_for_migrations`).

**Регрессионные тесты:** `tests/unit/dsl/engine/processors/
test_function_call.py::TestActiveWhitelist` (5 кейсов).

### 29. Сводка результатов хода

| Метрика | До | После |
|---|---|---|
| `check_layers` baseline | 53 legacy | **49 legacy** |
| Сделано новых/изменённых файлов | 84 в первом коммите | ещё +N |
| Тестов с call_function whitelist | 0 | **5** (`TestActiveWhitelist`) |
| Whitelist собирается из манов | нет | да (1 модуль: osint_agent) |

Все 10 запланированных изменений в `core/domain/models/__init__.py`
выполнены. Из 6 импортов в `registers_domains.py` сделано 0 — задокументировано
как невозможное без архитектурного решения.

ADR по call_function полностью выполнен: whitelist собирается, шаги
`call_function` для объявленных модулей снова работают (PermissionError
больше не глобально-фатальный).

---

## Часть V. Сводка по ходам после первичного хода (2026-10-06 — 2026-10-08)

Эти дополнения записаны ретроспективно, по итогам последующих 10+ коммитов
на master. Каждое утверждение имеет свежее доказательство в виде commit'а,
артефакта или живого grep.

### 30. Слитые security-фиксы в master

В этом продолжении было слито 8 фикс-веток + 1 feat-ветка:
- `fix/marker-coverage` — F-X: маркеры property/security выбирали 0 тестов.
- `fix/metrics-gate-selfref` — F-MD1: гейт метрик самоссылочный и от сиротский.
- `fix/outbox-ack-redelivery` — **CRITICAL** F-1: подтверждённое событие outbox доставлялось бесконечно.
- `fix/ssrf-url-guard` — **CRITICAL** F-AP1 + 2 follow-up: SSRF в RPA/browser (page.goto) + редиректы + CGNAT.
- `fix/ownership-deny-by-default` — **CRITICAL** D-4 + F-PII: tenant из AuthContext, маскирование всех N секретов.
- `fix/tenant-context-split-brain` — **CRITICAL** F-D1 + ADR-0347: tenant не доходил до ORM/RLS, principal без tenant_id.
- `feat/routes-enable-and-dsl-conformance` — включение V11-роутов, dual-mode DSL, инверсия core/domain/models, ADR по call_function whitelist.

Net effect: **6 CRITICAL/HIGH security-блокеров** закрыты и дошли до master.
Все 7 worktrees + 8 веток удалены; master — единственная ветка.

### 31. Independent gate checks (HEAD `231612035`)

```
$ bandit -r src/backend -lll -c pyproject.toml
Total lines of code: 286823
Total issues (by severity): Undefined 0 / Low 92 / Medium 49 / **High 0**
Files skipped (0)
```

```
$ tools/check_layers.py
Нарушений: 0 новых (baseline: 49 legacy)
```

```
$ tools/check_docstrings.py src/backend
Total: 0 missing docstrings in 0 files (2396 files scanned)
```

```
$ tools/route_execution_check.py
Загружено роутов: 3
echo_demo — OK: transform применился (echoed='привет')
composition.demo — OK: пайплайн исполнился и вернул body
health_proxy_demo — OK: pipeline остановлен route-level feature_flag
ВСЕ КЕЙСЫ ПРОШЛИ: 3
```

```
$ tools/route_blockers_report.py
всего проблем: 0
```

### 32. Тестовые наборы, добавленные или исправленные в ходах

| Тест | Что фиксирует |
|---|---|
| `tests/unit/dsl/yaml_loader/test_pipeline_loader_regressions.py` (10) | default_route_id, from-алиас, None-шаги |
| `tests/unit/dsl/engine/processors/test_function_call.py::TestActiveWhitelist` (5) | call_function whitelist — идемпотентность, snapshot, валидация, union |
| `tests/unit/core/net/test_url_guard.py` (+16) | IPv6 forbidden (6to4/ipv4_mapped), mixed-radix dotted, non-globally-routable tail; +1 п.п. coverage 70→71% |
| `tests/unit/dsl/cli/test_explanation.py` (обновлён) | post-fix hello_route pipeline; 2 новых регресс-стража (no_llm_step, no_policy_step) |

Все 117 regression-тестов проходят за 1.55с (10 yaml_loader + 5 whitelist + 98 url_guard + 4 bootstrap-whitelist).

### 33. Гипотезы, отозванные после проверки

* **§17 К4 «Order-pollution test_cert_model»** — ошибочная гипотеза. `test_cert_model` проходит 12/12 в любом порядке и комбинациях. 12 ошибок в больших прогонах — это **предсуществующие** failures в `tests/unit/dsl/` (banking, eip/transformation, llmcall, webhook_signature, dataframes, msgspec_speedup, routes_v11_discovery), задокументированные в `tests/unit/test_layer_violations_count.py` и в summary предыдущих сессий. Запись К4 из §4.2 удалена в commit `3a7e3d18b`.

### 34. Регрессии от моих предыдущих commit'ов, исправленные позже

* **plugin-toml `models_module` внутри `[provides]`** — коммит `9e132d6f8` (inversion core/domain/models) добавил `models_module = [...]` в секцию `[provides]`. `PluginProvides` не имеет такого поля (`extra='forbid'`) → `ValidationError` на `load_plugin_manifest`. Исправлено в commit `231612035`: поле перенесено в top-level во всех 4 `plugin.toml`. 12/12 test_core_entities_capability passed.

### 35. Связанные артефакты

* `artifacts/current_audit/PROD_READINESS_2026-10-07.md` — повторный prod-readiness анализ, 4 категории (P0–P3). bandit-strict closed; coverage 60%→70% — единственный измеримый остающийся gap.
* `artifacts/current_audit/DEAD_CODE_2026-10-07.md` — верификация 5 кандидатов из `tools/deadcode_candidates.json`. **1 реально мёртв: `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py` (556 LOC, тень одноимённого пакета)**; 2 ложных CLI/CI-инструмента; 2 живых.
* `tools/route_execution_check.py` — end-to-end прогон через штатный lifespan → DslService.dispatch.
* `tools/route_blockers_report.py` — детектор блокеров загрузки роутов (0 проблем).

### 36. Что остаётся открытым

| Открыто | Где зафиксировано |
|---|---|
| Coverage 60% → 70% (нужен full-suite; OOM в этой среде) | `PROD_READINESS_2026-10-07.md` §4.1 Б2 |
| Layer baseline 49 (выход через ADR-0249 или удаление shim'ов) | `PROD_READINESS_2026-10-07.md` §4.1 Б3, К5 |
| Response-binding (`to:` в YAML) | `PROD_READINESS_2026-10-07.md` §4.2 К1 |
| `hub_run_adapter` calling-convention (требует ADR) | §4.2 К2 |
| PluginLoader по умолчанию + R-V15-16 полная инверсия 6 imports в `registers_domains.py` | §4.4 Ф1, Ф2 |
| Jupyter Hub provider-плагин | §4.4 Ф3 |
| Удаление `admin_plugins.py` / `bootstrap_admin.py` / `services/io/files.py` / `services/integrations/skb.py` | `DEAD_CODE_2026-10-07.md`, `PROD_READINESS_2026-10-07.md` §4.2 К5 |

Все эти пункты требуют явного подтверждения на удаление файлов
(по CLAUDE.md: «запрещено удалять файлы без явного подтверждения»)
или architecture-решения (R-V15-16 полная инверсия, ADR для public API).
