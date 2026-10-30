# ADR-0401 — RPA-runtime wiring, инвалидация всех уровней кэша, квоты и PII fast-path (волна 20, кластер W4)

* Статус: Accepted (2026-10-30, волна 20, кластер W4 — RPA, кэш, файлы)
* Cycle: 179 (волна 20)
* Связан с:
  - ADR-0369 (достижимость RPA-шагов; дефект G12.6 — wiring `browser_pool`/`desktop_rpa_client`),
  - ADR-0370 (capability-каталог RPA; долг «потребитель `audit_event`»),
  - ADR-0390 (production-guard хранилища и лимиты файлов; долг «`s3.py` без `size()`», «DI-провайдер без quota-manager»),
  - ADR-0391 (Redis-тир кэша и tenant-ключи; долг «memory/disk не в `CacheInvalidator`»),
  - ADR-0392 (ReDoS в PII-регексе; fast-path `sub_email`),
  - ADR-0393 (capability-гейт для БД/RPA-шагов)
* Затрагивает:
  - `src/backend/core/di/providers/rpa.py` (новый),
  - `src/backend/core/di/providers/storage.py`, `src/backend/core/di/providers/__init__.py`,
  - `src/backend/dsl/engine/processors/base.py`, `.../rpa_browser.py`, `.../desktop_rpa.py`,
  - `src/backend/plugins/composition/di.py`, `.../lifecycle/shutdown.py`, `.../service_setup.py`,
  - `src/backend/infrastructure/cache/factory.py`, `.../cache/backends/{memory,disk}.py`,
  - `src/backend/infrastructure/storage/{s3,tenant_wrapper}.py`,
  - `src/backend/core/security/pii_masker.py`,
  - `src/backend/infrastructure/observability/pii_filter.py`

---

## Контекст

Волна 20 закрыла пять остаточных дефектов кластера «RPA, кэш, файлы»:

1. **[high] RPA-runtime не зарегистрирован.** `grep` по `plugins/` и `core/di/` —
   0 совпадений по `browser_pool` / `desktop_rpa_client`. DSL-шаги
   `browser_launch`/`navigate`/`click` (`dsl/engine/processors/rpa_browser.py`)
   и `desktop_rpa` (`dsl/engine/processors/desktop_rpa.py`) искали зависимость
   только в `ExecutionContext` — а он `dataclass(slots=True)` и не имеет ни
   `browser_pool`, ни `app_state`. Итог: RPA browser/desktop **всегда**
   заканчивались `RuntimeError` (ADR-0369, дефект G12.6).
2. **[medium] `audit_event` не эмитится.** Поле объявлено более чем 40 классами
   процессоров, но потребитель был один — `agent_dsl/_base.py` (AI-процессоры).
   События не создавал никто: ADR-0370 зафиксировал это как долг владельца.
3. **[medium] `CacheInvalidator` не покрывает fallback-уровни.** Primary-уровень
   регистрировался в `infrastructure/cache/factory.py`, а memory (L1) и disk (L3)
   создавались напрямую в `plugins/composition/service_setup.py` и в инвалидатор
   **не** попадали. Tag/pattern-инвалидация чистила только primary — после
   отказа Redis клиент получал stale-значения из L1/L3.
4. **[medium] Квоты файлов не уменьшались.** `core/di/providers/storage.py` не
   создавал quota-manager (grep пуст), поэтому фасад, отданный extensions'ам,
   получал `quota_manager=None` и `enforce_quota=False`. Вторая половина долга —
   `infrastructure/storage/s3.py` не имел `size()`, поэтому `StorageFacade`
   при удалении объекта уменьшал только счётчик файлов, но не байт
   (ADR-0390, «потолок решения»).
5. **[medium] Fast-path PII-применялся не везде.** `sub_email` (ADR-0392)
   использовал только `entrypoints/middlewares/data_masking.py`; остальные
   потребители (`core/security/pii_masker.py`,
   `infrastructure/observability/pii_filter.py`) вызывали `EMAIL.sub(...)`
   напрямую и сканировали каждую строку линейно.

---

## Решение

### 1. RPA-runtime: DI-провайдер + composition root + shutdown

