# DSL Write-Back (W25.2)

Bidirectional Python ↔ YAML для DSL-маршрутов: сериализация Pipeline'а
из ``RouteRegistry`` обратно в YAML-файлы. Используется для миграции
legacy кода в YAML и UI-редактора.

## Компоненты

| Слой | Файл | Назначение |
|---|---|---|
| Core | `src/dsl/engine/pipeline.py` (`to_dict`/`to_yaml`) | сериализация Pipeline |
| Core | `src/dsl/engine/processors/base.py::BaseProcessor.to_spec()` | базовый контракт processor → dict |
| Core | `src/dsl/yaml_store.py::YAMLStore` | save/load/diff на диск |
| Service | `src/services/dsl/builder_service.py::DSLBuilderService` | фасад с env-guard |
| CLI | `manage.py dsl write-yaml` | dev-CLI для write-back |
| UI | `src/entrypoints/streamlit_app/pages/32_DSL_Builder.py` | Streamlit-страница |

## Использование

### CLI (dev-only)

```bash
# preview без записи
uv run python manage.py dsl write-yaml my.route_id --diff --dry-run

# фактическая запись (только в development)
uv run python manage.py dsl write-yaml my.route_id --output dsl_routes/
```

CLI выходит с кодом 2, если `APP_ENVIRONMENT != "development"` и не
указан `--dry-run`.

### Streamlit page

`/32_DSL_Builder` — выбор route_id → preview YAML/diff → кнопка Save
(видна только в development).

### Программно (services-слой)

```python
from src.services.dsl.builder_service import get_dsl_builder_service

svc = get_dsl_builder_service()
result = svc.save_route("orders.create", dry_run=True)
print(result.diff)  # unified-diff с YAMLStore
print(result.written, result.reason)
```

## Контракт `to_spec()`

Каждый процессор может реализовать ``to_spec() -> dict | None``:

```python
class LogProcessor(BaseProcessor):
    def to_spec(self) -> dict[str, Any] | None:
        return {"log": {"level": self._level}}
```

- ключ внешнего dict'а — **имя метода RouteBuilder**;
- значение — kwargs этого метода (примитивы, dict, list);
- ``None`` — процессор не сериализуется (callable/тип в args, sub-pipelines, etc.).

Pipeline.to_dict пропускает процессоры, у которых ``to_spec()`` возвращает ``None``.

## Текущее покрытие (W25.2 baseline)

Реализовано в этой волне (примитивно-параметризованные процессоры):

| Builder method | Processor | Файл |
|---|---|---|
| `set_header` | SetHeaderProcessor | `processors/core.py` |
| `set_property` | SetPropertyProcessor | `processors/core.py` |
| `log` | LogProcessor | `processors/core.py` |
| `transform` | TransformProcessor | `processors/core.py` |
| `dispatch_action` | DispatchActionProcessor (без payload_factory) | `processors/core.py` |
| `enrich` | EnrichProcessor (без payload_factory) | `processors/core.py` |
| `throttle` | ThrottlerProcessor | `processors/eip/flow_control.py` |
| `delay` | DelayProcessor (без scheduled_time_fn) | `processors/eip/flow_control.py` |

Уже было реализовано до W25 (~28 процессоров): Audit / Notify / Invoke /
Entity CRUD / Telegram / Express / WindowedDedup / MulticastRoutes /
Redirect и пр.

### W27 — AI primitive-args batch

| Builder method | Processor | Файл |
|---|---|---|
| `sanitize_pii` | SanitizePIIProcessor | `processors/ai.py` |
| `rag_search` | VectorSearchProcessor | `processors/ai.py` |
| `compose_prompt` | PromptComposerProcessor | `processors/ai.py` |
| `call_llm` | LLMCallProcessor | `processors/ai.py` |

### W28 — enrichment + business batch

12 новых builder-методов + to_spec:

