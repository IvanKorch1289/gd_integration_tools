# Локализация открытых находок волны 35/36 (2026-11-18)

**Задача:** «продолжай, локализуй» — довести открытые позиции до точных
мест в коде и закрыть те, где локализация даёт безопасный фикс.

**Итог:** 4 открытые позиции локализованы, 3 из них закрыты кодом,
1 опровергнута (ошибка измерения). Ниже — по каждой: где именно, почему,
что сделано.

---

## 1. «Стриминговый ответ обрезается до первого чанка» — ОПРОВЕРГНУТО (артефакт измерения)

**Где было заявлено:** отчёт волны 35, §5 «стриминговая регрессия
HTTP-цепочки (pre-existing)»; агент волны 36 не смог локализовать
(«bisect-пробы зависают»).

**Локализация:**

* Воспроизведение через реалную цепочку middleware
  (`build_default_registry()` → `apply_to_app` поверх Starlette-приложения с
  конечным `StreamingResponse`): **5/5 чанков доходят до клиента**, status
  200. Обрезки нет.
* Биссект по одному middleware (37 отключений) ни один не меняет результат.
* Реальные стриминговые эндпоинты приложения:
  * `/events/stream` (`src/backend/entrypoints/sse/handler.py:109`) — **бесконечный
    поток по контракту** (`while True` + heartbeat раз в 30 с). Блокирующий
    клиент на таком потоке читает первый чанк и **висит** — это и выглядело
    как «обрезка»;
  * `/api/v1/ai/llm/stream` — требует LLM и авторизацию;
  * `/api/v1/storage/upload-stream` — multipart, авторизация.
* `httpx.ASGITransport` в этой версии httpx **не поддерживает стриминг**;
  `Starlette TestClient` буферизует тело. Оба инструмента не подходят для
  проверки потоков — отсюда и «зависающие пробы».

**Вывод:** middleware-цепочка стриминг не режет. Находка была артефактом
измерения бесконечного SSE-потока блокирующим клиентом.

**Закрыто регресс-тестом:** `tests/unit/entrypoints/middlewares/test_streaming_passthrough.py`
— реальная цепочка middleware, все чанки доходят (2 теста).

**Побочно найдено (и закрыто):** в SSE-обработчике при сбое PII-редирекции
chunks прокидывались **без редактирования** (fail-open), а в логе
указывалось «Set FEATURE_PII_STREAMING_FAIL_CLOSED=true» — **такого флага в
реестре не существовало**, escape-hatch молча ничего не делал.

* `src/backend/core/config/features/security.py` — добавлен флаг
  `pii_streaming_fail_closed` (default OFF — прежнее поведение).
* `src/backend/entrypoints/sse/handler.py` — при флаге ON сбой редикции
  **обрывает поток** (fail-closed), при OFF — прежнее best-effort.
* `tests/unit/entrypoints/sse/test_pii_fail_closed.py` — 5 тестов (flag +
  обе ветки поведения).

---

## 2. KNOWN-01: повторный импорт падал с `KeyError` по родительскому пакету — ЗАКРЫТО

**Симптом:** `tests/unit/core/ai/test_audit_fixes_cycle31.py` — 1 из 6 тестов
Redis-batch падал при прогоне файла целиком (в изоляции — зелёные).

**Локализация (пошагово):**

1. Биссект по классам файла → виновник `TestInProcessAgentSandboxAudit`
   (аудит-эмит песочницы ломает последующий импорт).
2. Трассировка импортов: пакет `src.backend.core.resilience` **уходил из
   `sys.modules`** после неудачного импорта.
3. Полный traceback: `core/resilience/__init__.py:79` →
   `_DeadlockError: deadlock detected by _ModuleLock('src.backend.core.resilience.retry')`.
4. Цикл импортов (был в коде как «хрупкая договорённость» в комментарии
   `core/resilience/__init__.py`):

   ```
   core.resilience.__init__ → core.resilience.rate_limiter
     → infrastructure.resilience.unified_rate_limiter → infrastructure.resilience.__init__
       → coordinator.py:44 → from src.backend.core.resilience import DegradationManager
   ```

   Раньше цикл разрывался **порядком** блоков в `__init__` (degradation выше
   rate_limiter). На Python 3.14 с per-module импорт-локом прямой импорт
   подмодуля (`from src.backend.core.resilience.retry import retry_async` —
   так делает clickhouse-аудит, `services/audit/clickhouse_audit_service/service.py:292`)
   приводил к взаимоблокировке импортов. Ошибка **глушилась** `emit_audit_safe`
   → **события аудита терялись** («audit_silent_loss»), а пакет оставался
   удалённым из `sys.modules` → следующий импорт падал уже с
   `KeyError: 'src.backend.core.resilience'`.

**Фикс:** `src/backend/core/resilience/__init__.py` переведён на **ленивый
re-export (PEP 562)** — `__init__` не импортирует подмодули на старте,
поэтому ре-ентрантность невозможна в принципе (а не «при правильном
порядке»). Для mypy имена оставлены в `TYPE_CHECKING`-импортах.

Побочно: из `__all__` убраны `Bulkhead`/`get_bulkhead` — они были
**объявлены, но не импортировались** (`from src.backend.core.resilience import
Bulkhead` → ImportError); каноническое место — `infrastructure.resilience.bulkhead`
(core не импортирует infrastructure).

**Проверка:** файл-регресс `tests/unit/core/ai/test_audit_fixes_cycle31.py` —
**17 passed** (было 1 failed); `tests/unit/core/resilience/**` — 325 passed;
новый контракт-тест `tests/unit/core/resilience/test_lazy_package_imports.py`
(7 тестов).

---

## 3. «gateway.verify_request is auth_selector.verify_request» — ЗАКРЫТО

