# RPA Guide (Sprint 171 — M6)

> **Domain-agnostic RPA infrastructure.** 37+ DSL processors covering
> file operations, terminal/shell, documents (PDF/Word/Excel), browser
> automation (patchright), desktop (pywinauto), OCR (pytesseract),
> image processing, banking integrations (Citrix/Terminal3270).

## Architecture

```
DSL Processors (35+ classes, 8 files)
        ↓
Capability-Gated (rpa.file.*, rpa.shell.*, rpa.browser.*, ...)
        ↓
HTTP Middleware: RpaPolicyMiddleware (deny-by-default, role check)
        ↓
Audit Events (rpa.* в ClickHouse/Redis)
```

## File Operations (10 processors)

| Processor | Capability | Description |
|-----------|-----------|-------------|
| `FileMoveProcessor` | `rpa.file.move` | copy/move/rename |
| `FileDeleteProcessor` | `rpa.file.delete` | secure file/dir deletion |
| `FileListProcessor` | `rpa.file.list` | glob-поиск (async via `to_thread`) |
| `FilteredDirectoryScanProcessor` (M7) | `rpa.directory.scan` | recursive `**` + size/mtime filters |
| `FileWatchProcessor` | `rpa.file.watch` | watchdog create/modify/delete |
| `ArchiveProcessor` | `rpa.file.archive` | ZIP/TAR/GZ |
| `HashProcessor` | `rpa.file.hash` | SHA256/MD5 |
| `EncryptProcessor` | `rpa.file.encrypt` | symmetric encryption |
| `DecryptProcessor` | `rpa.file.decrypt` | symmetric decryption |
| `TemplateRenderProcessor` | `rpa.file.template` | Jinja2 |
| `RegexProcessor` | `rpa.file.regex` | extract/replace |

## Terminal / Shell (2 processors)

| Processor | Capability | Description |
|-----------|-----------|-------------|
| `ShellExecProcessor` | `rpa.shell.exec` | sync shell exec |
| `TerminalExecProcessor` | `rpa.shell.exec` | async subprocess с timeout (M6) |

## Documents (8 processors)

| Processor | Capability | Description |
|-----------|-----------|-------------|
| `PdfReadProcessor` | `rpa.doc.pdf.read` | extract text |
| `PdfMergeProcessor` | `rpa.doc.pdf.merge` | combine PDFs |
| `WordReadProcessor` | `rpa.doc.word.read` | .docx text |
| `WordWriteProcessor` | `rpa.doc.word.write` | .docx creation |
| `ExcelReadProcessor` | `rpa.doc.excel.read` | openpyxl-based |

## Images (3 processors)

| Processor | Capability | Description |
|-----------|-----------|-------------|
| `ImageOcrProcessor` | `rpa.image.ocr` | pytesseract |
| `ImageResizeProcessor` | `rpa.image.resize` | pillow |
| `ImageConvertProcessor` | `rpa.image.convert` | pillow format |

## Browser Automation (8 processors)

| Processor | Capability | Description |
|-----------|-----------|-------------|
| `BrowserLaunchProcessor` | `rpa.browser.launch` | patchright (anti-detection) |
| `NavigateProcessor` | `rpa.browser.navigate` | URL |
| `ClickProcessor` | `rpa.browser.click` | click element |
| `FillProcessor` | `rpa.browser.fill` | form input |
| `ExtractProcessor` | `rpa.browser.extract` | text/data |
| `WaitForProcessor` | `rpa.browser.wait` | wait for selector |
| `ScreenshotProcessor` | `rpa.browser.screenshot` | PNG capture |
| `PdfProcessor` | `rpa.browser.pdf` | browser → PDF |

## Banking (4 processors)

| Processor | Capability | Description |
|-----------|-----------|-------------|
| `CitrixSessionProcessor` | `rpa.banking.citrix` | Citrix ICA |
| `TerminalEmulator3270Processor` | `rpa.banking.terminal3270` | mainframes |
| `AppiumMobileProcessor` | `rpa.banking.appium` | mobile |
| `EmailDrivenProcessor` | `rpa.banking.email` | email workflow |

## Desktop (Windows-only, requires `[rpa-windows]` extra)

- `DesktopRpaProcessor` — pywinauto Win32/UIA automation
- `KeystrokeReplayProcessor` — record/replay keystrokes

## Security (defense in depth)

**3 layers:**

1. **HTTP middleware** (`RpaPolicyMiddleware`, M6 NEW)
   - Layer 1, order 124
   - Deny-by-default for `/api/v1/rpa/*`
   - Requires `rpa.admin` role in `X-Roles` header
   - Audit denied requests

2. **DSL capability check** (`required_capability` on every processor)
   - Per-processor capability string
   - Resolved at runtime via `CapabilityGate`
   - Default-deny

3. **Audit events** (`audit_event` on every processor)
   - All RCE-shaped ops logged to ClickHouse/Redis
   - Includes path, command, user, timestamp

## Performance

**Async patterns:**
- `asyncio.to_thread` для I/O-bound ops (file I/O, network)
- `asyncio.create_subprocess_shell` для shell ops с timeout
- `asyncio.wait_for(proc.communicate(), timeout)` для cancellation

**CPU-bound patterns:**
- `src.backend.core.utils.cpu_bound.run_cpu_bound(fn, ...)` для heavy ops
- `use_process_pool=True` для parallel across cores
- Default: `asyncio.to_thread` (lightweight)

**Settings** (`config_profiles/dev.yml`):
```yaml
rpa:
  shell_timeout_s: 30
  file_watch_timeout_s: 60
  max_archive_size_mb: 1000
  process_pool_size: 3  # cpu_count - 1
```

## Usage example (DSL YAML)

```yaml
- file_list:
    pattern: "/incoming/*.csv"
    recursive: true
    to: body.files
- terminal_exec:
    command: "wc -l ${body.files[0]}"
    timeout: 10
    to: body.line_count
- file_delete:
    path: "${body.files[0]}"
    missing_ok: true
```

## Patterns (D-rules)

- **D143**: RPA thin wrapper pattern — 1-line delegation to library
- **D144**: RCE-shaped capability gating (audit + role)
- **D145**: async subprocess pattern (`create_subprocess_shell` + timeout)
- **D146**: file I/O via `asyncio.to_thread` (no blocking event loop)
- **D147**: RpaPolicyMiddleware deny-by-default

## See also

- `src/backend/dsl/engine/processors/rpa/` — all DSL processors
- `src/backend/services/rpa/` — service-layer implementations
- `src/backend/entrypoints/middlewares/rpa_policy.py` — security middleware
- `src/backend/core/utils/cpu_bound.py` — performance helper
