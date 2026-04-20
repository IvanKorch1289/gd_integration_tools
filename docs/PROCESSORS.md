# Каталог процессоров DSL

> Автогенерируется `tools/generate_processors_doc.py` из docstrings.

Всего процессоров: **138**

## ai

| Класс | Назначение |
|-------|------------|
| `CacheProcessor` | Redis-кеш для результатов обработки. |
| `CacheWriteProcessor` | Записывает результат в Redis-кеш после обработки. |
| `GuardrailsProcessor` | Проверяет LLM output на безопасность и соответствие ожиданиям. |
| `LLMCallProcessor` | Вызывает LLM с retry, rate-limit detection и cost tracking. |
| `LLMFallbackProcessor` | Пробует несколько LLM-провайдеров по цепочке. |
| `LLMParserProcessor` | Парсит ответ LLM в структурированный формат. |
| `PromptComposerProcessor` | Строит промпт из шаблона + контекст из exchange properties. |
| `RestorePIIProcessor` | Восстанавливает замаскированные PII из exchange properties. |
| `SanitizePIIProcessor` | Маскирует PII в body перед передачей дальше. |
| `SemanticRouterProcessor` | Маршрутизация по семантическому сходству — RAG-based intent routing. |
| `TokenBudgetProcessor` | Обрезает текст по token budget (tiktoken для точного подсчёта). |
| `VectorSearchProcessor` | Ищет в RAG vector store, результаты в exchange properties. |

## ai_banking

| Класс | Назначение |
|-------|------------|
| `AntiFraudScoreProcessor` | LLM-скоринг антифрода поверх детерминистических правил. |
| `AppealProcessorAI` | Автоматическая обработка клиентских обращений. |
| `CreditScoringRagProcessor` | Кредитный скоринг через RAG: клиент + история + policy-документы. |
| `CustomerChatbotProcessor` | Клиентский чат-бот (tool-use: balance, statement, faq, escalate). |
| `FinDocOcrLlmProcessor` | OCR + LLM для финансовых документов (счета, договоры, выписки). |
| `KycAmlVerifyProcessor` | KYC/AML верификация клиента. |
| `TransactionCategorizerProcessor` | Категоризация транзакций (MCC + subcategory + merchant normalization). |

## banking

| Класс | Назначение |
|-------|------------|
| `EdifactParserProcessor` | Парсер UN/EDIFACT сегментов (FINPAY, PAYMUL). |
| `FixMessageProcessor` | Парсер/билдер FIX-сообщений для торговых систем (биржа, брокер). |
| `Iso20022ParserProcessor` | Парсит ISO 20022 XML (pain.001, camt.053, pacs.008) в структурированный dict. |
| `OneCExchangeProcessor` | Интеграция с 1С:Предприятие через OData или HTTP-сервисы. |
| `SwiftMTParserProcessor` | Парсит SWIFT MT-сообщение (MT103, MT202, MT940) в dict-структуру. |
| `SwiftMXBuilderProcessor` | Строит SWIFT MX (ISO 20022 XML) из словаря. Делегирует в сервис через action. |

## base

| Класс | Назначение |
|-------|------------|
| `CallableProcessor` | Адаптер, превращающий обычную функцию или coroutine в процессор. |

## components

| Класс | Назначение |
|-------|------------|
| `DatabaseQueryProcessor` | Camel JDBC Component — query/execute SQL from DSL pipeline. |
| `FileReadProcessor` | Camel File Component (read) — read local file into exchange body. |
| `FileWriteProcessor` | Camel File Component (write) — write exchange body to local file. |
| `HttpCallProcessor` | Camel HTTP Component — call external APIs from DSL pipeline. |
| `PollingConsumerProcessor` | Camel Polling Consumer — periodically calls an action and feeds results into pipeline. |
| `S3ReadProcessor` | Camel S3 Component (read) — download object from S3. |
| `S3WriteProcessor` | Camel S3 Component (write) — upload exchange body to S3. |
| `TimerProcessor` | Camel Timer Component — generates exchange events on interval or cron. |

## control_flow

| Класс | Назначение |
|-------|------------|
| `ChoiceProcessor` | Условное ветвление When/Otherwise. |
| `ParallelProcessor` | Выполняет несколько веток параллельно. |
| `PipelineRefProcessor` | Вызывает другой зарегистрированный DSL-маршрут. |
| `RetryProcessor` | Повторяет sub-pipeline с настраиваемым backoff. |
| `SagaProcessor` | Saga-паттерн: выполняет шаги последовательно с откатом. |
| `TryCatchProcessor` | Try/Catch/Finally внутри DSL pipeline. |

## converters

| Класс | Назначение |
|-------|------------|
| `ConvertProcessor` | Universal format converter — Camel TypeConverter pattern. |

## core