| Builder method | Processor | Файл |
|---|---|---|
| `geoip` | GeoIpProcessor | `processors/enrichment.py` |
| `jwt_sign` | JwtSignProcessor | `processors/enrichment.py` |
| `jwt_verify` | JwtVerifyProcessor | `processors/enrichment.py` |
| `compress` | CompressProcessor | `processors/enrichment.py` |
| `decompress` | DecompressProcessor | `processors/enrichment.py` |
| `webhook_sign` | WebhookSignProcessor | `processors/enrichment.py` |
| `deadline` | DeadlineProcessor | `processors/enrichment.py` |
| `tenant_scope` | TenantScopeProcessor | `processors/business.py` |
| `cost_tracker` | CostTrackerProcessor | `processors/business.py` |
| `outbox` | OutboxProcessor (без custom writer) | `processors/business.py` |
| `mask` | DataMaskingProcessor | `processors/business.py` |
| `compliance_labels` | ComplianceLabelProcessor | `processors/business.py` |

`HumanApprovalProcessor` пропущен (DI ``approval_store`` + callable
``notifier`` не сериализуются).

**Безопасность секретов**: `jwt_sign` / `jwt_verify` / `webhook_sign`
сохраняют ``secret_key`` / ``secret`` как literal в YAML. Для production
используйте SecretRef-маркеры (см. ``to_spec_audit.md``).

### W29 — ai_banking AI pipelines

7 процессоров AI-pipelines для banking-домена; builder-методы уже
существовали — добавлен только ``to_spec()``:

| Builder method | Processor | Файл |
|---|---|---|
| `kyc_aml_verify` | KycAmlVerifyProcessor | `processors/ai_banking.py` |
| `antifraud_score` | AntiFraudScoreProcessor | `processors/ai_banking.py` |
| `credit_scoring_rag` | CreditScoringRagProcessor | `processors/ai_banking.py` |
| `customer_chatbot` | CustomerChatbotProcessor | `processors/ai_banking.py` |
| `appeal_ai` | AppealProcessorAI | `processors/ai_banking.py` |
| `tx_categorize` | TransactionCategorizerProcessor | `processors/ai_banking.py` |
| `findoc_ocr_llm` | FinDocOcrLlmProcessor | `processors/ai_banking.py` |

### W30 — RPA batch (UiPath-style + RPA terminal/desktop/mobile)

21 процессор; builder-методы уже существовали — добавлен только
`to_spec()`.

`rpa.py` (16):

| Builder method | Processor |
|---|---|
| `pdf_read` | PdfReadProcessor |
| `pdf_merge` | PdfMergeProcessor |
| `word_read` | WordReadProcessor |
| `word_write` | WordWriteProcessor |
| `excel_read` | ExcelReadProcessor |
| `file_move` | FileMoveProcessor |
| `archive` | ArchiveProcessor |
| `ocr` | ImageOcrProcessor |
| `image_resize` | ImageResizeProcessor |
| `regex` | RegexProcessor |
| `render_template` | TemplateRenderProcessor |
| `hash` | HashProcessor |
| `encrypt` | EncryptProcessor |
| `decrypt` | DecryptProcessor |
| `shell` | ShellExecProcessor |
| `email` | EmailComposeProcessor |

`rpa_banking.py` (5):

| Builder method | Processor |
|---|---|
| `citrix` | CitrixSessionProcessor |
| `terminal_3270` | TerminalEmulator3270Processor |
| `appium_mobile` | AppiumMobileProcessor |
| `email_driven` | EmailDrivenProcessor |
| `keystroke_replay` | KeystrokeReplayProcessor |

Особенности W30:

- `ShellExecProcessor.allowed_commands` хранится как `set` —
  `to_spec` отдаёт `sorted(list(...))` для детерминизма round-trip'а.
- `ShellExecProcessor.timeout_seconds` не экспонируется через
  builder и теряется при write-back.
- `ImageResizeProcessor.output_format` нормализуется к UPPERCASE
  (`Pillow` API), поэтому `output_format="jpeg"` становится `"JPEG"`
  после первого round-trip'а — идемпотентно.
