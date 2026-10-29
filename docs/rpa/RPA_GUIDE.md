# RPA Guide (Sprint 171 — M6; актуализировано в cycle 172)

> **Domain-agnostic RPA infrastructure.** 46 DSL-процессоров под
> capability-гейтом: файловые операции, terminal/shell, документы
> (PDF/Word/Excel), браузерная автоматизация (patchright), desktop
> (pywinauto / pyautogui), OCR (pytesseract), изображения, почта и
> банковские интеграции (Citrix / Terminal3270 / Appium).

> **Актуальность документа.** Capability-таблица ниже генерируется из
> vocabulary (`src/backend/core/security/capabilities/vocabulary/defaults/rpa_fs.py`)
> и сверяется с `required_capability` процессоров. Гейт актуальности —
> `tests/rpa/test_rpa_docs.py` (падает при расхождении с кодом).

## Архитектура

```
DSL-процессоры (46 с rpa.* capability)
        ↓
Capability-гейт (required_capability → CapabilityGate)
        ↓
HTTP-middleware: RpaPolicyMiddleware (deny-by-default, role-check)
        ↓
path-allowlist (settings.dsl.allowed_paths) — для файловых операций
```

> **Audit-события RPA-процессоров не реализованы.** Класс `audit_event`
> объявлен на 308 процессорах, но потребителя у него нет: ни DSL-движок,
> ни middleware не читают это поле, в ClickHouse/Redis ничего не пишется.
> Это owner-задача (подключение audit-sink к DSL-слою), а не реализованная
> возможность. Не строьте архитектуру, опираясь на «audit events → ClickHouse».

## Capability-каталог RPA

Имена — из vocabulary; 41 capability, 46 процессоров (три capability
используются двумя-тремя процессорами: `rpa.shell.exec` — тремя,
`rpa.http.request` — тремя).

### Файлы, каталоги, архивы, передача (9)

| Процессор | Capability | Назначение |
|---|---|---|
| `FileMoveProcessor` | `rpa.file.move` | move / copy / rename файла |
| `FileDeleteProcessor` | `rpa.file.delete` | удаление файла или каталога |
| `FileListProcessor` | `rpa.file.list` | glob-поиск по каталогу (async) |
| `FilteredDirectoryScanProcessor` | `rpa.directory.scan` | рекурсивный `**` + фильтры size/mtime |
| `FileWatchProcessor` | `rpa.file.watch` | watchdog: create / modify / delete |
| `ArchiveProcessor` | `rpa.archive.execute` | ZIP / TAR / GZ (create + extract) |
| `CsvReadProcessor` | `rpa.file.csv.read` | чтение CSV (файл или inline-контент) |
| `CsvWriteProcessor` | `rpa.file.csv.write` | запись CSV + защита от formula-injection |
| `FtpUploadProcessor` | `rpa.ftp.upload` | выгрузка по FTP/FTPS (TLS по умолчанию) |

### Хеши, крипто, текст (5)

| Процессор | Capability | Назначение |
|---|---|---|
| `HashProcessor` | `rpa.hash.compute` | SHA256 / MD5 / BLAKE |
| `EncryptProcessor` | `rpa.crypto.encrypt` | Fernet (AES-128-CBC + HMAC-SHA256) |
| `DecryptProcessor` | `rpa.crypto.decrypt` | Fernet |
| `RegexProcessor` | `rpa.regex.execute` | extract / replace / match |
| `TemplateRenderProcessor` | `rpa.template.render` | Jinja2 (sandboxed) |

### Shell, сеть, почта (6)

