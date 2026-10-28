# ADR-0358 — Allowlist файловых путей в конфиг-системе и единый path-барьер DSL (cycle 172)

* Статус: Accepted (2026-10-27, cycle 172)
* Cycle: 172
* Связан с: [ADR-0112](0112-security-audit-status.md) — allowlist-регекс для SQL-идентификаторов
* Затрагивает:
  - `src/backend/core/config/dsl.py`
  - `src/backend/dsl/engine/processors/_path_safety.py`
  - `src/backend/dsl/engine/processors/file_watch.py`
  - `src/backend/dsl/engine/processors/fs_directory_scan.py`
  - `src/backend/dsl/engine/processors/rpa/operations/`
  - `config_profiles/base.yml`

## Контекст

До Wave 13 allowlist файловых путей существовал только как env-переменная
`DSL_ALLOWED_PATHS`. Это делало конфигурацию зависимостью от окружения
процесса, а не от профиля приложения. При этом path-guard вызывался
только в трёх файловых процессорах — FileRead, FileWrite и FileDelete
(это ограничение зафиксировано в
`tests/unit/dsl/engine/processors/test_core_fs_path_allowlist.py:1-10`).

Активные сканеры и файловые операции обходили allowlist:

| Процессор | Недоверенный ввод | Проверка в текущем коде |
|---|---|---|
| Core `FileWatchProcessor` | каталог из конфигурации/property | `src/backend/dsl/engine/processors/file_watch.py:184-195` |
| Core `DirectoryScanProcessor` | `path` из тела запроса | `src/backend/dsl/engine/processors/fs_directory_scan.py:140-176` |
| RPA `FileListProcessor` | glob из конфигурации/тела запроса | `src/backend/dsl/engine/processors/rpa/operations/filelistprocessor.py:88-113` |
| RPA `FilteredDirectoryScanProcessor` | каталог | `src/backend/dsl/engine/processors/rpa/operations/filtereddirectoryscanprocessor.py:70-86` |
| RPA `FileWatchProcessor` | каталог | `src/backend/dsl/engine/processors/rpa/operations/filewatchprocessor.py:77-92` |
| RPA `FtpUploadProcessor` | локальный путь читаемого файла | `src/backend/dsl/engine/processors/rpa/operations/ftpuploadprocessor.py:78-100` |

Ранее `FileListProcessor` и `DirectoryScanProcessor` брали путь/паттерн
из тела запроса без allowlist-проверки. Сейчас оба значения проходят
общий барьер до обращения к файловой системе
(`src/backend/dsl/engine/processors/rpa/operations/filelistprocessor.py:90-113`,
`src/backend/dsl/engine/processors/fs_directory_scan.py:159-176`).

Отдельно зафиксирован `FileSearchProcessor`
(`src/backend/dsl/engine/processors/rpa/file_search.py:20-66`): это
standalone-helper, а не зарегистрированный `BaseProcessor`; активных
callers в `src/backend` нет. Guard (`validate_path`) добавлен follow-up'ом
Wave 13, чтобы при подключении к DSL защита уже была на месте.

## Решение

### 1. Источник истины — конфигурация приложения

В `DSLSettings` добавлено поле `allowed_paths`
(`src/backend/core/config/dsl.py:26-48`,
`src/backend/core/config/dsl.py:76-88`). Настройка загружается из секции
`dsl:` корневого `Settings`
(`src/backend/core/config/settings.py:155-156`) и объявлена в профиле
`config_profiles/base.yml:659-669`.

### 2. Приоритет источников

`validate_path()` получает разрешённые каталоги в следующем порядке:

1. env `DSL_ALLOWED_PATHS` — операционный override;
2. `settings.dsl.allowed_paths` — профильный источник истины;
3. встроенные defaults — fallback, если конфиг недоступен.

Порядок реализован в
`src/backend/dsl/engine/processors/_path_safety.py:37-71`; встроенный
fallback — в `src/backend/dsl/engine/processors/_path_safety.py:27-34`.
Таким образом, env может явно переопределить профильный список (в том
числе расширить его), но не расширяет allowlist неявно.

### 3. Единый path-барьер

Целевой контракт решения — единый `validate_path()` для локальных
path-процессоров DSL. Helper нормализует путь, отклоняет
traversal-компоненты и проверяет принадлежность одному из разрешённых
префиксов (`src/backend/dsl/engine/processors/_path_safety.py:74-111`).

В текущем рабочем дереве guard применён к следующим локальным
path-процессорам:

- чтение/запись: `components/filereadprocessor.py:36-60`,
  `components/filewriteprocessor.py:38-72`;
- удаление: `rpa/operations/filedeleteprocessor.py:49-68`;
- core-сканеры: `file_watch.py:184-195`,
  `fs_directory_scan.py:159-176`;
- RPA-сканеры/загрузка: `rpa/operations/filelistprocessor.py:88-113`,
  `rpa/operations/filtereddirectoryscanprocessor.py:70-86`,
  `rpa/operations/filewatchprocessor.py:77-92`,
  `rpa/operations/ftpuploadprocessor.py:78-100`.