- `encrypt` / `decrypt` / `email` / `webhook_sign` — **literal
  secret в YAML**: для production используйте SecretRef-маркеры
  (см. `to_spec_audit.md`).

### post-W30 cleanup — удаление специализированных интеграций

Удалены 8 процессоров и 8 builder-методов:

- `processors/banking.py` (файл удалён целиком, 6 классов): SWIFT MT/MX
  parse-builder, ISO 20022 parser, FIX message, EDIFACT parser, 1С
  exchange.
- `processors/rpa_banking.py` — 2 класса: SAP GUI Scripting, bank
  statement PDF parser (Сбер/ВТБ/Альфа форматы).

Builder-методы удалены: `swift_mt_parse`, `swift_mx_build`,
`iso20022_parse`, `fix_message`, `edifact_parse`, `onec_exchange`,
`sap_gui`, `bank_statement_pdf`.

Специализированные финансовые протоколы (SWIFT / ISO 20022 / FIX /
EDIFACT), интеграции с проприетарными ERP/CRM (1С / SAP) и форматами
банк-выписок маршрутизируются через корпоративную интеграционную
шину предприятия — не из этого сервиса.

Контракт W27: `to_spec` сохраняет только те kwargs, что приняты
builder-методом (см. `to_spec_audit.md`). Не-builder параметры
(`output_property` для rag/prompt, `prompt_property` / `max_retries`
/ `retry_delay` для LLM) при write-back теряются — by design.

Пример round-trip RAG-цепочки:

```yaml
processors:
  - sanitize_pii: {}
  - rag_search: {namespace: kb_main, top_k: 3}
  - compose_prompt:
      template: "Контекст:\n{context}\n\nВопрос: {input}"
  - call_llm: {provider: perplexity}
```

## Ограничения

1. **Callable-аргументы**: процессоры с ``payload_factory``,
   ``predicate``, ``correlation_key`` и т.п. сериализуются как
   ``None`` (молча). Их нужно описывать YAML'ом изначально или
   рефакторить под expression-форму (JMESPath / template).

2. **Type-аргументы**: ``ValidateProcessor(model=OrderSchemaIn)`` пока
   не сериализуется — model нужно резолвить через registry. Будет в
   следующих волнах через ``schema: OrderSchemaIn`` (символьный ref).

3. **Sub-processors**: реализованы в W26.1 для пяти control-flow
   процессоров — Retry / TryCatch / Parallel / Saga / Choice. Choice
   поддерживает только JMESPath-форму (``expr``); legacy callable
   predicate возвращает ``None`` и пропускается при write-back.
   Splitter / Aggregator / Loop / OnCompletion остаются open и
   запланированы в более поздних волнах.

   Пример nested-YAML для control-flow:

   ```yaml
   processors:
     - retry:
         max_attempts: 3
         delay_seconds: 1.0
         backoff: exponential
         processors:
           - log: {level: info}
           - dispatch_action: {action: orders.create}
     - do_try:
         try_processors:
           - transform: {expression: body}
         catch_processors:
           - log: {level: error}
         finally_processors:
           - set_header: {key: x-finalized, value: "1"}
     - parallel:
         strategy: all
         branches:
           left:
             - log: {level: info}
           right:
             - dispatch_action: {action: notify.user}
     - saga:
         steps:
           - forward: {dispatch_action: {action: orders.reserve}}
             compensate: {dispatch_action: {action: orders.cancel}}
     - choice:
         when:
           - expr: "status == 'ok'"
             processors:
               - dispatch_action: {action: orders.complete}
         otherwise:
           - log: {level: warning}
   ```

4. **Write-back только в development**: env-guard в
   ``DSLBuilderService.is_write_enabled``. Production использует
   read-only YAMLStore + ImportGateway / API endpoints.

## Полный аудит to_spec coverage

См. `docs/reference/dsl/to_spec_audit.md` (генерируется
``tools/audit_to_spec.py``).
