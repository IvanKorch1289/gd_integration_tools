# DSL Audit — RPA / OCR / Archives / Hash / Search / Proxy / WAF / Antivirus

> **Актуальность.** Документ приведён в соответствие с кодом в cycle 172
> (ADR-0370). Capability-имена сверены с vocabulary
> (`src/backend/core/security/capabilities/vocabulary/defaults/`),
> список процессоров — с `src/backend/dsl/engine/processors/`.
> Гейт актуальности — `tests/rpa/test_rpa_docs.py`.

## Существующие процессоры

| Категория | Файл | Процессор | Capability |
|---|---|---|---|
| **OCR** | `rpa/operations/imageocrprocessor.py` | `ImageOcrProcessor` (pytesseract) | `rpa.image.ocr` |
| **OCR** | `ai_banking/document.py` | `DocumentClassifierProcessor`, `FrancotypingProcessor`, `TransactionCategorizerProcessor`, `FinDocOcrLlmProcessor` | нет (AI-контур) |
| **OCR (helper)** | `rpa/pdf_extract.py` | `PdfExtractProcessor` | нет (standalone-helper) |
| **Documents** | `rpa/documents.py` | `PdfReadProcessor` / `PdfMergeProcessor` / `WordReadProcessor` / `WordWriteProcessor` / `ExcelReadProcessor` | `rpa.pdf.read` / `rpa.pdf.merge` / `rpa.word.read` / `rpa.word.write` / `rpa.excel.read` |
| **Documents (helper)** | `rpa/office_extract.py` | `OfficeExtractProcessor` | нет (standalone-helper) |
| **Archives** | `rpa/operations/archiveprocessor.py` | `ArchiveProcessor` (zip/tar/gz) | `rpa.archive.execute` |
| **Archives** | `zip_archive.py` | `ZipArchiveProcessor` | нет (legacy, без гейта) |
| **Hash** | `rpa/operations/hashprocessor.py` | `HashProcessor` (md5/sha/blake) | `rpa.hash.compute` |
| **Hash** | `webhook_signature.py` | `WebhookSignatureProcessor` (HMAC) | нет |
| **Search** | `rpa/operations/regexprocessor.py` | `RegexProcessor` | `rpa.regex.execute` |
| **Search** | `regex_extractor.py` | `RegexExtractorProcessor` | нет (legacy, без гейта) |
| **Search** | `web_search.py` | `WebSearchProcessor` | нет (шейперы) |
| **Search** | `streaming/windows.py` | `_BaseWindow` | нет |
| **Proxy** | `proxy/forward.py` | `ForwardToProcessor` | нет |
| **Proxy** | `proxy/redirect.py` | `RedirectProcessor` | нет |
| **Proxy** | `proxy/expose.py` | `ExposeProxyProcessor` | нет |
| **WAF** | `waf_check.py` | `WafCheckProcessor` (19 OWASP CRS-паттернов) | `security.waf.check` |
| **Antivirus** | `scan_file.py` | `ScanFileProcessor` (ClamAV) | нет (гейта нет — owner-задача) |
| **Detect** | `rpa/mime_detect.py` | `MimeDetectProcessor` (magic bytes) | нет (standalone-helper) |
| **Detect** | `rpa/encoding_detect.py` | `EncodingDetectProcessor` | нет (standalone-helper) |

> «нет» = у процессора не объявлен `required_capability`; capability-гейт
> к нему не применяется. Это осознанный долг (ADR-0361/ADR-0366),
> а не ошибка документации.

## GAPS (открытые)

| Gap | Описание | Статус |
|---|---|---|
| `FileSearchProcessor` | Поиск подстроки/regex в файлах с фильтром по path | **P2 — открыт**: класса нет ни в одном модуле `src/backend`; guard `validate_path` есть, но подключать нечего |

## Закрытые ранее пункты

Были в GAPS-таблице S171 M17.1, с тех пор реализованы:

| Бывший gap | Реализация |
|---|---|
| `PdfExtractProcessor` | `rpa/pdf_extract.py` (lazy pypdf) |
| `OfficeExtractProcessor` | `rpa/office_extract.py` (python-docx / openpyxl) |
| `MimeDetectProcessor` | `rpa/mime_detect.py` (magic bytes, stdlib-only) |
| `EncodingDetectProcessor` | `rpa/encoding_detect.py` |

> Все четыре — **standalone-helpers**, а не `BaseProcessor`: они не
> регистрируются в `ProcessorRegistry` и недостижимы из YAML. При
> подключении к DSL им нужен `required_capability` + регистрация.

## Открытый долг вне GAPS-таблицы

Capability-гейт не объявлен у legacy-процессоров proxy/antivirus и у
части core-процессоров: `ForwardToProcessor`, `RedirectProcessor`,
`ExposeProxyProcessor`, `ScanFileProcessor`, `ZipArchiveProcessor`,
`RegexExtractorProcessor`, `WebhookSignatureProcessor`. Для них
`required_capability` пуст — гейт не применяется. Это долг
ADR-0361/ADR-0366 (fail-closed enforcement для baseline-набора), а не
дефект документации.

## DSL capability taxonomy

Реальные capability-имена (все — из vocabulary, 108 штук):

```python
# RPA — файлы / документы / почта
required_capability: str | None = "rpa.file.list"       # файловые операции
required_capability: str | None = "rpa.pdf.read"        # документы
required_capability: str | None = "rpa.email.read"       # почта

# RPA — вычисления и интеграции
required_capability: str | None = "rpa.hash.compute"     # хеши
required_capability: str | None = "rpa.archive.execute"  # архивы
required_capability: str | None = "rpa.regex.execute"    # поиск по тексту
required_capability: str | None = "rpa.shell.exec"       # shell
required_capability: str | None = "rpa.http.request"     # HTTP-интеграции

# Ядро
required_capability: str | None = "security.waf.check"   # WAF (D207)
required_capability: str | None = "fs.read"              # файловая система ядра
```

Имена вида `ocr.extract`, `archive.extract`, `fs.hash`, `fs.search`,
`proxy.invoke`, `security.antivirus.scan` **в vocabulary не существуют** —
предыдущая версия этого документа ссылалась на выдуманные capability.

## Связанные документы

- `docs/rpa/RPA_GUIDE.md` — обзор RPA-подсистемы и capability-каталог;
- ADR-0358 — path-allowlist;
- ADR-0361 — семантика `required_capability`;
- ADR-0366 — runtime-enforcement capability-гейта;
- ADR-0370 — консолидация RPA-конфига и тестовая гигиена.