| Класс | Назначение |
|-------|------------|
| `DispatchActionProcessor` | Camel Service Activator — вызывает зарегистрированный action. |
| `EnrichProcessor` | Camel Content Enricher — обогащает Exchange данными из внешнего action. |
| `FilterProcessor` | Camel Message Filter — пропускает Exchange только если predicate=True. |
| `LogProcessor` | Логирует текущее состояние Exchange (тип body, список properties). |
| `SetHeaderProcessor` | Устанавливает заголовок в in_message Exchange. |
| `SetPropertyProcessor` | Устанавливает runtime-свойство Exchange. |
| `TransformProcessor` | Трансформирует body через JMESPath-выражение. |
| `ValidateProcessor` | Валидирует body через Pydantic-модель. |

## dq_check

| Класс | Назначение |
|-------|------------|
| `DQCheckProcessor` | Проверяет данные по правилам Data Quality. |

## enrichment

| Класс | Назначение |
|-------|------------|
| `CompressProcessor` | Compress body через gzip/brotli/zstd. |
| `DeadlineProcessor` | Устанавливает дedline для pipeline — проверяется последующими процессорами. |
| `DecompressProcessor` | Decompress body (auto-detect или указанный algorithm). |
| `GeoIpProcessor` | GeoIP enrichment via MaxMind GeoLite2. |
| `JwtSignProcessor` | Sign payload as JWT with secret + algorithm. |
| `JwtVerifyProcessor` | Verify JWT from header. Stores claims в property или fail. |
| `WebhookSignProcessor` | Sign outgoing webhook body with HMAC-SHA256. |

## export

| Класс | Назначение |
|-------|------------|
| `ExportProcessor` | Экспортирует body (list[dict]) в файл указанного формата. |

## external

| Класс | Назначение |
|-------|------------|
| `AgentGraphProcessor` | Запускает LangGraph-агента внутри DSL pipeline. |
| `CDCProcessor` | Реагирует на CDC-события и маршрутизирует через DSL. |
| `MCPToolProcessor` | Вызывает внешний MCP tool из DSL pipeline. |

## flow_control

| Класс | Назначение |
|-------|------------|
| `AggregatorProcessor` | Собирает N Exchange по correlation_id. |
| `DelayProcessor` | Задержка обработки на N миллисекунд или до timestamp. |
| `LoopProcessor` | Camel Loop EIP — execute sub-processors N times or until condition. |
| `OnCompletionProcessor` | Camel OnCompletion EIP — execute callback processors after pipeline completes. |
| `ThrottlerProcessor` | Rate-limit per route: N сообщений в секунду. |
| `WireTapProcessor` | Wire Tap — копирует Exchange в отдельный канал. |

## generic

| Класс | Назначение |
|-------|------------|
| `AbTestRouterProcessor` | Стабильная маршрутизация X% трафика на вариант B. |
| `BulkheadProcessor` | Ограничивает одновременное выполнение вложенной ветки на уровне всего процесса. |
| `FeatureFlagGuardProcessor` | Пропускает вложенную ветку только если feature-flag включен. |
| `LineageTrackerProcessor` | Фиксирует происхождение данных: какой pipeline и processor положил значение. |
| `SchemaValidateProcessor` | Валидация body по JSON Schema (Draft 2020-12). |
| `ShadowModeProcessor` | Исполняет вложенные процессоры в «теневом режиме» — без side effects. |
| `SseSourceProcessor` | Source-процессор для Server-Sent Events. |

## idempotency

| Класс | Назначение |
|-------|------------|
| `IdempotentConsumerProcessor` | Idempotent Consumer — предотвращает повторную обработку. |

## integration

| Класс | Назначение |
|-------|------------|
| `EventPublishProcessor` | Публикует событие из pipeline через EventBus. |
| `MemoryLoadProcessor` | Загружает conversation + facts из AgentMemoryService. |
| `MemorySaveProcessor` | Сохраняет результат в AgentMemoryService. |

## ml_inference

| Класс | Назначение |
|-------|------------|
| `EmbeddingProcessor` | Унифицированный embedding generation — OpenAI/SentenceTransformers/Ollama. |
| `OnnxInferenceProcessor` | ONNX model inference (CPU-only). |
| `OutboxProcessor` | Transactional Outbox pattern — guaranteed delivery. |
| `StreamingLLMProcessor` | Streaming LLM response — чанки отправляются через Redis stream. |

## patterns

| Класс | Назначение |
|-------|------------|
| `BatchWindowProcessor` | Benthos-style time-window batching. |
| `DebounceProcessor` | Zapier Debounce — группирует повторы, пропускает только последний. |
| `DeduplicateProcessor` | Benthos-style dedup в скользящем окне. |
| `FormatterProcessor` | Zapier Formatter — форматирует строку из body и properties. |
| `MergeProcessor` | n8n Merge node — объединяет несколько properties в body. |
| `SwitchProcessor` | n8n Switch node — маршрутизация по значению поля. |

## resilience

