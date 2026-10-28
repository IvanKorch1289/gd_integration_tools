# ADR-0357 — Отдельная capability `storage.presign` для presigned-URL (cycle 172)

* Статус: Accepted (2026-10-27, cycle 172)
* Cycle: 172
* Связан с: [ADR-0354](0354-cacheprocessor-tenant-services-facade.md) — Capability-проверка на границе services-фасада
* Затрагивает:
  - `src/backend/services/storage/facade.py`
  - `src/backend/core/security/capabilities/vocabulary/defaults/base.py`
  - `src/backend/core/security/capabilities/core_declarations.py`
  - `src/backend/core/security/capabilities/gate/__init__.py`
  - `src/backend/dsl/engine/processors/storage/s3.py`

## Контекст

До Wave 13 `StorageFacade.presigned_url()` проверял capability
`storage.read`. Это неверно отражало семантику операции: presigned-URL
выдаёт клиенту самостоятельный доступ к объекту в бакете, а не выполняет
чтение сервисной учётной записью внутри `StorageFacade`.

В общем случае подписанный URL может быть сформирован для операции
записи; текущий S3-backend выдаёт `get_object`-URL
(`src/backend/infrastructure/storage/s3.py:596-603`), но capability должна
описывать право выдать делегированный доступ, а не факт текущего read
вызова.

До разделения capability DSL-шаг `s3_presign` объявлял `storage.read`,
хотя его фактический эффект — выдача URL. Это позволяло смешивать два
разных решения: право читать через сервис и право делегировать доступ
клиенту.

Дополнительным дефектом был `AttributeError` в DSL-шаге: процессор
вызывал `facade.supports_presigned()`, которого у `StorageFacade` не было.
Регрессия зафиксирована в
`tests/unit/dsl/engine/processors/storage/test_s3_processors.py:222-236`.

## Решение

Ввести отдельную public capability **`storage.presign`** и требовать её
для выдачи presigned-URL.

### 1. Capability в vocabulary

`storage.presign` зарегистрирована с `matcher=path_glob` и
`public=True` в `src/backend/core/security/capabilities/vocabulary/defaults/base.py:193-207`.
Scope capability — ключ объекта, как и у `storage.read`/`storage.write`.

`public=True` снимает только declaration-time ограничение для
core-маршрутов; runtime-проверка scope остаётся. Семантика `public`
зафиксирована в
`src/backend/core/security/capabilities/vocabulary/models.py:24-35`.

### 2. Baseline-декларации ядра

`storage.presign` включена в общий набор capability ядра
(`src/backend/core/security/capabilities/core_declarations.py:44-69`).
Тот же baseline регистрируется для `core`, `system` и `ai-agent` в
process-wide capability gate
(`src/backend/core/security/capabilities/gate/__init__.py:145-170`).

### 3. Enforcement в `StorageFacade`

Фасад получил отдельный `_assert_presign(key)`
(`src/backend/services/storage/facade.py:83-86`). В
`presigned_url()` проверка выполняется **до** `try` вокруг вызова backend'а
(`src/backend/services/storage/facade.py:248-264`).

Так сохраняется исходный тип ошибки `CapabilityDeniedError`
(`src/backend/core/security/capabilities/errors.py:48-86`): если бы
проверка находилась внутри `try`, blanket `except Exception` превратил бы
отказ capability в `ServiceError` и скрыл причину deny.

### 4. DSL-процессор

`S3PresignProcessor` объявляет ровно `capabilities=("storage.presign",)`
(`src/backend/dsl/engine/processors/storage/s3.py:276-280`). Перед выдачей
URL процессор также проверяет поддержку операции backend'ом
(`src/backend/dsl/engine/processors/storage/s3.py:309-320`).

### 5. Capability-нейтральное определение поддержки

В `StorageFacade` добавлен `supports_presigned()`: метод делегирует
проверку backend'у, а если старый backend не имеет такого метода,
возвращает `True` (`src/backend/services/storage/facade.py:266-283`).
Проверка поддержки не требует capability, поскольку сама по себе не
выдаёт URL и не раскрывает данные.

## Альтернативы

### Вариант A: оставить `storage.read` (отклонён)

**Почему отклонён:** право выдать клиенту прямой доступ к бакету не
эквивалентно праву сервиса читать объект. Объединение этих прав не
позволяет выразить политику «можно читать, но нельзя делегировать URL»
и «можно делегировать URL, но нельзя читать через сервис».

### Вариант B: требовать `storage.write` (отклонён)

**Почему отклонён:** presign не означает запись объекта сервисной
учётной записью и не должен требовать права изменения бакета. Более
того, операция выдачи ссылки не эквивалентна ни read, ни write: её
смысл — делегирование доступа клиенту. Отдельная capability точнее
фиксирует этот контракт.

### Вариант C: не добавлять `supports_presigned()`, полагаться на исключение backend'а (отклонён)

**Почему отклонён:** обработка отсутствующего метода через
`AttributeError` в DSL-процессоре была неявным контрактом и приводила к
непонятной ошибке. Явный feature-детектор отделяет «операция не
поддерживается» от ошибки доступа capability.

## Последствия

### Позитивные

- Право выдачи presigned-URL отделено от read/write и проверяется по
  scope конкретного ключа.
- `CapabilityDeniedError` не маскируется `ServiceError`.
- Capability-метаданные `s3_presign` соответствуют фактическому эффекту
  шага.
- Старые backend'ы без `supports_presigned()` не ломают DSL-шаг.

### Негативные и ограничения

- Существующие декларации, полагавшиеся только на `storage.read` для
  выдачи URL, должны явно объявить `storage.presign`.
- `supports_presigned()` по умолчанию возвращает `True` для старых
  backend'ов без метода; это совместимость, а не утверждение, что все
  они действительно поддерживают presign.
- Текущий S3 backend формирует `get_object`-URL; отдельная capability
  оставляет место для безопасного upload-URL без смешения прав.

## Проверка после реализации

```bash
.venv/bin/python -m pytest \
  tests/unit/services/storage/test_facade.py \
  tests/unit/dsl/engine/processors/storage/test_s3_processors.py -q
```

## Связи с другими ADR

- [ADR-0354](0354-cacheprocessor-tenant-services-facade.md) — capability
  enforcement на границе services-фасада.
- Capability-модель ADR-044: `public` не отключает runtime scope-check.
