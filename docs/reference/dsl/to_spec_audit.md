# DSL Processors — `to_spec()` audit (post-W30 cleanup)

Снимок покрытия после W30 + удаление специализированных финансовых
протоколов. Цель — сделать round-trip ``RouteBuilder → YAML →
RouteBuilder`` возможным для всё большего числа процессоров.

| Категория | Покрытие |
|---|---|
| Всего процессоров | **178** (8 удалено) |
| C `to_spec()` | **85** |
| Без `to_spec()` | **93** |

## Удалено в post-W30 cleanup

Файл `processors/banking.py` удалён целиком (6 классов):
SwiftMTParser / SwiftMXBuilder / Iso20022Parser / FixMessage /
EdifactParser / OneCExchange. Из `processors/rpa_banking.py` удалены:
SapGuiProcessor / BankStatementPdfParserProcessor.

Соответствующие builder-методы удалены: `swift_mt_parse`,
`swift_mx_build`, `iso20022_parse`, `fix_message`, `edifact_parse`,
`onec_exchange`, `sap_gui`, `bank_statement_pdf`.

Причина: специализированные финансовые протоколы (SWIFT MT/MX,
ISO 20022, FIX, EDIFACT) и интеграции с проприетарными ERP/CRM (1С,
SAP) и форматами PDF-выписок (Сбер/ВТБ/Альфа) маршрутизируются через
корпоративную интеграционную шину предприятия.

`to_spec()` возвращает ``dict | None`` по контракту:
- ключ внешнего dict'а = имя метода RouteBuilder;
- значение = kwargs этого метода;
- ``None`` — для процессоров с callable / type-аргументами либо
  sub-processors (см. write_back.md).

## Принцип W25.2

Не блокировать write-back на отсутствие `to_spec()`. `Pipeline.to_dict`
молча пропускает процессоры, у которых `to_spec()` возвращает `None`.
Это позволяет делать частичный round-trip уже сейчас, при том что
полное покрытие — итерационная работа в последующих волнах.

## Категории работ

1. **Easy-wins** — примитивные параметры (str/int/bool/dict/list). Сделано в W25.2: SetHeader, SetProperty, Log, Transform, DispatchAction, Enrich, Throttle, Delay.
2. **Sub-processors** — Choice/Retry/Saga/Splitter/Aggregator/Loop/OnCompletion/Parallel. Требуется рекурсивный `to_spec()` на children + поддержка nested-format в `yaml_loader._apply_processor`. Отложено как long-tail.
3. **Type/Schema args** — Validate/SchemaValidate. Требуется symbolic registry для Pydantic-моделей, чтобы spec ссылался на имя (``schema: OrderSchemaIn``).
4. **Callable args** — Filter/Aggregate/Loop. Альтернатива: переход на JMESPath-выражения вместо Python-callables.

## Per-file inventory

### ai.py
- [   ] CacheProcessor (callable key_fn)
- [   ] CacheWriteProcessor (callable key_fn)
- [   ] GetFeedbackExamplesProcessor
- [   ] GuardrailsProcessor
- [✓] LLMCallProcessor (W27; provider/model only — non-builder kwargs lost)
- [   ] LLMFallbackProcessor
- [   ] LLMParserProcessor (type-arg, требует registry)
- [✓] PromptComposerProcessor (W27; template/context_property)
- [   ] RestorePIIProcessor
- [✓] SanitizePIIProcessor (W27)
- [   ] SemanticRouterProcessor
- [   ] TokenBudgetProcessor
- [✓] VectorSearchProcessor (W27; query_field/top_k/namespace — output_property lost)

### ai_banking.py
- [✓] AntiFraudScoreProcessor (W29; model)
- [✓] AppealProcessorAI (W29)
- [✓] CreditScoringRagProcessor (W29; product)
- [✓] CustomerChatbotProcessor (W29; channel)
- [✓] FinDocOcrLlmProcessor (W29; doc_type)
- [✓] KycAmlVerifyProcessor (W29; jurisdiction)
- [✓] TransactionCategorizerProcessor (W29; taxonomy)

### audit.py
- [✓] AuditProcessor

### banking.py — _удалён целиком в post-W30 cleanup_

