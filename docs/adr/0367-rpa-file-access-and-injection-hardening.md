# ADR-0367 — Файловый доступ и защита от инъекций в RPA-процессорах

* Статус: Accepted (2026-10-28, cycle 172)
* Cycle: 172 (Wave 14, RPA-кластер C2)
* Связан с:
  - ADR-0358 (allowlist файловых путей + единый path-барьер DSL)
  - ADR-0361 (семантика `required_capability` / capability-гейт)
  - ADR-0354 (запрет прямых импортов `services.*` из DSL)
* Затрагивает:
  - `src/backend/dsl/engine/processors/rpa/operations/csvreadprocessor.py`
  - `src/backend/dsl/engine/processors/rpa/operations/csvwriteprocessor.py`
  - `src/backend/dsl/engine/processors/rpa/operations/filedeleteprocessor.py`
  - `src/backend/dsl/engine/processors/rpa/operations/archiveprocessor.py`
  - `src/backend/dsl/engine/processors/rpa/documents.py`

## Контекст

Ревью RPA-подсистемы (роём из 8 агентов, cycle 172) нашло, что часть
файловых RPA-процессоров не проходит второй независимый барьер
безопасности — path-allowlist (`validate_path`,
`src/backend/dsl/engine/processors/_path_safety.py`). Capability-гейт
(`required_capability`) ограничивает **факт вызова** процессора, но не
**путь**, к которому он обращается: процессор с валидной capability
читал/писал произвольные файлы ФС.

| Процессор | Дефект | Последствие |
|---|---|---|
| `CsvReadProcessor` | `src` не проверяется | чтение любого CSV (PII) |
| `CsvWriteProcessor` | `dst` не проверяется | запись/перезапись любого файла |
| `PdfReadProcessor` | путь из тела запроса | эксфильтрация PII (`body='/tmp/rpa_secret.pdf'`) |
| `WordReadProcessor` | путь из тела запроса | то же |
| `ExcelReadProcessor` | путь из тела запроса | то же (`body='/tmp/rpa_secret.xlsx'`) |

Помимо allowlist, ревью нашло четыре независимых дефекта:

1. **CSV formula-инъекция** (`CsvWriteProcessor`): значение `=cmd|'/c calc'!A0`
   писалось «как есть» — при открытии CSV в Excel/LibreOffice ячейка
   исполняется как формула (OWASP CSV Injection).
2. **Zip-slip** (`ArchiveProcessor`, режим `create`): имя записи архива не
   санитизировалось — `ZIP ENTRIES: ['../../etc/cron.d/evil']`.
3. **Нет кап на распаковку** (`ArchiveProcessor`, режим `extract`):
   zip/tar-bomb распаковывается целиком в память → OOM процесса.
4. **AttributeError** (`FileDeleteProcessor`): `exchange.in_message.body.get("path")`
   падал с `AttributeError: 'str' object has no attribute 'get'`, если тело
   запроса — не dict.

Отдельно `CsvWriteProcessor` строил заголовок по ключам **первой** строки
(`list(self.rows[0].keys())`), а писал все строки → на разнородных ключах
`ValueError: dict contains fields not in fieldnames`.

## Решение

1. **Allowlist во всех файловых RPA-процессорах.** Паттерн — как в
   `filemoveprocessor.py:58-68`:
   `try: safe = validate_path(p) except PathTraversalError as exc: exchange.fail("... blocked: ..."); return`.
   Проверяются **оба** пути (источник и цель), если процессор работает с ними.
2. **Единый хелпер `_safe_body_path()`** в `rpa/documents.py` — для пути,
   приходящего из тела запроса (PDF/Word/Excel). Bytes-ветки (файл из
   памяти) allowlist **не** требуют — файловой системы они не касаются.
3. **CSV formula-инъекция нейтрализуется префиксом `'`** для строковых
   значений, начинающихся с `=`, `+`, `-`, `@`. Числа (`int`/`float`) и
   прочие типы **не** изменяются. Нейтрализуются и значения ячеек, и имена
   колонок (header — тоже ячейка). Совпадение имён колонок после
   нейтрализации → понятная `ValueError`, а не тихая порча данных.
4. **Zip-slip устранён**: имя записи при создании архива проходит через
   `os.path.basename`; пустое имя, `.` и `..` → отказ.
5. **Капы на распаковку** — модульные константы (без новых config-ключей):
   `_MAX_UNPACK_BYTES = 64 * 1024 * 1024`, `_MAX_ENTRIES = 1000`.
   Сумма заявленных размеров и число записей проверяются **до** чтения
   содержимого; дополнительно — per-entry cap на фактически прочитанные
   байты (`read(cap + 1)`).
6. **`FileDeleteProcessor`**: тело запроса проверяется `isinstance(body, dict)`
   (образец — `filemoveprocessor.py:49`), не-dict → путь не берётся.
