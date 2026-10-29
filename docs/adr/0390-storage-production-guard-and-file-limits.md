# ADR-0390 — Production-guard хранилища, пути/файлы и лимиты (волна 18, G1)

* Статус: Accepted (2026-10-29, cycle 173, волна 18)
* Cycle: 173 (волна 18, кластер G1 — хранилище и файлы)
* Связан с:
  - ADR-0358 (allowlist файловых путей + единый path-барьер DSL)
  - ADR-0367 (RPA: path-allowlist + CSV formula-инъекция)
  - ADR-0362 (конфиг не должен врать: лимиты — в модулях, а не в «мёртвых» ключах)
  - ADR-0369 (target `body` в HTTP-процессорах)
* Затрагивает:
  - `src/backend/infrastructure/storage/factory.py`
  - `src/backend/infrastructure/storage/local_fs.py`
  - `src/backend/core/config/dsl.py`
  - `src/backend/dsl/engine/processors/_path_safety.py`
  - `src/backend/dsl/engine/processors/_csv_safety.py` (новый)
  - `src/backend/dsl/engine/processors/components/file{read,write}processor.py`
  - `src/backend/dsl/engine/processors/rpa/operations/{filelist,ftpupload,csvread,csvwrite,httprequest}processor.py`
  - `src/backend/dsl/engine/processors/rpa/documents.py`
  - `src/backend/services/storage/facade.py`
  - `src/backend/core/config/services/storage.py` (поле `enforce_quota`)
  - `config_profiles/base.yml` (секция `fs: enforce_quota`)

## Контекст

Повторный аудит (волна 18) нашёл 11 дефектов в кластере «хранилище и файлы».
Критический дефект (1) ломал storage в production полностью; остальные —
обходы path-allowlist, fail-open гейт, гонки и отсутствие лимитов.

| # | Severity | Дефект | Последствие |
|---|---|---|---|
| 1 | critical | `factory.get_object_storage()` вызывал `_enforce_local_fs_safe_in_prod()` **безусловно** перед сборкой цепочки `S3→LocalFS` | `ProductionConfigError` даже при `provider=aws`: storage не инициализировался ВООБЩЕ, все DSL-шаги `to_s3`/`from_s3` в проде падали |
| 2 | medium (регрессия) | `DSL_ALLOWED_PATHS` (env-override, ADR-0358 §2) ломал Settings: pydantic ждёт JSON для `list[str]` | `SettingsError: error parsing value for field "allowed_paths"` → приложение не стартует, audit-транспорт теряет события |
| 3 | high | `FileListProcessor` валидировал только статический префикс паттерна | pattern `<allow>/*/../../etc/hostname` проходил барьер, glob отдавал файл вне allowlist |
| 4 | high | `ftpuploadprocessor.py` определял production по deprecated `APP_ENV` | plaintext-FTP fail-open в проде (пароль/файл уходили открытым текстом) |
| 5 | medium | LocalFS: предсказуемое имя tmp-файла `path.tmp` | 4 конкурентных upload → 3× `FileNotFoundError`; при ошибке `.tmp` оставался навсегда |
| 6 | medium | `LocalFSStorage._safe_path`: prefix-check без разделителя | `/…/storage_evil/pwned.txt` принимался (symlink-escape) |
| 7 | medium | `record_upload`/`record_delete` не вызывались нигде в `src/` | usage всегда 0, `check_can_upload` всегда разрешал даже при `enforce_quota=true` |
| 8 | medium | `CsvReadProcessor`: жёсткий utf-8, без лимитов | cp1251 → необработанный `UnicodeDecodeError`; CSV-бомба съедала память |
| 9 | medium/low | Нет лимитов: FileRead (файл в память), FileList (число), Excel (строки), HttpRequest (размер ответа) | OOM-векторы |
| 10 | medium | `FileWriteProcessor.csv` не нейтрализовал формулы (ADR-0367 покрыл только `CsvWriteProcessor`) | та же CSV-инъекция (OWASP) |
| 11 | medium | `provider="local"` → bare LocalFS без tenant-префикса | обход пер-тенантных квот |

## Решение

1. **Prod-guard только для фактического backend'а.** `_enforce_local_fs_safe_in_prod()`
   вызывается только когда LocalFS становится **рабочим** backend'ом
   (`provider=local` или fallback после отказа S3). LocalFS в роли *secondary*
   (цепочка `S3→LocalFS`) guard'ом не блокируется — это буфер runtime-fallback,
   а не storage. Вспомогательная функция `_local_fs_instance()` создаёт LocalFS
   без guard'а, `get_local_fs_storage()` — с guard'ом.