* Новый `src/backend/core/di/providers/rpa.py` — canonical single entry point:
  `get_browser_pool_provider()` (lazy singleton `PlaywrightBrowserPool`),
  `get_desktop_rpa_client_provider()` (lazy singleton `DesktopRpaClient`),
  `set_*_provider()` (test-инъекция), `shutdown_rpa_runtime()`.
  Браузер поднимается при первом `acquire()` (`PlaywrightBrowserPool.startup`
  идемпотентен), поэтому отсутствие playwright/patchright не ломает старт.
* `plugins/composition/di.py::register_app_state` регистрирует
  `app.state.browser_pool` и `app.state.desktop_rpa_client`;
  `plugins/composition/lifecycle/shutdown.py` вызывает `shutdown_rpa_runtime()`
  (шаг 8c) — иначе playwright-subprocess жил до конца процесса.
* Процессоры резолвят зависимость в три шага: `context.browser_pool` →
  `context.app_state.browser_pool` → DI-провайдер.

### 2. `audit_event`: эмиссия в базовом классе

* `BaseProcessor` получил `audit_event: ClassVar[str | None]` и
  `__init_subclass__`, который оборачивает `process` наследника
  (`_install_audit_emitter`): после шага эмитится событие с outcome
  `success` / `failure` / `denied`.
* Событие содержит **только метаданные** — имя процессора, класс, capability,
  route и tenant; значения данных в payload не попадают.
* Шаги без `audit_event` не аудируются. Классы, которые эмитят событие сами
  (`BaseAIProcessor` — контракт `_audit_safe_emit`), не оборачиваются: дубля
  события нет. Правило реализовано duck-typing-проверкой, поэтому файл
  `agent_dsl/_base.py` (занятый параллельным кластером W3) не изменялся.

### 3. Инвалидация кэша по всем уровням

* `MemoryBackend` и `DiskCacheBackend` получили tag-индекс:
  `bind_key_to_tag` / `delete_by_tag` (и `delete_by_pattern` → int у memory).
* `infrastructure/cache/factory.py::_register_invalidator_backend` стал публичным
  `register_backend_in_invalidator`; новая `create_cache_fallback_backends()`
  создаёт L1/L3 (с `TenantCacheBackend`) и регистрирует их в глобальном
  `CacheInvalidator`. `plugins/composition/service_setup.py` вызывает её,
  передавая `disk_path=cache_settings.disk_fallback_path` (прямое чтение поля,
  без `getattr` — гейт cycle 163).

### 4. Квоты: DI-провайдер + `size()` у S3

* `core/di/providers/storage.py`: `get_quota_manager_provider()` /
  `set_quota_manager_provider()`; `get_storage_facade_provider()` теперь
  передаёт фасаду `quota_manager` и `enforce_quota` (из
  `FileStorageSettings.enforce_quota`).
* `S3ObjectStorage.size()` (`head_object` → `ContentLength`, 0 для 404) и
  проксирование `size()` в `TenantObjectStorage` — теперь удаление объекта
  уменьшает счётчик **байт**, а не только файлов.

### 5. PII fast-path — во всех потребителях

* `sub_email` (канон в `core/security/pii_patterns.py`) теперь используется в
  `core/security/pii_masker.py` (для канонического `EMAIL`-паттерна) и в
  `infrastructure/observability/pii_filter.py`. Строка без `@` не сканируется
  регексом вовсе.

---

## Альтернативы (отклонённые)

* **Регистрировать pool/client только в `app.state`** — отклонено: `ExecutionContext`
  не имеет `app_state`, а CLI/воркеры работают без FastAPI-приложения; нужен
  собственный single entry point.
* **Поднимать `PlaywrightBrowserPool.startup()` на старте приложения** —
  отклонено: отсутствие playwright ломало бы старт; подъём по требованию.
* **Править 40+ классов процессоров для эмиссии audit** — отклонено:
  высокий риск и большой diff; обёртка в базовом классе покрывает их всех.
* **Эмиссия audit из движка DSL** — отклонено: событие должно создаваться на
  уровне шага (там известны capability и профиль), а не в оркестраторе.