### business.py
- [✓] ComplianceLabelProcessor (W28; labels)
- [✓] CostTrackerProcessor (W28)
- [✓] DataMaskingProcessor (W28; patterns/replacement; default-set не пишется)
- [   ] HumanApprovalProcessor (DI store + callable notifier)
- [✓] OutboxProcessor (W28; topic only — custom outbox_writer → None)
- [✓] TenantScopeProcessor (W28; header/body_path/required)

### components.py
- [   ] (8 классов — детали см. через скрипт audit)

### control_flow.py
- [✓] ChoiceProcessor (W26.1; JMESPath-форма; legacy callable predicate → None)
- [✓] ParallelProcessor (W26.1)
- [   ] PipelineRefProcessor
- [✓] RetryProcessor (W26.1)
- [✓] SagaProcessor (W26.1)
- [✓] TryCatchProcessor (W26.1)

### converters.py
- [   ] (несколько классов конверсий)

### core.py
- [✓] DispatchActionProcessor (W25.2; payload_factory=None)
- [✓] EnrichProcessor (W25.2; payload_factory=None)
- [   ] FilterProcessor (callable predicate)
- [✓] LogProcessor (W25.2)
- [✓] SetHeaderProcessor (W25.2)
- [✓] SetPropertyProcessor (W25.2)
- [✓] TransformProcessor (W25.2)
- [   ] ValidateProcessor (type-arg, требует registry)

### dq_check.py
- [   ] DQCheckProcessor

### eip/flow_control.py
- [   ] AggregatorProcessor (callable correlation_key)
- [✓] DelayProcessor (W25.2; scheduled_time_fn=None)
- [   ] LoopProcessor (sub-processors)
- [   ] OnCompletionProcessor (sub-processors)
- [✓] ThrottlerProcessor (W25.2)
- [   ] WireTapProcessor (sub-processors)

### eip/idempotency.py
- [   ] IdempotentConsumerProcessor

### eip/resilience.py
- [   ] DeadLetterProcessor (sub-processors)
- [   ] FallbackChainProcessor (sub-processors)

### eip/routing.py
- [   ] DynamicRouterProcessor
- [✓] MulticastRoutesProcessor
- [   ] RecipientListProcessor
- [   ] ScatterGatherProcessor

### eip/sequencing.py
- [   ] (классы упорядочивания)

### eip/transformation.py
- [   ] MessageTranslatorProcessor
- [   ] SplitterProcessor (sub-processors)

### eip/windowed_dedup.py
- [✓] WindowedCollectProcessor
- [✓] WindowedDedupProcessor

### entity.py (CRUD-семейство)
- [✓] EntityCreateProcessor
- [✓] EntityDeleteProcessor
- [✓] EntityGetProcessor
- [✓] EntityListProcessor
- [✓] EntityUpdateProcessor

### enrichment.py
- [✓] CompressProcessor (W28; algorithm/level)
- [✓] DecompressProcessor (W28; algorithm)
- [✓] DeadlineProcessor (W28; timeout_seconds/fail_on_exceed)
- [✓] GeoIpProcessor (W28; ip_field/ip_header/output_property)
- [✓] JwtSignProcessor (W28; secret_key/algorithm/expires_in_seconds/output_property)
- [✓] JwtVerifyProcessor (W28; secret_key/algorithm/header/output_property)
- [✓] WebhookSignProcessor (W28; secret/header/algorithm)

### export.py / external.py / generic.py
- [   ] большинство — без to_spec

### express/
- [✓] ExpressEditProcessor
- [✓] ExpressMentionProcessor
- [✓] ExpressReplyProcessor
- [✓] ExpressSendFileProcessor
- [✓] ExpressSendProcessor
- [✓] ExpressStatusProcessor
- [✓] ExpressTypingProcessor

### invoke.py
- [✓] InvokeProcessor

### notify.py
- [✓] NotifyProcessor

### proxy/redirect.py
- [✓] RedirectProcessor

