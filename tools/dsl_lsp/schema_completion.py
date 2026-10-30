"""YAML schema completion provider for DSL LSP (Wave s19/k3-w4-lsp-server-finale).

Provides:
* ``STEP_COMPLETIONS`` — CompletionList of step type keywords with
  JSON-Schema validation snippets for each step type.
* ``ROUTE_COMPLETIONS`` — top-level route manifest keys.
* ``get_step_snippet()`` — returns the JSON-Schema skeleton for a given step type.

Used by :mod:`src.backend.dsl.cli.lsp_server` to populate ``textDocument/completion``
responses.

ADR-0369 (cycle 172, cluster C4): канон — **имя YAML-шага = имя публичного
метода ``RouteBuilder``**. Completion не предлагает фиктивных шагов и
фиктивных параметров: каждая метка — реальный метод ``RouteBuilder``, каждое
свойство snippet'а — реальный kwarg этого метода.

ADR-0399: список шагов **генерируется из каталога**
(:mod:`src.backend.dsl.builders.step_catalog`) — 438 шагов вместо 55
захардкоженных. Статический список (``_STATIC_STEP_COMPLETIONS``) остаётся
fallback'ом и источником curated-описаний для известных шагов.
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "STEP_COMPLETIONS",
    "ROUTE_COMPLETIONS",
    "get_step_snippet",
    "STEP_SCHEMA_SNIPPETS",
)


#: Curated step type keywords for the ``steps[]`` array in ``*.dsl.yaml``.
#: Each entry: (label, detail, insert_text_snippet).
#: The insert_text includes YAML indentation anchors (``${N}`` are tab-stops).
#:
#: ADR-0399: список — **fallback**; полный набор шагов генерируется из
#: каталога ``src.backend.dsl.builders.step_catalog`` (см.
#: :func:`_build_step_completions`).
_STATIC_STEP_COMPLETIONS: tuple[tuple[str, str, str], ...] = (
    (
        "proxy",
        "Прокси-запрос на upstream без бизнес-логики",
        "proxy:\n  src: ${1:/src/path}\n  dst: ${2:http://target:port}",
    ),
    (
        "redirect",
        "HTTP-redirect 30x на target URL",
        "redirect:\n  target_url: ${1:https://target.example.com}\n  status_code: ${2:302}",
    ),
    (
        "call_function",
        "Вызов Python-функции 'module:fn' через whitelist",
        "call_function:\n  ref: ${1:extensions.my_plugin:my_function}\n  payload_from: ${2:body}",
    ),
    (
        "dispatch_action",
        "Service Activator — диспетчер action в sync/async/bg/api/sse/ws",
        "dispatch_action:\n  action: ${1:my.action.name}",
    ),
    (
        "transform",
        "JMESPath-трансформация body",
        "transform:\n  expression: ${1:body}",
    ),
    (
        "choice",
        "EIP Content-Based Router — ветвление по JMESPath-выражению",
        "choice:\n  when:\n    - expr: ${1:body.status == 'active'}\n      processors:\n        - ${2:proxy:}",
    ),
    (
        "parallel",
        "EIP Scatter-Gather — параллельное выполнение ветвей",
        "parallel:\n  branches:\n    ${1:branch_a}:\n      - ${2:proxy:}",
    ),
    (
        "do_try",
        "Try-catch с компенсацией / DLQ-handoff",
        "do_try:\n  try_processors:\n    - ${1:proxy:}\n  catch_processors:\n    - ${2:audit:}",
    ),
    (
        "saga",
        "Saga-step (Temporal compensation)",
        "saga:\n  steps:\n    - forward:\n        ${1:call_function:}\n      compensate:\n        ${2:call_function:}",
    ),
    (
        "invoke_workflow",
        "Temporal/Lite workflow invocation",
        "invoke_workflow:\n  name: ${1:my_workflow}\n  args:\n    ${2:key}: ${3:value}",
    ),
    (
        "crud_create",
        "CRUD create entity через repository",
        "crud_create:\n  entity: ${1:orders}\n  payload_from: ${2:body}",
    ),
    (
        "crud_read",
        "CRUD read by id (или по фильтру из body)",
        "crud_read:\n  entity: ${1:orders}\n  id_from: ${2:body.id}",
    ),
    (
        "crud_update",
        "CRUD update by id",
        "crud_update:\n  entity: ${1:orders}\n  id_from: ${2:body.id}\n  payload_from: ${3:body}",
    ),
    (
        "crud_delete",
        "CRUD delete by id",
        "crud_delete:\n  entity: ${1:orders}\n  id_from: ${2:body.id}",
    ),
    (
        "publish_event",
        "Publish в MQ (Kafka/RabbitMQ/NATS/Redis Streams)",
        "publish_event:\n  channel: ${1:my.topic}",
    ),
    (
        "notify_cascade",
        "Email/SMS/Telegram cascade notification",
        "notify_cascade:\n  adapter_names: ${1:email}\n  recipient_path: ${2:body.recipient}\n  subject: ${3:тема}",
    ),
    (
        "audit",
        "Audit-event в audit-trail",
        "audit:\n  action: ${1:route.my_route.call}\n  actor: ${2:system}\n  outcome: ${3:success}",
    ),
    (
        "validate_response",
        "Pydantic-валидация response от внешнего API",
        "validate_response:\n  schema: ${1:MyResponseSchema}\n  on_error: ${2:fail}",
    ),
    (
        "validate_schema",
        "Валидация по схеме из schema-registry (JSON Schema / Avro / Protobuf)",
        "validate_schema:\n  subject: ${1:orders.created}",
    ),
    (
        "schema_validate",
        "Валидация body по inline JSON Schema (draft 2020-12)",
        "schema_validate:\n  schema:\n    type: object\n    properties:\n      ${1:field}: { type: ${2:string} }",
    ),
    (
        "db_query_external",
        "SELECT в внешней БД через capability db.read",
        "db_query_external:\n  profile: ${1:analytics}\n  sql: ${2:SELECT * FROM orders}\n  params_from: ${3:body}",
    ),
    (
        "db_call_procedure",
        "Вызов хранимой процедуры через capability",
        "db_call_procedure:\n  profile: ${1:analytics}\n  name: ${2:my_proc}\n  params_from: ${3:body}",
    ),
    (
        "get_setting",
        "Прочитать конфиг по path → body.x",
        "get_setting:\n  path: ${1:my.setting.path}\n  to: ${2:body.setting}",
    ),
    (
        "send_via_sink",
        "Публикация в sink (S3/Kafka/WebDAV/...)",
        "send_via_sink:\n  sink_id: ${1:s3://bucket/path}\n  payload_from: ${2:body}",
    ),
    # --- RPA (ADR-0369, решение D6) ---
    (
        "browser_launch",
        "RPA: открыть browser-сессию (Playwright pool)",
        "browser_launch:\n  url: ${1:https://example.com}",
    ),
    (
        "wait_for_selector",
        "RPA: дождаться селектора или load-state",
        "wait_for_selector:\n  selector: ${1:button.submit}\n  state: ${2:load}\n  timeout: ${3:30}",
    ),
    (
        "print_pdf",
        "RPA: отрендерить страницу в PDF",
        "print_pdf:\n  format: ${1:A4}\n  path: ${2:/tmp/report.pdf}",
    ),
    (
        "rpa_navigate",
        "RPA: переход по URL (Playwright)",
        "rpa_navigate:\n  url: ${1:https://example.com}",
    ),
    (
        "rpa_click",
        "RPA: клик по CSS/XPath-селектору (Playwright)",
        "rpa_click:\n  selector: ${1:button.submit}\n  timeout: ${2:30}",
    ),
    (
        "rpa_fill",
        "RPA: заполнить input (Playwright)",
        "rpa_fill:\n  selector: ${1:input.email}\n  value: ${2:test@example.com}",
    ),
    (
        "rpa_extract",
        "RPA: извлечь текст/атрибут (Playwright)",
        "rpa_extract:\n  selector: ${1:h1.title}\n  attribute: ${2:href}",
    ),
    (
        "rpa_screenshot",
        "RPA: скриншот страницы (Playwright)",
        "rpa_screenshot:\n  full_page: ${1:false}\n  path: ${2:/tmp/screen.png}",
    ),
    (
        "csv_read",
        "RPA: прочитать CSV (файл или inline) → body.rows",
        "csv_read:\n  src: ${1:/tmp/data.csv}\n  delimiter: ${2:,}",
    ),
    (
        "csv_write",
        "RPA: записать список dict → CSV-файл",
        "csv_write:\n  dst: ${1:/tmp/out.csv}\n  rows:\n    - ${2:key}: ${3:value}",
    ),
    (
        "file_delete",
        "RPA: удалить файл/директорию",
        "file_delete:\n  path: ${1:/tmp/stale.csv}\n  missing_ok: ${2:true}",
    ),
    (
        "file_list",
        "RPA: список файлов по glob-паттерну",
        "file_list:\n  pattern: ${1:/tmp/*.txt}\n  recursive: ${2:false}",
    ),
    (
        "file_move",
        "RPA: копировать/переместить файл",
        "file_move:\n  src: ${1:/tmp/a.txt}\n  dst: ${2:/tmp/b.txt}\n  mode: ${3:copy}",
    ),
    (
        "ftp_upload",
        "RPA: загрузить файл на FTP/SFTP (пароль — только dev, prod — Vault)",
        "ftp_upload:\n  host: ${1:ftp.example.com}\n  local_path: ${2:/tmp/a.txt}\n  remote_path: ${3:/a.txt}",
    ),
    (
        "http_request",
        "RPA: асинхронный HTTP-запрос → body {status, headers, data}",
        "http_request:\n  url: ${1:https://api.example.com/data}\n  method: ${2:GET}",
    ),
    (
        "email_read",
        "RPA: прочитать письма IMAP (пароль — только dev, prod — Vault)",
        "email_read:\n  host: ${1:imap.example.com}\n  folder: ${2:INBOX}",
    ),
    (
        "terminal_exec",
        "RPA: выполнить команду терминала",
        "terminal_exec:\n  command: ${1:ls -la}\n  timeout: ${2:30}",
    ),
    (
        "directory_scan",
        "RPA: просканировать директорию (recursive, cap по числу файлов)",
        "directory_scan:\n  path: ${1:/tmp}\n  pattern: ${2:*}\n  recursive: ${3:false}",
    ),
    (
        "ocr",
        "RPA: OCR — распознавание текста на изображении/PDF",
        "ocr:\n  lang: ${1:eng+rus}",
    ),
    (
        "pdf_read",
        "RPA: извлечь текст/таблицы из PDF",
        "pdf_read:\n  extract_tables: ${1:false}",
    ),
    (
        "pdf_merge",
        "RPA: объединить PDF-файлы",
        "pdf_merge:",
    ),
    (
        "word_read",
        "RPA: извлечь текст из .docx",
        "word_read:",
    ),
    (
        "word_write",
        "RPA: сгенерировать .docx из body",
        "word_write:",
    ),
    (
        "excel_read",
        "RPA: прочитать Excel в list[dict]",
        "excel_read:\n  sheet_name: ${1:Sheet1}",
    ),
    (
        "image_resize",
        "RPA: изменить размер изображения",
        "image_resize:\n  width: ${1:800}\n  height: ${2:600}\n  output_format: ${3:PNG}",
    ),
    (
        "archive",
        "RPA: создать/распаковать архив (zip/tar)",
        "archive:\n  mode: ${1:extract}\n  format: ${2:zip}",
    ),
    (
        "citrix",
        "RPA: операция Citrix/RDP-сессии (заглушка — нет citrix-бэкенда)",
        "citrix:\n  operation: ${1:launch}\n  session_id: ${2:sess-1}",
    ),
    (
        "terminal_3270",
        "RPA: операция IBM 3270-терминала (заглушка — нет 3270-бэкенда)",
        "terminal_3270:\n  host: ${1: mainframe.example.com}\n  port: ${2:23}\n  action: ${3:query}",
    ),
    (
        "appium_mobile",
        "RPA: операция мобильного приложения (заглушка — нет appium-бэкенда)",
        "appium_mobile:\n  platform: ${1:android}\n  app_package: ${2:com.example.app}\n  operation: ${3:launch}",
    ),
    (
        "email_driven",
        "RPA: IMAP → structured data pipeline (заглушка — реальный клиент в сервисе)",
        "email_driven:\n  mailbox: ${1:INBOX}\n  extract: ${2:body_table}",
    ),
    (
        "keystroke_replay",
        "RPA: воспроизведение записанного сценария клавиатуры (заглушка — нет pyautogui)",
        "keystroke_replay:\n  script_name: ${1:login.yaml}",
    ),
)

#: JSON-Schema validation skeletons for each step type.
#: Used by LSP hover/documentation and for schema file generation.
STEP_SCHEMA_SNIPPETS: dict[str, dict[str, object]] = {
    "proxy": {
        "type": "object",
        "required": ["src", "dst"],
        "properties": {
            "src": {"type": "string", "description": "Source path pattern"},
            "dst": {"type": "string", "description": "Destination URL"},
        },
    },
    "redirect": {
        "type": "object",
        "required": [],
        "properties": {
            "target_url": {"type": "string", "description": "Redirect target URL"},
            "status_code": {
                "type": "integer",
                "description": "HTTP redirect code",
                "default": 302,
            },
        },
    },
    "call_function": {
        "type": "object",
        "required": ["ref"],
        "properties": {
            "ref": {
                "type": "string",
                "description": "Function reference 'module:function'",
            },
            "payload_from": {
                "type": "string",
                "description": "Namespace источника аргументов",
                "default": "body",
            },
        },
    },
    "dispatch_action": {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {"type": "string", "description": "Action name"},
        },
    },
    "transform": {
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {
                "type": "string",
                "description": "JMESPath-выражение над телом",
            }
        },
    },
    "choice": {
        "type": "object",
        "required": ["when"],
        "properties": {
            "when": {
                "type": "array",
                "description": "Ветви: {expr, processors}",
                "items": {
                    "type": "object",
                    "properties": {
                        "expr": {"type": "string", "description": "JMESPath-предикат"},
                        "processors": {"type": "array", "description": "Вложенные шаги"},
                    },
                },
            },
            "otherwise": {
                "type": "array",
                "description": "Вложенные шаги ветки else",
            },
        },
    },
    "parallel": {
        "type": "object",
        "required": ["branches"],
        "properties": {
            "branches": {
                "type": "object",
                "description": "Имя ветви → список вложенных шагов",
                "additionalProperties": {"type": "array"},
            },
            "strategy": {
                "type": "string",
                "description": "Стратегия сборки результатов",
                "default": "all",
            },
        },
    },
    "do_try": {
        "type": "object",
        "required": ["try_processors"],
        "properties": {
            "try_processors": {"type": "array", "description": "Шаги try"},
            "catch_processors": {"type": "array", "description": "Шаги catch"},
            "finally_processors": {"type": "array", "description": "Шаги finally"},
        },
    },
    "saga": {
        "type": "object",
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "description": "Шаги saga: {forward, compensate}",
                "items": {
                    "type": "object",
                    "properties": {
                        "forward": {"type": "object", "description": "Прямой шаг"},
                        "compensate": {"type": "object", "description": "Компенсация"},
                    },
                },
            }
        },
    },
    "invoke_workflow": {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "description": "Workflow name"},
            "mode": {"type": "string", "description": "async-api / sync / bg"},
            "args": {"type": "object", "description": "Аргументы workflow"},
        },
    },
    "crud_create": {
        "type": "object",
        "required": ["entity"],
        "properties": {
            "entity": {"type": "string"},
            "payload_from": {"type": "string"},
            "body": {"type": "string"},
        },
    },
    "crud_read": {
        "type": "object",
        "required": ["entity"],
        "properties": {
            "entity": {"type": "string"},
            "id_from": {"type": "string"},
        },
    },
    "crud_update": {
        "type": "object",
        "required": ["entity"],
        "properties": {
            "entity": {"type": "string"},
            "id_from": {"type": "string"},
            "payload_from": {"type": "string"},
            "body": {"type": "string"},
        },
    },
    "crud_delete": {
        "type": "object",
        "required": ["entity"],
        "properties": {
            "entity": {"type": "string"},
            "id_from": {"type": "string"},
        },
    },
    "publish_event": {
        "type": "object",
        "required": ["channel"],
        "properties": {"channel": {"type": "string"}},
    },
    "notify_cascade": {
        "type": "object",
        "required": [],
        "properties": {
            "adapter_names": {"type": "array", "items": {"type": "string"}},
            "recipient_path": {"type": "string"},
            "subject": {"type": "string"},
            "body_path": {"type": "string"},
        },
    },
    "audit": {
        "type": "object",
        "required": [],
        "properties": {
            "action": {"type": "string"},
            "actor": {"type": "string"},
            "outcome": {"type": "string"},
            "metadata_from": {"type": "string"},
        },
    },
    "validate_response": {
        "type": "object",
        "required": [],
        "properties": {
            "schema": {"type": "string"},
            "on_error": {"type": "string", "enum": ["dlq", "retry", "fail", "warn"]},
            "source": {"type": "string", "enum": ["out_body", "in_body"]},
        },
    },
    "validate_schema": {
        "type": "object",
        "required": ["subject"],
        "properties": {
            "subject": {
                "type": "string",
                "description": "Subject в schema-registry",
            },
        },
    },
    "schema_validate": {
        "type": "object",
        "required": ["schema"],
        "properties": {
            "schema": {
                "type": "object",
                "description": "Inline JSON Schema (draft 2020-12)",
            },
        },
    },
    "db_query_external": {
        "type": "object",
        "required": ["profile", "sql"],
        "properties": {
            "profile": {"type": "string"},
            "sql": {"type": "string"},
            "params_from": {"type": "string"},
        },
    },
    "db_call_procedure": {
        "type": "object",
        "required": ["profile", "name"],
        "properties": {
            "profile": {"type": "string"},
            "name": {"type": "string"},
            "schema": {"type": "string"},
            "params_from": {"type": "string"},
            "dialect": {"type": "string"},
        },
    },
    "get_setting": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "to": {"type": "string"},
        },
    },
    "send_via_sink": {
        "type": "object",
        "required": ["sink_id"],
        "properties": {
            "sink_id": {"type": "string"},
            "payload_from": {"type": "string"},
        },
    },
    # --- RPA (ADR-0369) ---
    "browser_launch": {
        "type": "object",
        "required": [],
        "properties": {"url": {"type": "string"}},
    },
    "wait_for_selector": {
        "type": "object",
        "required": [],
        "properties": {
            "selector": {"type": "string"},
            "state": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
            },
            "timeout": {"type": "number", "default": 30.0},
        },
    },
    "print_pdf": {
        "type": "object",
        "required": [],
        "properties": {
            "format": {"type": "string", "default": "A4"},
            "path": {"type": "string"},
            "landscape": {"type": "boolean", "default": False},
        },
    },
    "rpa_navigate": {
        "type": "object",
        "required": ["url"],
        "properties": {"url": {"type": "string"}},
    },
    "rpa_click": {
        "type": "object",
        "required": ["selector"],
        "properties": {
            "selector": {"type": "string"},
            "timeout": {"type": "number", "default": 30.0},
        },
    },
    "rpa_fill": {
        "type": "object",
        "required": ["selector", "value"],
        "properties": {
            "selector": {"type": "string"},
            "value": {"type": "string"},
        },
    },
    "rpa_extract": {
        "type": "object",
        "required": ["selector"],
        "properties": {
            "selector": {"type": "string"},
            "attribute": {"type": "string"},
        },
    },
    "rpa_screenshot": {
        "type": "object",
        "required": [],
        "properties": {
            "full_page": {"type": "boolean", "default": False},
            "path": {"type": "string"},
        },
    },
    "csv_read": {
        "type": "object",
        "required": [],
        "properties": {
            "src": {"type": "string"},
            "content": {"type": "string"},
            "delimiter": {"type": "string", "default": ","},
            "to": {"type": "string", "default": "body.rows"},
        },
    },
    "csv_write": {
        "type": "object",
        "required": ["dst", "rows"],
        "properties": {
            "dst": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "object"}},
            "delimiter": {"type": "string", "default": ","},
        },
    },
    "file_delete": {
        "type": "object",
        "required": [],
        "properties": {
            "path": {"type": "string"},
            "missing_ok": {"type": "boolean", "default": True},
        },
    },
    "file_list": {
        "type": "object",
        "required": [],
        "properties": {
            "pattern": {"type": "string"},
            "recursive": {"type": "boolean", "default": False},
            "to": {"type": "string", "default": "body.files"},
        },
    },
    "file_move": {
        "type": "object",
        "required": [],
        "properties": {
            "src": {"type": "string"},
            "dst": {"type": "string"},
            "mode": {"type": "string", "enum": ["copy", "move", "rename"]},
        },
    },
    "ftp_upload": {
        "type": "object",
        "required": ["host", "local_path", "remote_path"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 21},
            "user": {"type": "string"},
            "password": {
                "type": "string",
                "description": "Только dev; в prod — Vault",
            },
            "local_path": {"type": "string"},
            "remote_path": {"type": "string"},
            "allow_insecure_ftp": {"type": "boolean", "default": False},
        },
    },
    "http_request": {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "default": "GET"},
            "headers": {"type": "object"},
            "body": {},
            "timeout": {"type": "number", "default": 30.0},
            "to": {"type": "string", "default": "body"},
        },
    },
    "email_read": {
        "type": "object",
        "required": ["host"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 993},
            "user": {"type": "string"},
            "password": {
                "type": "string",
                "description": "Только dev; в prod — Vault",
            },
            "folder": {"type": "string", "default": "INBOX"},
            "to": {"type": "string", "default": "body.emails"},
        },
    },
    "terminal_exec": {
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number", "default": 30.0},
            "to": {"type": "string", "default": "body.output"},
            "shell": {"type": "boolean", "default": False},
        },
    },
    "directory_scan": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "pattern": {"type": "string", "default": "*"},
            "recursive": {"type": "boolean", "default": False},
            "max_files": {"type": "integer", "default": 1000},
            "sort_by": {"type": "string", "default": "name"},
        },
    },
    "ocr": {
        "type": "object",
        "required": [],
        "properties": {"lang": {"type": "string", "default": "eng+rus"}},
    },
    "pdf_read": {
        "type": "object",
        "required": [],
        "properties": {"extract_tables": {"type": "boolean", "default": False}},
    },
    "pdf_merge": {
        "type": "object",
        "required": [],
        "properties": {},
    },
    "word_read": {
        "type": "object",
        "required": [],
        "properties": {},
    },
    "word_write": {
        "type": "object",
        "required": [],
        "properties": {},
    },
    "excel_read": {
        "type": "object",
        "required": [],
        "properties": {"sheet_name": {"type": "string"}},
    },
    "image_resize": {
        "type": "object",
        "required": [],
        "properties": {
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "output_format": {"type": "string", "default": "PNG"},
        },
    },
    "archive": {
        "type": "object",
        "required": [],
        "properties": {
            "mode": {"type": "string", "enum": ["extract", "create"]},
            "format": {"type": "string", "default": "zip"},
        },
    },
    "citrix": {
        "type": "object",
        "required": ["operation", "session_id"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["launch", "connect", "click", "type", "screenshot", "close"],
            },
            "session_id": {"type": "string"},
        },
    },
    "terminal_3270": {
        "type": "object",
        "required": ["host"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 23},
            "action": {"type": "string", "default": "query"},
        },
    },
    "appium_mobile": {
        "type": "object",
        "required": ["platform", "app_package", "operation"],
        "properties": {
            "platform": {"type": "string", "enum": ["android", "ios"]},
            "app_package": {"type": "string"},
            "operation": {"type": "string"},
        },
    },
    "email_driven": {
        "type": "object",
        "required": [],
        "properties": {
            "mailbox": {"type": "string", "default": "INBOX"},
            "subject_filter": {"type": "string"},
            "extract": {"type": "string", "default": "body_table"},
        },
    },
    "keystroke_replay": {
        "type": "object",
        "required": ["script_name"],
        "properties": {"script_name": {"type": "string"}},
    },
}

#: Top-level route manifest keys for completion in ``route.toml`` / ``*.dsl.yaml``.
ROUTE_COMPLETIONS: tuple[tuple[str, str], ...] = (
    ("from", "Источник route (HTTP/Email/MQ/CDC/Webhook/Stream/...)"),
    ("steps", "Массив step-операций, выполняемых последовательно"),
    ("to", "Терминал route (response/sink/MQ/...) — финальная остановка"),
    ("on_error", "Глобальный обработчик ошибок: dlq | retry | fail | warn"),
    ("policy", "Idempotency/rate-limit/circuit-breaker для всего route"),
    ("schedule", "Cron / interval для scheduled-route"),
    ("requires_core", "SemVer-ограничение ядра"),
    ("requires_plugins", "Список плагинов с SemVer"),
    ("capabilities", "Список capabilities (V11) — db.read/net.outbound/..."),
    ("tenant_aware", "Bool — учитывать tenant-контекст"),
    ("feature_flag", "Имя feature_flag для default-OFF включения"),
    ("slo", "Service Level Objective: latency_p95_ms, error_budget_pct"),
)


def _step_detail(step: str, capabilities: dict[str, str]) -> str:
    """Человекочитаемое описание YAML-шага для LSP-completion.

    Args:
        step: Имя YAML-шага.
        capabilities: Карта ``шаг → capability``.

    Returns:
        Описание шага (для ``detail`` LSP-item'а).

    """
    capability = capabilities.get(step)
    if capability:
        return f"YAML-шаг RouteBuilder.{step} (capability: {capability})"
    return f"YAML-шаг RouteBuilder.{step}"


def _step_snippet(step: str, schema: dict[str, Any] | None) -> str:
    """Сгенерировать ``insert_text`` YAML-шага по его JSON-Schema.

    Args:
        step: Имя YAML-шага.
        schema: JSON-Schema параметров шага (может быть ``None``).

    Returns:
        YAML-snippet с tab-stop'ами (``${N:...}``).

    """
    properties = (schema or {}).get("properties") or {}
    lines = [f"{step}:"]
    for index, (name, spec) in enumerate(properties.items(), start=1):
        default = spec.get("default") if isinstance(spec, dict) else None
        placeholder = (
            f"${{{index}:{default}}}" if default is not None else f"${{{index}:{name}}}"
        )
        lines.append(f"  {name}: {placeholder}")
    return "\n".join(lines) if len(lines) > 1 else f"{step}:"


def _build_step_completions() -> tuple[tuple[str, str, str], ...]:
    """Собрать полный список LSP-completion из каталога YAML-шагов.

    ADR-0399: источник истины — каталог
    :mod:`src.backend.dsl.builders.step_catalog` (все публичные методы
    ``RouteBuilder``). Curated-описания и snippet'ы из
    :data:`_STATIC_STEP_COMPLETIONS` сохраняются; остальные шаги
    генерируются автоматически.

    Returns:
        Кортеж ``(label, detail, insert_text)`` для каждого YAML-шага.

    """
    try:
        from src.backend.dsl.builders.step_catalog import (
            builder_step_names,
            step_capability_map,
            step_schema_map,
        )
    except ImportError:  # pragma: no cover — каталог недоступен → fallback
        return _STATIC_STEP_COMPLETIONS

    steps = builder_step_names()
    schemas = step_schema_map()
    capabilities = step_capability_map()

    completions: list[tuple[str, str, str]] = [
        (label, detail, snippet)
        for label, detail, snippet in _STATIC_STEP_COMPLETIONS
        if label in steps
    ]
    known = {label for label, *_ in completions}
    for step in steps:
        if step in known:
            continue
        completions.append(
            (
                step,
                _step_detail(step, capabilities),
                _step_snippet(step, schemas.get(step)),
            )
        )
    return tuple(completions)


#: Полный список step-комплишенов (каталог YAML-шагов, ADR-0399).
STEP_COMPLETIONS: tuple[tuple[str, str, str], ...] = _build_step_completions()


def get_step_snippet(step_type: str) -> dict[str, object] | None:
    """Return the JSON-Schema skeleton for a given step type.

    Args:
        step_type: One of the known step type keywords
            (e.g. ``"proxy"``, ``"call_function"``, ``"crud_create"``).

    Returns:
        JSON-Schema dict for the step type, or ``None`` if unknown.
    """
    snippet = STEP_SCHEMA_SNIPPETS.get(step_type)
    if snippet is not None:
        return snippet
    # ADR-0399: curated-схемы не покрывают все шаги — добираем из каталога.
    try:
        from src.backend.dsl.builders.step_catalog import step_schema_map
    except ImportError:  # pragma: no cover — каталог недоступен
        return None
    return step_schema_map().get(step_type)