2. **Свой env-парсер для `DSL_ALLOWED_PATHS`.** Поле `allowed_paths` помечено
   `Annotated[list[str], NoDecode]` (pydantic-settings не пытается разбирать
   JSON), а `field_validator(mode="before")` разбирает env-строку по `:`.
   YAML-профиль (список) применяется как раньше; env-override приоритетнее YAML.
3. **FileList: три барьера.** `..` в паттерне запрещён (`_has_traversal`),
   каждый результат glob проверяется по allowlist (`is_path_allowed` — с
   разрешением симлинков), количество результатов ограничено
   (`_MAX_FILE_LIST_RESULTS = 1000`, `glob.iglob` + ранний выход).
4. **FTP-гейт по каноническому окружению.** `_is_production_environment()`
   читает `settings.app.environment`; неизвестное окружение → fail-closed
   (production). Deprecated `APP_ENV` больше не используется.
5. **Уникальный tmp-файл.** Имя ``.{name}.{uuid4}.tmp`` в каталоге цели +
   `finally: unlink` (ошибка записи не оставляет мусор).
6. **Граница `base_path` через `Path.is_relative_to`** вместо `str.startswith`
   (каталог-сосед `<base>_evil` больше не принимается).
7. **Учёт usage в фасаде.** `StorageFacade.upload/upload_stream` вызывают
   `record_upload` после успешной записи, `delete` — `record_delete`
   (размер — через duck-typed `size()` у backend'а, иначе 0). Фасад без
   явного `quota_manager` (создаётся DI-провайдером) использует
   ленивый default-менеджер, иначе записи через него не учитывались бы.
   Дополнительно в `FileStorageSettings` добавлено поле `enforce_quota`
   (default ``false``, env ``FS_ENFORCE_QUOTA``) — composition root читал
   ``getattr(settings.storage, "enforce_quota", False)``, но такого поля
   в модели не было, поэтому enforcement был всегда выключен (alert-only).
8. **CSV-read: автоопределение кодировки + лимиты.** `utf-8-sig → cp1251 →
   latin-1`; лимиты на размер файла (`_MAX_CSV_BYTES`) и число строк
   (`_MAX_CSV_ROWS`), понятная ошибка вместо `UnicodeDecodeError`/OOM.
9. **Лимиты на объём.** FileRead (`_MAX_FILE_READ_BYTES`), FileList
   (`_MAX_FILE_LIST_RESULTS`), Excel (`_MAX_EXCEL_ROWS`), HttpRequest
   (`_MAX_HTTP_RESPONSE_BYTES`, streaming-чтение с проверкой по ходу) и
   FileWrite (`_MAX_FILE_WRITE_BYTES`). Лимиты — константы модулей, без новых
   config-ключей (ADR-0362).
10. **Канон CSV-нейтрализации вынесен** в `processors/_csv_safety.py`
    (`neutralize_formula`); его используют и `CsvWriteProcessor`, и
    `FileWriteProcessor` (значения **и** заголовки).
11. **Tenant-префикс и для `provider="local"`** — `get_object_storage()`
    возвращает `TenantObjectStorage` во всех ветках (S3, цепочка, local).

### Осознанные изменения поведения

- `provider="local"` больше не возвращает bare `LocalFSStorage` — ключи
  получают префикс `tenants/<tenant_id>/` (совпадает с layout'ом
  `LocalFSStorage.tenant_root`).
- `get_object_storage()` в production при `provider=aws` **работает**;
  fail-stop остался только для фактического LocalFS.
- `FileRead`/`FileWrite`/`CsvRead`/`HttpRequest` отказывают на превышении
  лимитов с понятным сообщением (`exchange.fail`).
- `FileWriteProcessor` в CSV-ветке пишет через `csv.DictWriter` с
  нейтрализованными именами колонок; строки с «лишними» ключами больше не
  роняют запись (значение отсутствующей колонки → пустая строка).

## Альтернативы (отклонённые)

- **(а) Убрать prod-guard полностью** — отклонено: LocalFS как фактический
  backend в production действительно опасен (нет шифрования/репликации);
  fail-stop нужен, но только в этом случае.
- **(б) Fail-open на secondary-fallback** — отклонено: тогда запись в проде
  молча уходила бы на pod-local диск (потеря данных при eviction).
- **(в) Новый config-ключ `dsl.allowed_paths_separator`** — отклонено:
  разделитель — часть формата env-override, а не отдельная настройка
  (ADR-0362: конфиг не должен врать).
- **(г) Разбирать `DSL_ALLOWED_PATHS` только в `_path_safety`** — отклонено:
  Settings всё равно падал бы при сборе (`SettingsError`), то есть приложение
  не стартовало; парсер нужен в модели.
- **(д) Фильтровать «плохие» результаты glob вместо отказа** — отклонено:
  fail-closed заметнее: маршрут получает ошибку, а не неполный список.
- **(е) Квоты — в `ObjectStorage`-бэкенде (обёртка в factory)** — отклонено:
  pre-check уже живёт в фасаде; дублирование логики в двух местах разошлось
  бы. Учёт usage — в той же точке, что и проверка.
- **(ж) `mkstemp` вместо `uuid4` для tmp-файла** — отклонено: `uuid4` в том
  же каталоге даёт ту же уникальность без лишних `fd`-операций; каталог
  остаётся тем же → `os.replace` атомарен.
- **(з) Лимиты через settings** — отклонено: см. ADR-0362 (мёртвые ключи).

## Последствия

- **Позитивные**: storage в production инициализируется (починены все
  `to_s3`/`from_s3`); приложение стартует с `DSL_ALLOWED_PATHS`; обход
  allowlist через glob-pattern закрыт; plaintext-FTP в проде выключен;
  конкурентные записи в LocalFS больше не падают; квоты тенанта реально
  работают; CSV-инъекция закрыта во всех CSV-процессорах; OOM-векторы
  ограничены.
- **Затронутые тесты**: `tests/unit/infrastructure/storage/test_factory.py` —
  тесты, фиксировавшие старое (неверное) поведение, обновлены: bare LocalFS →
  `TenantObjectStorage`, а «prod + S3 success → ProductionConfigError»
  инвертирован в «prod + S3 success → storage работает».
- **Потолок решения**: квоты считаются в Redis-счётчиках без per-key
  учёта — перезапись одного ключа увеличивает счётчик файлов; при удалении
  ключа размер берётся из `size()` backend'а (для S3-совместимых backend'ов
  без `size()` байты не уменьшаются — уменьшается только счётчик файлов).
  Лимиты — константы: для разных деплоев требуется правка кода.