### rpa.py
- [✓] ArchiveProcessor (W30; mode/format)
- [✓] DecryptProcessor (W30; key)
- [✓] EmailComposeProcessor (W30; to/subject/body_template)
- [✓] EncryptProcessor (W30; key)
- [✓] ExcelReadProcessor (W30; sheet_name)
- [✓] FileMoveProcessor (W30; src/dst/mode)
- [✓] HashProcessor (W30; algorithm)
- [✓] ImageOcrProcessor (W30; lang)
- [✓] ImageResizeProcessor (W30; width/height/output_format)
- [✓] PdfMergeProcessor (W30)
- [✓] PdfReadProcessor (W30; extract_tables)
- [✓] RegexProcessor (W30; pattern/action/replacement)
- [✓] ShellExecProcessor (W30; command/args/allowed_commands; timeout_seconds потерян)
- [✓] TemplateRenderProcessor (W30; template)
- [✓] WordReadProcessor (W30)
- [✓] WordWriteProcessor (W30)

### rpa_banking.py
- [✓] AppiumMobileProcessor (W30; platform/app_package/operation)
- [✓] CitrixSessionProcessor (W30; operation/session_id)
- [✓] EmailDrivenProcessor (W30; mailbox/subject_filter/extract)
- [✓] KeystrokeReplayProcessor (W30; script_name)
- [✓] TerminalEmulator3270Processor (W30; host/port/action)

Специализированные интеграции (банковские протоколы / ERP / CRM /
госинтеграции) не реализуются в этом сервисе — они маршрутизируются
через корпоративную интеграционную шину предприятия.

### scan_file.py
- [✓] ScanFileProcessor

### security.py
- [✓] AuthValidateProcessor

### telegram/
- [✓] TelegramEditProcessor
- [✓] TelegramMentionProcessor
- [✓] TelegramReplyProcessor
- [✓] TelegramSendFileProcessor
- [✓] TelegramSendProcessor
- [✓] TelegramStatusProcessor
- [✓] TelegramTypingProcessor

## Контракт W27 для AI-процессоров

`to_spec()` для AI-процессоров сериализует только те kwargs, что
приняты публичным builder-методом (`call_llm`, `compose_prompt`,
`rag_search`, `sanitize_pii`). Это выбор в пользу round-trip через
builder API, не сохранения произвольно сконструированных Python-объектов.

Не сериализуются (теряются при write-back):
- `LLMCallProcessor`: `prompt_property`, `max_retries`, `retry_delay`.
- `PromptComposerProcessor`: `output_property`.
- `VectorSearchProcessor`: `output_property`.

Если нужен полный контроль над этими параметрами — оставайтесь в
Python-builder; YAML-форма фиксирует именно builder-API. Расширение
этих kwargs до builder-уровня — отдельный шаг (если будет реальный
запрос от пользователей).

## Контракт W28: secrets в YAML

`jwt_sign`, `jwt_verify`, `webhook_sign` сериализуют ``secret_key`` /
``secret`` как literal-строку в YAML. Это упрощает round-trip, но
небезопасно для production: YAML-snapshot маршрута попадает в git/
storage и засвечивает секрет.

Рекомендация: для production DSL-маршрутов передавайте секреты через
SecretRef-маркеры (см. ImportGateway / W24 deferred): ``${ENV_VAR}``
или ``secret://path/to/secret``. Резолюция через SecretsBackend в
runtime, в YAML остаётся только ссылка.

Формализация SecretRef-уровня для DSL — отдельный шаг (вне W28).

## Дальнейшая работа

Распределить недостающие to_spec по будущим волнам:
- W26: sub-processor framework (Choice / Retry / TryCatch / Parallel / Saga). ✅
- W27: AI processors (LLMCall / PromptCompose / VectorSearch / SanitizePII). ✅
- W28: enrichment + business — primitive-args batch + 12 builder-методов. ✅
- W29: banking + ai_banking — 13 процессоров (builder-методы уже были). ✅
  (post-W30: banking.py 6 удалены — финансовые протоколы.)
- W30: RPA — изначально 23 процессора rpa.py (16) + rpa_banking.py (7). ✅
  (post-W30: rpa_banking.py 2 удалены — sap_gui, bank_statement_pdf.)
- W31 candidates: components.py / converters.py / generic / external /
  eip/sequencing / eip/idempotency / dq_check / export.

Скрипт инвентаризации — `tools/audit_to_spec.py` (TBD). Сейчас аудит
сделан вручную через AST-обход; цифры в шапке актуальны на дату
W25.2 baseline.
