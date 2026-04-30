# DSL Processors — `to_spec()` audit (W25.2 baseline)

Снимок покрытия после W25.2. Цель — сделать round-trip
``RouteBuilder → YAML → RouteBuilder`` возможным для всё большего
числа процессоров.

| Категория | Покрытие |
|---|---|
| Всего процессоров | **186** |
| C `to_spec()` | **36** |
| Без `to_spec()` | **150** |

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
- [   ] CacheProcessor
- [   ] CacheWriteProcessor
- [   ] GetFeedbackExamplesProcessor
- [   ] GuardrailsProcessor
- [   ] LLMCallProcessor
- [   ] LLMFallbackProcessor
- [   ] LLMParserProcessor
- [   ] PromptComposerProcessor
- [   ] RestorePIIProcessor
- [   ] SanitizePIIProcessor
- [   ] SemanticRouterProcessor
- [   ] TokenBudgetProcessor
- [   ] VectorSearchProcessor

### ai_banking.py
- [   ] AntiFraudScoreProcessor
- [   ] CreditScoringRagProcessor
- [   ] CustomerChatbotProcessor
- [   ] FinDocOcrLlmProcessor
- [   ] KycAmlVerifyProcessor
- [   ] TransactionCategorizerProcessor

### audit.py
- [✓] AuditProcessor

### banking.py
- [   ] EdifactParserProcessor
- [   ] FixMessageProcessor
- [   ] Iso20022ParserProcessor
- [   ] OneCExchangeProcessor
- [   ] SwiftMTParserProcessor
- [   ] SwiftMXBuilderProcessor

### business.py
- [   ] ComplianceLabelProcessor
- [   ] CostTrackerProcessor
- [   ] DataMaskingProcessor
- [   ] HumanApprovalProcessor
- [   ] OutboxProcessor
- [   ] TenantScopeProcessor

### components.py
- [   ] (8 классов — детали см. через скрипт audit)

### control_flow.py
- [   ] ChoiceProcessor (sub-processors)
- [   ] ParallelProcessor (sub-processors)
- [   ] PipelineRefProcessor
- [   ] RetryProcessor (sub-processors)
- [   ] SagaProcessor (sub-processors)
- [   ] TryCatchProcessor (sub-processors)

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
- [   ] CompressProcessor / DecompressProcessor / DeadlineProcessor / GeoIpProcessor / JwtSignProcessor / JwtVerifyProcessor / WebhookSignProcessor

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

## Дальнейшая работа

Распределить недостающие to_spec по будущим волнам:
- W26: sub-processor framework (Choice / Retry / TryCatch / Parallel / Saga).
- W27: AI processors (LLMCall / PromptCompose / VectorSearch / SanitizePII).
- W28: enrichment / banking / ai_banking / RPA — primitive-args batch.

Скрипт инвентаризации — `tools/audit_to_spec.py` (TBD). Сейчас аудит
сделан вручную через AST-обход; цифры в шапке актуальны на дату
W25.2 baseline.
