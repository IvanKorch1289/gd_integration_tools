"""YAML schema completion provider for DSL LSP (Wave s19/k3-w4-lsp-server-finale).

Provides:
* ``STEP_COMPLETIONS`` — CompletionList of step type keywords with
  JSON-Schema validation snippets for each step type.
* ``ROUTE_COMPLETIONS`` — top-level route manifest keys.
* ``get_step_snippet()`` — returns the JSON-Schema skeleton for a given step type.

Used by :mod:`src.backend.dsl.cli.lsp_server` to populate ``textDocument/completion``
responses.
"""

from __future__ import annotations

__all__ = (
    "STEP_COMPLETIONS",
    "ROUTE_COMPLETIONS",
    "get_step_snippet",
    "STEP_SCHEMA_SNIPPETS",
)


#: Step type keywords for the ``steps[]`` array in ``*.dsl.yaml``.
#: Each entry: (label, detail, insert_text_snippet).
#: The insert_text includes YAML indentation anchors (``${N}`` are tab-stops).
STEP_COMPLETIONS: tuple[tuple[str, str, str], ...] = (
    (
        "proxy",
        "Прокси-запрос на upstream без бизнес-логики",
        "proxy:\n  src: ${1:/src/path}\n  dst: ${2:http://target:port}",
    ),
    (
        "redirect",
        "HTTP-redirect 30x на target URL",
        "redirect:\n  url: ${1:https://target.example.com}\n  code: ${2:302}",
    ),
    (
        "call_function",
        "Вызов Python-функции 'module:fn' через whitelist",
        "call_function:\n  ref: ${1:extensions.my_plugin:my_function}\n  args:\n    ${2:key}: ${3:value}",
    ),
    (
        "dispatch_action",
        "Service Activator — диспетчер action в sync/async/bg/api/sse/ws",
        "dispatch_action:\n  name: ${1:my.action.name}\n  mode: ${2:sync}",
    ),
    (
        "transform",
        "JMESPath/JSONata/JSONLogic трансформация body/header",
        "transform:\n  set:\n    ${1:body.field}: ${2:'${expression}'}",
    ),
    (
        "choice",
        "EIP Content-Based Router — when/otherwise ветвление",
        "choice:\n  when:\n    - condition: ${1:body.status == 'active'}\n      steps:\n        - ${2:proxy:}",
    ),
    (
        "parallel",
        "EIP Scatter-Gather — параллельное выполнение branches",
        "parallel:\n  branches:\n    - steps:\n        - ${1:proxy:}",
    ),
    (
        "try_catch",
        "Try-catch с компенсацией / DLQ-handoff",
        "try_catch:\n  try:\n    steps:\n      - ${1:proxy:}\n  catch:\n    steps:\n      - ${2:audit:}",
    ),
    (
        "saga",
        "Saga-step (Temporal compensation)",
        "saga:\n  steps:\n    - ${1:call_function:}\n  compensate:\n    - ${2:call_function:}",
    ),
    (
        "invoke_workflow",
        "Temporal/Lite workflow invocation",
        "invoke_workflow:\n  workflow: ${1:my_workflow}\n  args:\n    ${2:key}: ${3:value}",
    ),
    (
        "crud_create",
        "CRUD create entity через repository",
        "crud_create:\n  entity: ${1:orders}\n  body: ${2:${body}}",
    ),
    (
        "crud_read",
        "CRUD read by id или filter",
        "crud_read:\n  entity: ${1:orders}\n  filter:\n    id: ${2:123}",
    ),
    (
        "crud_update",
        "CRUD update by id",
        "crud_update:\n  entity: ${1:orders}\n  id: ${2:123}\n  body: ${3:${body}}",
    ),
    (
        "crud_delete",
        "CRUD delete by id",
        "crud_delete:\n  entity: ${1:orders}\n  id: ${2:123}",
    ),
    (
        "publish_event",
        "Publish в MQ (Kafka/RabbitMQ/NATS/Redis Streams)",
        "publish_event:\n  topic: ${1:my.topic}\n  payload: ${2:${body}}",
    ),
    (
        "notify_cascade",
        "Email/SMS/Telegram cascade notification",
        "notify_cascade:\n  channel: ${1:email}\n  to: ${2:user@example.com}\n  template: ${3:my_template}",
    ),
    (
        "audit",
        "Audit-event в audit-trail",
        "audit:\n  event: ${1:route.my_route.call}\n  metadata:\n    ${2:key}: ${3:value}",
    ),
    (
        "validate_response",
        "Pydantic-валидация response от внешнего API",
        "validate_response:\n  schema: ${1:MyResponseSchema}\n  on_error: ${2:dlq}",
    ),
    (
        "db_query_external",
        "SELECT в внешней БД через capability db.read",
        "db_query_external:\n  query: ${1:SELECT * FROM orders WHERE status = $1}\n  params:\n    - ${2:'active'}",
    ),
    (
        "db_call_procedure",
        "Вызов хранимой процедуры через capability",
        "db_call_procedure:\n  procedure: ${1:my_proc}\n  params:\n    - ${2:value}",
    ),
    (
        "get_setting",
        "Прочитать конфиг по path → body.x",
        "get_setting:\n  path: ${1:my.setting.path}\n  to: ${2:body.setting}",
    ),
    (
        "sink_publish",
        "Публикация в sink (S3/Kafka/WebDAV/...)",
        "sink_publish:\n  sink: ${1:s3://bucket/path}\n  content: ${2:${body}}",
    ),
    (
        "validate_request",
        "Валидация входящего request по JSON-Schema",
        "validate_request:\n  schema:\n    type: object\n    properties:\n      ${1:field}: { type: ${2:string} }\n    required:\n      - ${1:field}",
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
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "Redirect target URL"},
            "code": {
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
            "args": {"type": "object", "description": "Keyword arguments to pass"},
        },
    },
    "dispatch_action": {
        "type": "object",
        "required": ["name", "mode"],
        "properties": {
            "name": {"type": "string", "description": "Action name"},
            "mode": {
                "type": "string",
                "enum": ["sync", "async", "bg", "api", "sse", "ws"],
            },
        },
    },
    "transform": {
        "type": "object",
        "required": ["set"],
        "properties": {
            "set": {"type": "object", "description": "JMESPath/JSONata assignments"}
        },
    },
    "choice": {
        "type": "object",
        "required": ["when"],
        "properties": {
            "when": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string"},
                        "steps": {"type": "array"},
                    },
                },
            }
        },
    },
    "parallel": {
        "type": "object",
        "required": ["branches"],
        "properties": {
            "branches": {
                "type": "array",
                "items": {"type": "object", "properties": {"steps": {"type": "array"}}},
            }
        },
    },
    "try_catch": {
        "type": "object",
        "required": ["try", "catch"],
        "properties": {
            "try": {"type": "object", "properties": {"steps": {"type": "array"}}},
            "catch": {"type": "object", "properties": {"steps": {"type": "array"}}},
        },
    },
    "saga": {
        "type": "object",
        "required": ["steps", "compensate"],
        "properties": {"steps": {"type": "array"}, "compensate": {"type": "array"}},
    },
    "invoke_workflow": {
        "type": "object",
        "required": ["workflow"],
        "properties": {"workflow": {"type": "string"}, "args": {"type": "object"}},
    },
    "crud_create": {
        "type": "object",
        "required": ["entity", "body"],
        "properties": {"entity": {"type": "string"}, "body": {"type": "object"}},
    },
    "crud_read": {
        "type": "object",
        "required": ["entity"],
        "properties": {"entity": {"type": "string"}, "filter": {"type": "object"}},
    },
    "crud_update": {
        "type": "object",
        "required": ["entity", "id", "body"],
        "properties": {
            "entity": {"type": "string"},
            "id": {"type": ["string", "integer"]},
            "body": {"type": "object"},
        },
    },
    "crud_delete": {
        "type": "object",
        "required": ["entity", "id"],
        "properties": {
            "entity": {"type": "string"},
            "id": {"type": ["string", "integer"]},
        },
    },
    "publish_event": {
        "type": "object",
        "required": ["topic", "payload"],
        "properties": {"topic": {"type": "string"}, "payload": {"type": "object"}},
    },
    "notify_cascade": {
        "type": "object",
        "required": ["channel", "to", "template"],
        "properties": {
            "channel": {"type": "string", "enum": ["email", "sms", "telegram"]},
            "to": {"type": "string"},
            "template": {"type": "string"},
        },
    },
    "audit": {
        "type": "object",
        "required": ["event"],
        "properties": {"event": {"type": "string"}, "metadata": {"type": "object"}},
    },
    "validate_response": {
        "type": "object",
        "required": ["schema"],
        "properties": {
            "schema": {"type": "string"},
            "on_error": {"type": "string", "enum": ["dlq", "retry", "fail", "warn"]},
        },
    },
    "db_query_external": {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}, "params": {"type": "array"}},
    },
    "db_call_procedure": {
        "type": "object",
        "required": ["procedure"],
        "properties": {"procedure": {"type": "string"}, "params": {"type": "array"}},
    },
    "get_setting": {
        "type": "object",
        "required": ["path", "to"],
        "properties": {"path": {"type": "string"}, "to": {"type": "string"}},
    },
    "sink_publish": {
        "type": "object",
        "required": ["sink", "content"],
        "properties": {"sink": {"type": "string"}, "content": {"type": "object"}},
    },
    "validate_request": {
        "type": "object",
        "required": ["schema"],
        "properties": {
            "schema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "properties": {"type": "object"},
                    "required": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
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


def get_step_snippet(step_type: str) -> dict[str, object] | None:
    """Return the JSON-Schema skeleton for a given step type.

    Args:
        step_type: One of the known step type keywords
            (e.g. ``"proxy"``, ``"call_function"``, ``"crud_create"``).

    Returns:
        JSON-Schema dict for the step type, or ``None`` if unknown.
    """
    return STEP_SCHEMA_SNIPPETS.get(step_type)