| Процессор | Capability | Назначение |
|---|---|---|
| `ShellExecProcessor` | `rpa.shell.exec` | синхронный shell-exec (fail-closed whitelist, ADR-0368) |
| `TerminalExecProcessor` | `rpa.shell.exec` | async subprocess с timeout |
| `SshCommandProcessor` | `rpa.shell.exec` | выполнение команды по SSH |
| `HttpRequestProcessor` | `rpa.http.request` | async HTTP-запрос (httpx) |
| `EmailComposeProcessor` | `rpa.email.send` | отправка письма по SMTP |
| `EmailReadProcessor` | `rpa.email.read` | чтение письма по IMAP |

### Документы (5)

| Процессор | Capability | Назначение |
|---|---|---|
| `PdfReadProcessor` | `rpa.pdf.read` | извлечение текста из PDF |
| `PdfMergeProcessor` | `rpa.pdf.merge` | объединение PDF |
| `WordReadProcessor` | `rpa.word.read` | чтение .docx |
| `WordWriteProcessor` | `rpa.word.write` | создание .docx |
| `ExcelReadProcessor` | `rpa.excel.read` | чтение XLSX (openpyxl) |

### Изображения и OCR (2)

| Процессор | Capability | Назначение |
|---|---|---|
| `ImageOcrProcessor` | `rpa.image.ocr` | OCR через pytesseract (Tesseract на хосте) |
| `ImageResizeProcessor` | `rpa.image.resize` | изменение размера (Pillow) |

### Браузерная автоматизация (8)

| Процессор | Capability | Назначение |
|---|---|---|
| `BrowserLaunchProcessor` | `rpa.browser.launch` | запуск браузера (patchright) |
| `NavigateProcessor` | `rpa.browser.navigate` | переход по URL |
| `ClickProcessor` | `rpa.browser.click` | клик по элементу |
| `FillProcessor` | `rpa.browser.fill` | заполнение поля формы |
| `ExtractProcessor` | `rpa.browser.extract` | извлечение текста/данных |
| `WaitForProcessor` | `rpa.browser.wait` | ожидание селектора |
| `ScreenshotProcessor` | `rpa.browser.screenshot` | снимок экрана (PNG) |
| `PdfProcessor` | `rpa.browser.pdf` | сохранение страницы в PDF |

### Банкинг, desktop, AI (8)

| Процессор | Capability | Назначение |
|---|---|---|
| `CitrixSessionProcessor` | `rpa.citrix.invoke` | Citrix ICA-сессия (заглушка: делегирует в сервис) |
| `TerminalEmulator3270Processor` | `rpa.terminal3270.invoke` | мейнфрейм 3270 (заглушка) |
| `AppiumMobileProcessor` | `rpa.appium.invoke` | мобильная автоматизация (заглушка) |
| `EmailDrivenProcessor` | `rpa.email.extract` | pipeline «письмо → структурированные данные» (заглушка) |
| `KeystrokeReplayProcessor` | `rpa.keystroke.replay` | воспроизведение сценария клавиатуры/мыши |
| `DesktopRpaProcessor` | `rpa.desktop.invoke` | desktop-приложения через windows-worker sidecar |
| `DesktopPyAutoGUIProcessor` | `rpa.desktop.automate` | автоматизация desktop через pyautogui |
| `AIRpaProcessor` | `rpa.ai.decide` | AI-принятие решения внутри RPA-сценария |

### Веб-скрейпинг (3)

| Процессор | Capability | Назначение |
|---|---|---|
| `ScrapeProcessor` | `rpa.http.request` | одноразовый scrape страницы |
| `PaginateProcessor` | `rpa.http.request` | постраничный обход |
| `ApiProxyProcessor` | `rpa.http.request` | проксирование API-вызовов |

## Безопасность (defense in depth)

**Слоя 2 (из 3 заявленных работают):**

1. **HTTP-middleware** (`RpaPolicyMiddleware`, pure ASGI)
   - deny-by-default для префикса `/api/v1/rpa`;
   - требуемая роль — `rpa.admin` (настраивается через `required_role`);
   - источник роли — **`scope["state"]["auth"].roles`**, объект auth-контекста,
     который выставляет upstream auth-middleware. Заголовок `X-Roles` **не
     читается** (см. `src/backend/entrypoints/middlewares/rpa_policy.py:104-116`);
   - при отсутствии auth-контекста — 403 (fail-closed).