| Класс | Назначение |
|-------|------------|
| `CircuitBreakerProcessor` | Camel Circuit Breaker EIP — fail-fast pattern inside DSL pipeline. |
| `DeadLetterProcessor` | Dead Letter Channel — направляет упавшие Exchange в DLQ. |
| `FallbackChainProcessor` | Fallback Chain — последовательно пробует процессоры. |
| `TimeoutProcessor` | Camel Timeout EIP — wrap sub-processors with a time limit. |

## routing

| Класс | Назначение |
|-------|------------|
| `DynamicRouterProcessor` | Маршрутизация на основе runtime-выражения. |
| `LoadBalancerProcessor` | Camel Load Balancer EIP — distributes exchanges across multiple routes. |
| `MulticastProcessor` | Camel Multicast EIP — send one message to N processor lists in parallel. |
| `RecipientListProcessor` | Отправляет сообщение на динамический список маршрутов. |
| `ScatterGatherProcessor` | Fan-out на N маршрутов → сборка результатов. |

## rpa

| Класс | Назначение |
|-------|------------|
| `ArchiveProcessor` | ZIP/TAR архивация и распаковка. |
| `DecryptProcessor` | AES расшифровка body через Fernet. |
| `EmailComposeProcessor` | Compose и отправка email через SMTP. |
| `EncryptProcessor` | AES шифрование body через Fernet (symmetric). |
| `ExcelReadProcessor` | Читает Excel файл в list[dict]. |
| `FileMoveProcessor` | Copy, move, or rename файлов. |
| `HashProcessor` | Вычисляет hash от body. |
| `ImageOcrProcessor` | OCR — извлечение текста с изображений через Tesseract. |
| `ImageResizeProcessor` | Ресайз и конвертация изображений через Pillow. |
| `PdfMergeProcessor` | Объединяет несколько PDF в один. |
| `PdfReadProcessor` | Извлекает текст и таблицы из PDF файла. |
| `RegexProcessor` | Regex операции: extract, replace, match. |
| `ShellExecProcessor` | Выполнение shell-команд с whitelist и sandbox. |
| `TemplateRenderProcessor` | Рендеринг Jinja2 шаблонов. |
| `WordReadProcessor` | Извлекает текст из .docx файла. |
| `WordWriteProcessor` | Генерирует .docx документ из текста. |

## rpa_banking

| Класс | Назначение |
|-------|------------|
| `AppiumMobileProcessor` | Appium для автоматизации мобильных банковских приложений. |
| `BankStatementPdfParserProcessor` | Парсер PDF-выписок по счёту (Сбер, ВТБ, Альфа и т.д.). |
| `CitrixSessionProcessor` | Управление Citrix/RDP-сессией. Реальный вызов — через action. |
| `EmailDrivenProcessor` | Email → structured data pipeline. |
| `KeystrokeReplayProcessor` | Воспроизведение записанного сценария клавиатуры/мыши (pyautogui). |
| `SapGuiProcessor` | SAP GUI Scripting (через pywin32). Windows-only. |
| `TerminalEmulator3270Processor` | IBM 3270 терминальный эмулятор. Нужен x3270/py3270. |

## scraping

| Класс | Назначение |
|-------|------------|
| `ApiProxyProcessor` | Transparent API proxy with request/response transformation. |
| `PaginateProcessor` | Multi-page crawling with automatic next-page detection. |
| `ScrapeProcessor` | Extract structured data from HTML using CSS selectors. |

## sequencing

| Класс | Назначение |
|-------|------------|
| `ResequencerProcessor` | Camel Resequencer EIP — reorder messages by sequence field. |

## storage_ext

| Класс | Назначение |
|-------|------------|
| `Neo4jQueryProcessor` | Neo4j Cypher query processor. |
| `PriorityEnqueueProcessor` | Enqueue сообщение в priority queue (Redis sorted set). |
| `TimeSeriesWriteProcessor` | Write to TimescaleDB или InfluxDB (auto-detect по ENV). |

## transformation

| Класс | Назначение |
|-------|------------|
| `ClaimCheckProcessor` | Camel Claim Check EIP — store payload, pass token through pipeline. |
| `MessageTranslatorProcessor` | Конвертация форматов: JSON↔XML, JSON↔CSV. |
| `NormalizerProcessor` | Camel Normalizer EIP — auto-detect input format and normalize to canonical dict. |
| `SortProcessor` | Camel Sort EIP — sort list body by key function. |
| `SplitterProcessor` | Разбивает массив из body на отдельные Exchange. |

## web

| Класс | Назначение |
|-------|------------|
| `ClickProcessor` | Кликает по CSS-селектору на текущей странице. |
| `ExtractProcessor` | Извлекает текст по CSS-селектору. |
| `FillFormProcessor` | Заполняет форму на странице. |
| `NavigateProcessor` | Открывает URL в браузере, результат в properties. |
| `RunScenarioProcessor` | Выполняет multi-step сценарий из body или параметра. |
| `ScreenshotProcessor` | Делает скриншот страницы. |