7. **`CsvWriteProcessor`**: колонки — union ключей всех строк
   (`dict.fromkeys`, порядок первого появления); не-`Mapping` строка →
   понятная `ValueError`. Файл создаётся **после** валидации строк.

### Осознанное изменение поведения

- `csv_read`/`csv_write` теперь требуют путь внутри `dsl.allowed_paths`
  (`DSL_ALLOWED_PATHS` или YAML-профиль). Это ожидаемо: тот же контракт уже
  действует для `FileList`/`FileWatch`/`DirectoryScan`/`FtpUpload` (ADR-0358).
- `csv_write` нейтрализует строковые значения и имена колонок, начинающиеся
  с `=`, `+`, `-`, `@`. Значения типа `int`/`float` не трогаются.
- `archive extract` отказывает на архивах > 64 MiB (суммарно) или > 1000
  записей.

## Альтернативы (отклонённые)

- **(а) Новые config-ключи для кап архива** (`dsl.archive_max_bytes` и т.п.) —
  отклонено: капы безопасности не должны зависеть от окружения; лимит по
  умолчанию в модуле достаточен, а конфигурируемость добавит новые
  «мёртвые» ключи конфига (ADR-0362).
- **(б) Проверка allowlist только в capability-гейте** — отклонено:
  capability ограничивает вызов, а не путь; разделение ответственности
  (ADR-0358) требует второго независимого барьера.
- **(в) Проверка allowlist в `BaseProcessor.process()`** (централизованно) —
  отклонено: у каждого процессора свой источник пути (`src`/`dst`/`body`/
  glob), а единая точка не различает «путь» и «произвольная строка»
  (например, inline-контент CSV или `body` как bytes).
- **(г) CSV-инъекция: экранирование через `quoting=csv.QUOTE_ALL`** —
  отклонено: кавычки не мешают Excel трактовать ячейку как формулу.
- **(д) Zip-slip: отказ при наличии `..` в имени** — отклонено: безопаснее
  не отказывать, а санитизировать (`basename`) — валидные «плоские» архивы
  продолжают работать.
- **(е) Распаковка потоково (без кап)** — отклонено: не защищает от
  zip-bomb (сжатые данные малого размера → огромный распакованный объём).

## Последствия

- **Позитивные**: закрыты эксфильтрация PII через `csv_read`/`pdf_read`/
  `word_read`/`excel_read` и запись произвольных файлов через `csv_write`;
  zip-slip и zip/tar-bomb больше не приводят к записи вне каталога и OOM;
  CSV-файлы, открытые в Excel/LibreOffice, больше не исполняют формулы из
  данных.
- **Затронутые тесты**: существующие CSV-тесты используют `tmp_path` вне
  allowlist → в них добавлен `monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))`
  (проверка allowlist **не** ослаблена).
- **Потолок решения**: allowlist защищает от выхода за пределы разрешённых
  каталогов, но не от чтения «разрешённого» файла — это отдельная задача
  (уровень доступа к данным). Капы распаковки не защищают от архива,
  проходящего по размеру, но вредоносного по содержимому.
- **Вне зоны**: `filelistprocessor.py`, `ftpuploadprocessor.py`,
  `filemoveprocessor.py`, `hashprocessor.py`, `encryptprocessor.py` — уже
  проверяют путь (ADR-0358) и в этом цикле не менялись.

## Проверка

- `pytest tests/unit/dsl/engine/processors/rpa/operations/test_archiveprocessor_async.py`
  `tests/unit/dsl/engine/processors/rpa/operations/test_rpa_path_allowlist.py`
  `tests/unit/dsl/engine/processors/rpa/operations/test_more_rpa_tools.py`
  `tests/unit/dsl/engine/processors/rpa/operations/test_new_rpa_tools.py`
  `tests/unit/dsl/engine/processors/rpa/operations/test_document_processors.py` — 64 passed.
- `tools/check_layers.py --strict` — 41 (baseline, новых нет).
- `tools/check_docstrings.py src --max-allowed 0` — 1 missing (pre-existing,
  `dsl/builders/infra_logging_mixin.py`).
- `tools/config_audit.py --scope orphans` — 0 (новых config-ключей нет).

## Связи с другими ADR

- ADR-0358 — allowlist файловых путей и единый path-барьер; этот ADR
  распространяет барьер на оставшиеся RPA-процессоры.
- ADR-0361 — семантика `required_capability`: capability-gate ограничивает
  вызов, allowlist — путь (два независимых барьера).
- ADR-0354 — DSL не импортирует `services.*` напрямую; в этом ADR новых
  межслойных импортов не введено.
- ADR-0362 — принцип «конфиг не должен врать»: капы вынесены в модуль,
  а не в неиспользуемые ключи конфига.