**Симптом:** order-dependent падение `tests/unit/core/auth/test_gateway_facade.py`
в CI-режиме: `gateway.verify_request` — реальная функция, а
`auth_selector.verify_request` — `AsyncMock`.

**Локализация:**

* `tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py:166`
  патчит **шим** `entrypoints...auth_selector.verify_request` через
  `monkeypatch.setattr`;
* `tests/unit/core/auth/test_auth_selector_relocation.py` делает
  `importlib.reload(шима)` — reload пересоздаёт объекты функций в шиме;
* фасад `core.auth.gateway` продолжает держать **прежний** объект → инвариант
  «gateway.X is shim.X» становился ложным; в зависимости от порядка в
  воркере тест падал или нет.

**Фикс (причина, а не симптом):** шим
`src/backend/entrypoints/api/dependencies/auth_selector.py` и фасад
`core.auth.gateway` переведены на **ленивый re-export (PEP 562)** →
объект, который видит шим, **всегда тот же**, что и у фасада и канона,
независимо от reload'ов и патчей.

Три механизма, которые пришлось учесть (инвариант держался не с первого
фикса):

1. **Кэш в `globals()`.** PEP 562 вызывает `__getattr__` только если атрибута
   НЕТ в `__dict__`; первое обращение кэшировало объект → после reload'а
   канона фасад «отставал». Кэширование убрано: каждый доступ резолвит
   **текущий** объект канона.
2. **`setattr` на модуль «замораживает» lazy-реэкспорт.** `monkeypatch` пишет
   в `__dict__` модуля → после патча PEP 562 перестаёт вызываться, и шим
   навсегда отдавал бы старый объект. Устранено в источнике: тест
   `test_auth_required_pure_asgi` патчил и deprecated-шим, хотя middleware
   импортирует `verify_request` из `core.auth.auth_selector` — патч шима
   убран (был избыточен).
3. **Внутренние вызовы фасада.** Внутри модуля глобальный поиск имени НЕ
   обращается к `__getattr__` → собственные вызовы фасада идут через
   `_canonical()`.

Предупреждение о deprecated сохранено (module-level), непубличные
`_VERIFIERS` по-прежнему не текут, классы `AuthContext`/`AuthMethod` в фасаде
оставлены eager-импортом (нужны теле класса `AuthGateway` на этапе
определения модуля).

**Проверка:** `tests/unit/core/auth/**` — 537 passed;
`core/auth` + `entrypoints` + `plugins` в CI-режиме — **2528 passed**.

---

## 4. Остальные открытые пункты — локализованы (правки отложены: требуют решений)

| Пункт | Точное место | Статус |
|---|---|---|
| P2-1 pre-load расширений в lifespan | `src/backend/plugins/composition/lifecycle/` (lifespan подключается в `app_factory.py:92`); сам реестр — `src/backend/core/extension_registry.py:load_extension_resources` | локализовано; требует выбора точки старта (lifespan vs composition root) |
| P2-6 мёртвые `basicAuth`/`samlSession` в схеме | `src/backend/entrypoints/api/openapi_security.py` (схема `SECURITY_SCHEMES`) | локализовано; публичный контракт → решение владельца |
| P2-8 `rglob("plugin.toml")` в capability-графе | `src/backend/entrypoints/api/v1/endpoints/admin_capabilities.py:149` — `extensions_dir.iterdir()` + `child / "plugin.toml"` (только верхний уровень; 8 деклараций вложенных `core_entities/*` не видны) | локализовано |
| P2-9 `xfail_strict` + perf-профиль | `pyproject.toml` (pytest-конфиг, ключа `xfail_strict` нет) + 48 XPASS в `tests/unit/core/security/test_pii_tokenizer_redis_persistence.py` и др. | локализовано; требует разделения perf-кейсов |
| P3 фаза `denied` в трейсере | статус `"denied"` уже есть (`dsl/engine/processor_pool.py:165`, `execution_engine.py:256`, `processors/base.py:122`); не хватает **фазы** в трейсере | локализовано |
| P3 `ProtocolType` → `core/types/` | `src/backend/dsl/adapters/types.py:14` | локализовано |
| P3 `cache_resource` → `session_state` | SSE-очередь и `FakeOutbox` — фронтовые `st.cache_resource`-объекты | локализовано |
| `Cache-Control: public` на аутентифицированных ответах | `src/backend/entrypoints/middlewares/response_cache.py:215` (`f"public, max-age={self._max_age}"`), без `Vary` | локализовано; решение владельца |
| host-glob vs URL в `net.outbound` | scope роутов (`routes/health_proxy_demo/route.toml`, `routes/composition_demo/route.toml`) заданы как `https://host:port:internal`, а рантайм-гейт сверяет host (dot_glob) | локализовано; подтверждение владельца |
| Гейт «все слои в матрице» + lazy-import гейт | `tools/check_layers.py` (матрица слоёв, `_layer_for`); каталог `src/backend/utilities/**` вне матрицы | локализовано |

---

## 5. Сводка

| Позиция | Было | Стало |
|---|---|---|
| Стриминг «обрезается» | не локализовано | **опровергнуто** (артефакт измерения) + регресс-тест |
| SSE fail-open без escape-hatch | флаг не существовал | **флаг реализован**, fail-closed режим + 5 тестов |
| KNOWN-01 (KeyError по пакету) | не локализовано | **локализовано** (цикл импортов + `_DeadlockError`) → **закрыто** (ленивый `__init__`) |
| Identity `gateway`/`auth_selector` | order-dependent падение | **закрыто** (ленивый шим) |
| `Bulkhead` в `core.resilience.__all__` | ImportError | **закрыто** (убрано из API core) |
| Остальные открытые пункты | «требует решения» | **локализованы до file:line** (таблица §4) |