### 4. Glob-паттерны

Сам glob нельзя резолвить как путь (`**/*.py` не является обычным
`Path`). Поэтому для `FileListProcessor` валидируется статический
**каталоговый** префикс до первого magic-символа
(`src/backend/dsl/engine/processors/rpa/operations/filelistprocessor.py:27-59`).
Проверка каталога, а не произвольного начала строки, не позволяет
`/data/uploads*/*.txt` пройти через `/data/uploads` и затем матчить
`/data/uploads_backup/*`.

### 5. Capability и allowlist — независимые барьеры

Capability ограничивает **факт вызова** процессора, allowlist —
**путь**, к которому процессор обращается. Например,
`FileListProcessor` сначала проверяет `rpa.file.list`
(`src/backend/dsl/engine/processors/rpa/operations/filelistprocessor.py:62-90`),
затем отдельно проверяет путь
(`src/backend/dsl/engine/processors/rpa/operations/filelistprocessor.py:98-113`).
Наличие одной capability не отменяет path-guard и наоборот.

### 6. Известные границы покрытия

Follow-up к этому ADR закрыл три оставшихся случая (Wave 13, Q7c):

- RPA `FileMoveProcessor` — валидируются оба пути (`src` и `dst`) до
  обращения к ФС; в операции передаются уже resolved-пути
  (`src/backend/dsl/engine/processors/rpa/operations/filemoveprocessor.py:54-84`).
- `RenderTemplateFileProcessor` — `validate_path` добавлен ДО чтения
  шаблона, существующий `_safe_template_path()` сохранён как второй барьер
  (`src/backend/dsl/engine/processors/template_engine.py:151-164`).
- `FileSearchProcessor` — standalone-helper: `validate_path(str(root))`
  в начале `search()`, fail-fast `PathTraversalError`; активных callers
  в `src/backend` нет, но guard присутствует до подключения к DSL
  (`src/backend/dsl/engine/processors/rpa/file_search.py:52-66`).

Остаётся осознанное ограничение: для glob-паттернов проверяется
статический префикс каталога, а не каждый найденный результат (см.
«Негативные и ограничения»).

## Альтернативы

### Вариант A: оставить только env `DSL_ALLOWED_PATHS` (отклонён)

**Почему отклонён:** allowlist нельзя единообразно описать в
версионируемом YAML-профиле, проверять конфигурационным аудитом и
каталогизировать вместе с остальными настройками DSL. Env остаётся
удобным override, но не единственным источником истины.

### Вариант B: добавить конфиг, но не расширять покрытие процессоров (отклонён)

**Почему отклонён:** конфигурационный allowlist не защищает процессоры,
которые его не вызывают. Сканеры и RPA-операции продолжили бы читать
произвольные пути, а `FileListProcessor`/`DirectoryScanProcessor` —
принимать путь из тела запроса.

### Вариант C: оставить только capability-проверку (отклонён)

**Почему отклонён:** capability отвечает на вопрос «кому разрешено
вызвать операцию», но не ограничивает путь внутри разрешённой операции.
Владелец `rpa.file.list` смог бы запросить каталог вне разрешённой ФС.

## Последствия

### Позитивные

- Allowlist версионируется вместе с профилем приложения.
- Env-override сохранён для нестандартного размещения каталогов.
- Покрытые core- и RPA-path-процессоры используют один `validate_path`.
- Пути из тела запроса проверяются до чтения/сканирования/выгрузки в
  покрытых процессарах.
- Capability и allowlist остаются независимыми слоями защиты.

### Негативные и ограничения

- Появляется ещё один источник конфигурации, который нужно валидировать
  профилем и deployment-конфигурацией.
- Для `FileListProcessor` проверяется статический префикс glob, а не
  каждый найденный результат; симлинк внутри разрешённого каталога
  может вести наружу. Документированный предел и апгрейд находятся в
  `src/backend/dsl/engine/processors/rpa/operations/filelistprocessor.py:98-103`.
- `FileMoveProcessor`, `RenderTemplateFileProcessor` и
  `FileSearchProcessor` закрыты follow-up'ом Wave 13 (Q7c); на момент
  исходной редакции ADR они были явными implementation gaps — см.
  «Известные границы покрытия».

## Проверка после реализации

```bash
.venv/bin/python -m pytest \
  tests/unit/dsl/engine/processors/test_path_safety.py \
  tests/unit/dsl/engine/processors/test_core_fs_path_allowlist.py \
  tests/unit/dsl/engine/processors/rpa/operations/test_rpa_path_allowlist.py -q
```

## Связи с другими ADR

- [ADR-0112](0112-security-audit-status.md) — тот же принцип
  allowlist + defence-in-depth для недоверенных SQL-идентификаторов.
- Capability-модель ADR-044: capability и filesystem allowlist —
  независимые барьеры.