2. **DSL capability-гейт** (`required_capability` на каждом процессоре)
   - имя capability сверяется с vocabulary и с baseline-декларацией ядра
     (`core/security/capabilities/core_declarations.py`);
   - fail-closed: незаявленная capability → deny;
   - фактическая enforcement — ADR-0366.

3. **Audit-события** — **не реализованы** (см. врезку в разделе «Архитектура»).

## Политика prod / staging (ADR-0393) — RPA-шаги fail-closed

> **Важно.** В prod и staging RPA-шаги **не работают** до появления
> плагина-владельца RPA-capability.

В `config_profiles/prod.yml` и `config_profiles/staging.yml`:

```yaml
features:
  dsl_capability_gate_enabled: true
  dsl_capability_core_baseline_enabled: false
```

Что это значит на практике:

* capability-гейт в prod/staging **включён** (runtime-резолвер
  ADR-0366): namespace = `route_id` роута → fallback `"core"` (baseline)
  → fail-closed DENY;
* core-baseline **выключен** → least privilege: доступ определяется
  только декларациями роутов/плагинов;
* capability `rpa.*` **не публична** и **не принадлежит ни одному
  плагину** → RPA-шаги в prod/staging отклоняются **fail-closed**;
* объявить `rpa.*` прямо в `route.toml` нельзя: subset-инвариант
  `route.capabilities ⊆ plugins ∪ public` отклоняет такой роут
  (`CapabilitySupersetError`) — роут просто не загрузился бы. Поэтому
  RPA-capability требует **плагина-владельца** (ADR-0078 / ADR-044).

Практический вывод: RPA-сценарии работают в dev/dev_light (гейт
выключен, legacy-путь). Для prod их нужно сначала провести через
плагина-владельца capability — иначе шаг упадёт с отказом capability-гейта
до выполнения операции.

Проверка профиля (`core/config/validator/profile_merge.py`) поднимает
CRITICAL, если в prod/staging capability-гейт выключен, и WARNING,
если включён core-baseline.

Подробнее — [Capability runtime](../explanation/capability_runtime.md).

## Path-allowlist (ADR-0358)

Файловые RPA-операции (и core-процессоры FileRead/FileWrite/FileWatch/
FileDelete/DirectoryScan) работают **только** внутри allowlist-каталогов:

| Источник | Значение |
|---|---|
| `settings.dsl.allowed_paths` | список каталогов (`config_profiles/base.yml`, секция `dsl:`) |
| env `DSL_ALLOWED_PATHS` | перекрывает список; разделитель — `:` |
| по умолчанию | `/data/uploads`, `/data/exports`, `/tmp/dsl`, `/var/data` |

Проверка — `validate_path()` в `src/backend/dsl/engine/processors/_path_safety.py`:
путь нормализуется (`Path.resolve`) и отклоняется, если не попадает ни в один
разрешённый префикс (`PathTraversalError`). Аргумент проверяется **до**
обращения к файловой системе.

В YAML-шагах путь берётся из параметров конструктора, поэтому литерал
пути в маршруте должен попадать в allowlist — иначе шаг завершится
ошибкой `PathTraversalError`, а не «пустым результатом».

## Настройки

Модель — `src/backend/core/config/services/rpa.py` (`RPASettings`,
env-префикс `RPA_`, `extra="forbid"`). Секция `rpa:` в
`config_profiles/base.yml` содержит только живые поля:

```yaml
rpa:
  browser_pool_size: 2                     # предсозданных Playwright-контекстов
  browser_headless: true                   # false — только для локальной отладки
  browser_launch_max_retries: 2            # повторов (не попыток) при transient-crash
  browser_launch_retry_base_seconds: 0.5   # база exponential backoff
```

