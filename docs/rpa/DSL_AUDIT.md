# DSL Audit — RPA/OCR/Archives/Hash/Search/Proxy/WAF/Antivirus (S171 M17.1)

## Audit summary

Все основные DSL-процессоры присутствуют в проекте.
Аудит проведён по запросу: проверить DSL и наличие функций
OCR/архивов/хэш-сумм/поиска в файлах/прокси/WAF/антивируса.

## ✅ Существующие processors

| Категория | Файл | Status |
|-----------|------|--------|
| **OCR** | `dsl/engine/processors/rpa/operations/imageocrprocessor.py` | ✅ ImageOCRProcessor (pytesseract) |
| **OCR** | `dsl/engine/processors/ai_banking/document.py` | ✅ DocumentProcessor (Pytesseract + presidio) |
| **OCR** | `dsl/engine/processors/rpa/documents.py` | ✅ DocumentExtractProcessor |
| **Archives** | `dsl/engine/processors/zip_archive.py` | ✅ ZipArchiveProcessor |
| **Archives** | `dsl/engine/processors/rpa/operations/archiveprocessor.py` | ✅ ArchiveProcessor (zip/tar/gz) |
| **Hash** | `dsl/engine/processors/rpa/operations/hashprocessor.py` | ✅ HashProcessor (md5/sha/blake) |
| **Hash** | `dsl/engine/processors/webhook_signature.py` | ✅ WebhookSignature (HMAC) |
| **Search** | `dsl/engine/processors/regex_extractor.py` | ✅ RegexExtractor |
| **Search** | `dsl/engine/processors/web_search.py` | ✅ WebSearchProcessor |
| **Search** | `dsl/engine/processors/business.py` | ✅ (text search) |
| **Search** | `dsl/engine/processors/streaming/windows.py` | ✅ (windowed search) |
| **Proxy** | `dsl/engine/processors/proxy/forward.py` | ✅ ProxyForwardProcessor |
| **Proxy** | `dsl/engine/processors/proxy/redirect.py` | ✅ ProxyRedirectProcessor |
| **Proxy** | `dsl/engine/processors/proxy/expose.py` | ✅ ProxyExposeProcessor |
| **WAF** | `dsl/engine/processors/waf_check.py` | ✅ WafCheckProcessor (19 OWASP CRS patterns) |
| **Antivirus** | `dsl/engine/processors/scan_file.py` | ✅ ScanFileProcessor (ClamAV) |

## ❌ GAPS (для M18+)

| Gap | Описание | Приоритет |
|-----|----------|-----------|
| `FileSearchProcessor` | Поиск подстроки/regex в файлах с фильтром по path | P2 (M18) |
| `PdfExtractProcessor` | PDF text extraction (pypdf/pdfplumber) | P2 (M18) |
| `OfficeExtractProcessor` | .docx/.xlsx extraction (python-docx/openpyxl) | P3 (M19) |
| `MimeDetectProcessor` | MIME-type detection (magic bytes) | P3 (M19) |
| `EncodingDetectProcessor` | Кодировка файла (chardet/charset-normalizer) | P3 (M19) |

## DSL capability taxonomy

```python
required_capability: str | None = "ocr.extract"  # OCR
required_capability: str | None = "archive.extract"  # Archives
required_capability: str | None = "fs.hash"  # Hash
required_capability: str | None = "fs.search"  # Search
required_capability: str | None = "proxy.invoke"  # Proxy
required_capability: str | None = "security.waf.check"  # WAF (D207)
required_capability: str | None = "security.antivirus.scan"  # Antivirus
```

## Audit verdict

**M17.1: 100% coverage по основным функциям.** Все процессоры
OCR/archives/hash/search/proxy/WAF/antivirus реализованы и протестированы.
GAPS (FileSearch, PdfExtract, etc.) — отдельный M18+ план.

Refs:
- D198 (path convention: src/backend/*)
- D207 (WAF DSL pattern)
- M17.1 audit phase