* **Хранить tag-индекс в `UnifiedCacheFacade` (facade-level tracking)** —
  отклонено: глобальный `CacheInvalidator` (единственный потребитель —
  `services/core/base/cache_mixin.py`) работает с backend'ами, а не с фасадом.
* **Вернуть `getattr` в `service_setup.py`** — отклонено: регресс-гейт cycle 163
  (ADR-0362: конфиг не должен врать).
* **Квоты внутри `ObjectStorage`-бэкенда** — отклонено: pre-check и учёт usage
  уже живут в фасаде; дублирование разошлось бы (ADR-0390, альтернатива «е»).
* **Новый config-ключ для URL windows-worker** — отклонено: `core/config/services/rpa.py`
  вне зоны кластера; используется документированный дефолт, переопределяемый
  через `set_desktop_rpa_client_provider()`.

---

## Последствия

* **Позитивные**: RPA browser/desktop больше не падают с `RuntimeError`; каждый
  шаг с `audit_event` оставляет audit-запись (без данных); tag-инвалидация
  чистит L1/L2/L3; удаление объекта уменьшает байты квоты; PII-строки без `@`
  не сканируются регексом.
* **Осознанные изменения поведения**:
  * `MemoryBackend`/`DiskCacheBackend` теперь умеют `delete_by_tag` — прежнее
    документированное ограничение («tag-инвалидация только в фасаде», cycle 167)
    отменено; обновлены два теста, фиксировавших старое поведение;
  * `desktop_rpa` без явного клиента теперь уходит в DI-провайдер и получает
    сетевую ошибку вместо мгновенного «клиент не зарегистрирован»;
  * каждый шаг с `audit_event` создаёт fire-and-forget audit-задачу.
* **Потолок решения**: tag-индекс memory/disk живёт в памяти процесса (после
  рестарта ранее записанные ключи неизвестны) — то же ограничение, что и у
  `DiskCacheBackend.delete_pattern`; URL desktop-worker'а не вынесен в
  конфиг-модель.
* **Вне зоны (волна 20)**: `core/config/services/rpa.py` (нет поля
  `desktop_worker_url`); `services/rpa/desktop_rpa_client.py` (нет
  `aclose` — HTTP-клиент создаётся per-call).

---

## Проверка

- `.venv/bin/python -m pytest tests/unit/dsl/engine/processors tests/unit/infrastructure/cache tests/unit/infrastructure/storage tests/unit/core/config -q -p no:randomly` — **3976 passed**, 18 skipped.
- `.venv/bin/python -m pytest tests/unit/cache tests/unit/storage tests/unit/infrastructure/storage tests/unit/core/di/providers tests/unit/core/security tests/unit/infrastructure/cache tests/unit/infrastructure/observability -q -p no:randomly` — **1548 passed**, 4 skipped, 13 xpassed.
- `.venv/bin/python -m pytest tests/unit/entrypoints/middlewares tests/unit/services -q -p no:randomly` — 3577 passed, 1 pre-existing failure (`test_vault_not_configured_ok_true`).
- `.venv/bin/python -m ruff check <файлы кластера>` — clean.
- `.venv/bin/python tools/config_audit.py --scope orphans` — 0.
- `.venv/bin/python tools/check_layers.py --strict` — 41 (baseline, новых нет).
- `.venv/bin/python tools/check_docstrings.py src --max-allowed 0` — 0 missing.

---

## Связи с другими ADR

- ADR-0369 — достижимость RPA-шагов; этот ADR закрывает долг «wiring
  `browser_pool`/`desktop_rpa_client`» (G12.6).
- ADR-0370 — долг «потребитель `audit_event`» закрыт эмиссией в базовом классе.
- ADR-0390 — «потолок решения» по `size()` у S3 закрыт; DI-провайдер квот
  теперь создаёт менеджер (ADR-0390 §7).
- ADR-0391 — дефект «tag-инвалидация — no-op» закрыт расширением на L1/L3.
- ADR-0392 — fast-path `sub_email` теперь применяется всеми потребителями.
- ADR-0393 — outcome `denied` в audit-событии соответствует семантике
  capability-гейта.