Параметры desktop-RPA pool'а (`base_url`, `api_key`, `timeout`,
`ttl_seconds`, `max_sessions`) — ctor-аргументы `DesktopRPASessionPool`,
а не настройки приложения. Мёртвые поля (13 штук) удалены в ADR-0370.

Флаги — в `core/config/features/`: `rpa_session_persistence`,
`browser_cookies_redis_persist`, `desktop_rpa_session_pool_enabled`,
`rpa_resilience_wrapper_enabled`, `rpa_ocr_enabled`.

## Производительность

**Async-паттерны:**
- `asyncio.to_thread` для blocking I/O (файлы, сеть);
- `asyncio.create_subprocess_exec` + `asyncio.wait_for` для shell;
- `run_cpu_bound(fn, use_process_pool=True)` из
  `src/backend/core/utils/cpu_bound.py` для CPU-bound задач (PDF/OCR/image).

**Известные ограничения:**
- `wait_for(to_thread(...))` не прерывает поток executor'а — поток
  доработает текущий I/O (owner-задача, вне cycle 172);
- `pdfplumber` молча отдаёт `tables=[]` при отсутствии зависимости —
  установку `pdfplumber` нужно контролировать (ADR-0367).

## Пример маршрута (DSL YAML)

Имена шагов — публичные методы `RouteBuilder` (`dsl/builders/ai_rpa/rpa.py`).
Ключи внутри шага — kwargs конструктора процессора.

```yaml
route_id: rpa.inbox.daily
source:
  http:
    method: POST
    path: /api/v1/rpa/inbox/daily
steps:
  - email_read:
      host: imap.example.com
      port: 993
      user: robot
      folder: INBOX
      to: body.emails
  - csv_write:
      dst: /data/exports/mails.csv
      rows:
        - subject: "Отчёт за день"
          rows: 42
  - file_list:
      pattern: /data/exports/*.csv
      recursive: true
      to: body.files
  - terminal_exec:
      command: wc -l /data/exports/mails.csv
      timeout: 10
      to: body.line_count
  - file_delete:
      path: /data/exports/mails.csv
      missing_ok: true
```

> Имена `file_list` / `terminal_exec` / `file_delete` / `csv_read` /
> `csv_write` / `ftp_upload` / `http_request` / `email_read` появились в
> `RouteBuilder` в cycle 172 (ADR-0369). До этого соответствующие
> процессоры существовали, но были недостижимы из YAML
> («Unknown or forbidden processor»).

## Связанные ADR

- **ADR-0358** — allowlist файловых путей и единый path-барьер DSL;
- **ADR-0361** — семантика `required_capability`;
- **ADR-0366** — runtime-enforcement capability-гейта;
- **ADR-0367** — файловый доступ и защита от инъекций в RPA-процессорах;
- **ADR-0368** — fail-closed whitelist shell-команд;
- **ADR-0369** — достижимость RPA-шагов из YAML и канон имён;
- **ADR-0370** — консолидация RPA-конфига и тестовая гигиена;
- **ADR-0393** — DB-capability-гейт, tenant-изоляция DSL-SQL и
  авторизация RPA (в т.ч. prod/staging-политика выше).

## Где смотреть код

- `src/backend/dsl/engine/processors/rpa/` — RPA-процессоры (operations, documents);
- `src/backend/dsl/engine/processors/rpa_browser.py` — браузер;
- `src/backend/dsl/engine/processors/rpa_banking.py` — банкинг/desktop-заглушки;
- `src/backend/services/rpa/` — сервисный слой (session pool, cookies, OCR);
- `src/backend/entrypoints/middlewares/rpa_policy.py` — security-middleware;
- `src/backend/core/utils/cpu_bound.py` — helper для CPU-bound задач;
- `src/backend/core/security/capabilities/vocabulary/defaults/rpa_fs.py` — vocabulary.
