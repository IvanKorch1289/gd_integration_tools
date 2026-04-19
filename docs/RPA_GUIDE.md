# RPA Guide — UiPath-style automation

Платформа поддерживает работу с файлами, документами и системными операциями
в стиле UiPath/Blue Prism через DSL-процессоры.

## Когда использовать RPA vs API vs Scraping

| Сценарий | Инструмент |
|---|---|
| Приложение имеет REST API | `.http_call()` |
| Приложение только в браузере | `.scrape()` + `.paginate()` или `.navigate()` + web automation |
| Обработка файлов (PDF/Word/Excel) | RPA-процессоры |
| Desktop приложение без API | `.shell()` + OCR + image processing |
| Интеграция через email | `.email()` + IMAP monitor |

## Работа с документами

### PDF

```python
# Извлечение текста и таблиц
route = (
    RouteBuilder.from_("pdf.parse", source="internal:pdf")
    .read_file(path="/data/invoice.pdf", binary=True)
    .pdf_read(extract_tables=True)
    .dispatch_action("invoices.save")
    .build()
)

# Объединение нескольких PDF
route = (
    RouteBuilder.from_("pdf.merge_reports", source="internal:reports")
    .dispatch_action("reports.load_pdfs")  # body = list[bytes]
    .pdf_merge()
    .write_file(path="/data/combined.pdf")
    .build()
)
```

### Word (.docx)

```python
# Чтение текста из документа
.read_file(path="report.docx", binary=True)
.word_read()
# body = {"text": "...", "paragraphs": [...]}

# Генерация документа
.set_property("data", {"paragraphs": ["Header", "Body text"]})
.word_write()
# body = bytes (.docx file)
```

### Excel

```python
# Чтение Excel в list[dict]
.read_file(path="data.xlsx", binary=True)
.excel_read(sheet_name="Orders")
# body = [{"col1": ..., "col2": ...}, ...]
.dispatch_action("analytics.insert_batch")
```

## Работа с изображениями

### OCR

```python
# Распознавание текста (русский + английский)
.read_file(path="scan.png", binary=True)
.ocr(lang="eng+rus")
# body = {"text": "...", "lang": "eng+rus"}
.dispatch_action("documents.save_text")
```

### Ресайз/конвертация

```python
.read_file(path="photo.jpg", binary=True)
.image_resize(width=800, height=600, output_format="PNG")
.write_file(path="photo_resized.png")
```

## Архивы

```python
# Распаковка ZIP
.read_file(path="archive.zip", binary=True)
.archive(mode="extract", format="zip")
# body = [{"name": "file1.txt", "data": bytes, "size": 1024}, ...]

# Создание ZIP
.set_property("files", [
    {"name": "report.pdf", "data": pdf_bytes},
    {"name": "data.csv", "data": csv_bytes},
])
.archive(mode="create", format="zip")
.write_file(path="bundle.zip")
```

## Текстовые операции

### Regex

```python
# Извлечение всех email
.regex(pattern=r"\b[\w.-]+@[\w.-]+\.\w+\b", action="extract")
# body = ["user@example.com", ...]

# Маскирование
.regex(pattern=r"\d{16}", action="replace", replacement="****************")

# Фильтр по шаблону (stop если не matches)
.regex(pattern=r"^ORDER-\d+$", action="match")
```

### Jinja2 templates

```python
.set_property("order_id", 123)
.set_property("total", 4999.99)
.render_template("Order {order_id}: total {total} rubles")
# body = "Order 123: total 4999.99 rubles"
```

## Безопасность данных

### Hash

```python
.hash(algorithm="sha256")
# body = hex-string hash
```

### Шифрование (AES Fernet)

```python
from cryptography.fernet import Fernet
key = Fernet.generate_key().decode()

# Encrypt
.encrypt(key=key)
# body = bytes (encrypted)

# Decrypt
.decrypt(key=key)
# body = bytes (decrypted)
```

## Shell команды (безопасный запуск)

```python
# Whitelist обязателен для безопасности
.shell(
    command="ls",
    args=["-la", "/data"],
    allowed_commands=["ls", "cat", "wc", "grep"],
)
# body = {"stdout": "...", "stderr": "...", "exit_code": 0}
```

**Безопасность:**
- `shell=True` никогда не используется
- Timeout 30 секунд по умолчанию
- Whitelist команд обязателен в production

## Email

```python
.set_property("order_id", 12345)
.set_property("customer_name", "Иван")
.email(
    to="customer@example.com",
    subject="Order confirmation #{order_id}",
    body_template="Уважаемый {customer_name}, ваш заказ #{order_id} принят.",
)
```

## Комплексный пример: обработка входящих документов

```python
from app.dsl.builder import RouteBuilder
from app.dsl.engine.processors import ValidateProcessor
from app.schemas.documents import DocumentSchema

route = (
    RouteBuilder.from_("documents.process_incoming", source="email_imap:inbox")
    # 1. Получаем email с attachment (body = {"attachments": [...]})
    .dispatch_action("email.parse_attachments")
    # 2. Распаковываем ZIP если нужно
    .archive(mode="extract", format="zip")
    # 3. Извлекаем текст из PDF
    .pdf_read(extract_tables=True)
    # 4. Извлекаем order_id через regex
    .regex(pattern=r"Order #(\d+)", action="extract")
    # 5. Валидация
    .validate(DocumentSchema)
    # 6. Сохраняем
    .dispatch_action("documents.save")
    # 7. Подтверждение на email
    .email(
        to="manager@example.com",
        subject="Document processed: order #{order_id}",
        body_template="Document with order #{order_id} saved successfully.",
    )
    .on_completion(
        processors=[LogProcessor(level="info")],
    )
    .build()
)
```

## Зависимости (lazy-imported)

Все тяжёлые библиотеки подгружаются ТОЛЬКО при вызове:

```bash
pip install pypdf pdfplumber        # PDF
pip install python-docx             # Word
pip install openpyxl                # Excel
pip install Pillow pytesseract      # Images + OCR
pip install jinja2                  # Templates
pip install cryptography            # Encrypt/decrypt
```