- **Вне зоны (волна 18)**: `core/di/providers/storage.py` создаёт фасад без
  `quota_manager` (alert-only pre-check там не применяется — учёт usage
  работает через default-менеджер); `infrastructure/storage/s3.py` не имеет
  `size()` (см. «потолок решения»); `resilience/components/object_storage_chain.py`
  использует `get_local_fs_storage()` напрямую.

## Проверка

- `pytest tests/unit/storage/test_adr0390_storage_prod_guard.py tests/unit/storage/test_adr0390_local_fs.py tests/unit/core/config/test_adr0390_dsl_allowed_paths.py tests/unit/dsl/engine/processors/rpa/operations/test_adr0390_file_list.py tests/unit/dsl/engine/processors/rpa/operations/test_adr0390_ftp_env.py tests/unit/dsl/engine/processors/rpa/operations/test_adr0390_csv_read.py tests/unit/dsl/engine/processors/components/ tests/unit/services/storage/` — 76 passed.
- `pytest tests/unit/infrastructure/storage/ tests/unit/storage/ tests/unit/services/storage/ tests/unit/dsl/engine/processors/` — passed (2568+ в processors, 199 в storage).
- `ruff check src/backend/` — по моим файлам чисто (12 ошибок — pre-existing, в cache-модулях других кластеров).
- `tools/config_audit.py --scope orphans` — 0 (новых config-ключей нет).
- `tools/check_layers.py --strict` — baseline 41 (новых нарушений нет).
- `tools/check_docstrings.py src --max-allowed 0` — 0 missing.

## Связи с другими ADR

- ADR-0358 — allowlist путей и единый path-барьер; этот ADR усиливает барьер
  для glob-паттернов (результаты проверяются, а не только префикс).
- ADR-0367 — CSV formula-инъекция; канон нейтрализации переиспользован
  `FileWriteProcessor` (раньше покрыт был только `CsvWriteProcessor`).
- ADR-0362 — лимиты вынесены в модули, а не в новые (мёртвые) ключи конфига.
- ADR-0369 — target `body` в `HttpRequestProcessor` сохранён (ADR-0390 меняет
  только способ чтения ответа).
