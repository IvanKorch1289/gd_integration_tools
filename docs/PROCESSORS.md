# Каталог DSL-процессоров

Полный список процессоров с категориями, builder-методами и примерами.

## Core Processors (app/dsl/engine/processors/core.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `SetHeaderProcessor` | `.set_header(k, v)` | Устанавливает заголовок |
| `SetPropertyProcessor` | `.set_property(k, v)` | Устанавливает runtime-свойство |
| `DispatchActionProcessor` | `.dispatch_action(action)` | **Camel Service Activator** — вызов action из registry |
| `TransformProcessor` | `.transform(expr)` | JMESPath преобразование body |
| `FilterProcessor` | `.filter(pred)` | **Camel Message Filter** — стоп если predicate=False |
| `EnrichProcessor` | `.enrich(action)` | **Camel Content Enricher** — обогащение из action |
| `LogProcessor` | `.log(level)` | Логирование состояния exchange |
| `ValidateProcessor` | `.validate(model)` | Pydantic-валидация body |

## Control Flow (control_flow.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `ChoiceProcessor` | `.choice(when, otherwise)` | When/Otherwise ветвление |
| `TryCatchProcessor` | `.do_try(try, catch, finally)` | Try/catch/finally |
| `RetryProcessor` | `.retry(procs, max_attempts)` | Retry с exponential backoff |
| `PipelineRefProcessor` | `.to_route(route_id)` | Вызов другого маршрута |
| `ParallelProcessor` | `.parallel(branches)` | Параллельное выполнение веток |
| `SagaProcessor` | `.saga(steps)` | Saga с компенсацией |

## Camel EIP (eip.py)

### Routing
| Процессор | Builder | Назначение |
|---|---|---|
| `DynamicRouterProcessor` | `.dynamic_route(expr)` | Runtime-выбор маршрута |
| `LoadBalancerProcessor` | `.load_balance(targets, strategy)` | round_robin/random/weighted/sticky |
| `RecipientListProcessor` | `.recipient_list(expr)` | Динамический fan-out |
| `ScatterGatherProcessor` | `.scatter_gather(routes)` | Fan-out + aggregation |
| `MulticastProcessor` | `.multicast(branches)` | Параллельная отправка на N веток |

### Transformation
| Процессор | Builder | Назначение |
|---|---|---|
| `MessageTranslatorProcessor` | `.translate(from, to)` | (DEPRECATED — use `.convert()`) |
| `NormalizerProcessor` | `.normalize(schema)` | Авто-нормализация XML/CSV/YAML/JSON → dict |
| `ClaimCheckProcessor` | `.claim_check_in/out()` | Хранение payload в Redis, передача токена |
| `ResequencerProcessor` | `.resequence(key, seq_field)` | Восстановление порядка сообщений |
| `SortProcessor` | `.sort(key_field, reverse)` | Сортировка list body |

### Resilience
| Процессор | Builder | Назначение |
|---|---|---|
| `DeadLetterProcessor` | `.dead_letter(procs)` | DLQ для упавших Exchange |
| `IdempotentConsumerProcessor` | `.idempotent(key)` | Дедупликация через Redis (постоянная) |
| `FallbackChainProcessor` | `.fallback(procs)` | Последовательный fallback |
| `CircuitBreakerProcessor` | `.circuit_breaker(procs)` | CLOSED→OPEN→HALF_OPEN |
| `TimeoutProcessor` | `.timeout(procs, seconds)` | Обёртка с таймаутом |
| `LoopProcessor` | `.loop(procs, count/until)` | Цикл N раз или до условия |
| `OnCompletionProcessor` | `.on_completion(procs)` | Callback после pipeline (как finally) |

### Flow
| Процессор | Builder | Назначение |
|---|---|---|
| `ThrottlerProcessor` | `.throttle(rate)` | Rate limiting (token bucket) |
| `DelayProcessor` | `.delay(ms)` | Задержка |
| `SplitterProcessor` | `.split(expr, procs)` | Разбиение массива на отдельные Exchange |
| `AggregatorProcessor` | `.aggregate(key, batch_size)` | Агрегация по correlation_id |
| `WireTapProcessor` | `.wire_tap(procs)` | Копия Exchange в отдельный канал |

## Components (components.py) — Sources/Sinks

| Процессор | Builder | Назначение |
|---|---|---|
| `HttpCallProcessor` | `.http_call(url, method)` | HTTP client (GET/POST/PUT/DELETE) |
| `DatabaseQueryProcessor` | `.db_query(sql)` | SQL через SQLAlchemy |
| `FileReadProcessor` | `.read_file(path)` | Чтение локального файла |
| `FileWriteProcessor` | `.write_file(path, format)` | Запись в файл |
| `S3ReadProcessor` | `.read_s3(bucket, key)` | Загрузка из S3 |
| `S3WriteProcessor` | `.write_s3(bucket, key)` | Выгрузка в S3 |
| `TimerProcessor` | `.timer(interval)` | Scheduled event source |
| `PollingConsumerProcessor` | `.poll(action)` | Периодический опрос action |

## Converters (converters.py)

| Builder | Назначение |
|---|---|
| `.convert(from, to)` | Универсальный конвертер форматов |

Поддерживаемые форматы: `json`, `yaml`, `xml`, `csv`, `msgpack`, `parquet`, `bson`, `html→json`.

## Scraping (scraping.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `ScrapeProcessor` | `.scrape(url, selectors)` | CSS-selector extraction (с SSRF-защитой) |
| `PaginateProcessor` | `.paginate(next_selector)` | Multi-page crawling |
| `ApiProxyProcessor` | `.api_proxy(base_url)` | Прозрачный API proxy |

## AI/ML (ai.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `PromptComposerProcessor` | `.compose_prompt(tpl)` | Построение промпта из шаблона |
| `LLMCallProcessor` | `.call_llm()` | Вызов LLM с PII-маскировкой |
| `LLMFallbackProcessor` | `.call_llm_with_fallback()` | LLM с fallback-цепочкой провайдеров |
| `LLMParserProcessor` | `.parse_llm_output(schema)` | Парсинг LLM в Pydantic |
| `TokenBudgetProcessor` | `.token_budget(n)` | Ограничение по токенам (tiktoken) |
| `VectorSearchProcessor` | `.rag_search(query)` | RAG поиск |
| `SanitizePIIProcessor` | `.sanitize_pii()` | PII маскирование перед LLM |
| `RestorePIIProcessor` | `.restore_pii()` | Восстановление PII после LLM |
| `CacheProcessor` | `.cache(key_fn)` | Redis-кеш чтение |
| `CacheWriteProcessor` | `.cache_write(key_fn)` | Redis-кеш запись |
| `GuardrailsProcessor` | `.guardrails()` | Проверка LLM output (length, blocklist) |

## RPA (UiPath-style) (rpa.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `PdfReadProcessor` | `.pdf_read()` | Извлечение текста и таблиц из PDF |
| `PdfMergeProcessor` | `.pdf_merge()` | Объединение PDF |
| `WordReadProcessor` | `.word_read()` | Чтение .docx |
| `WordWriteProcessor` | `.word_write()` | Генерация .docx |
| `ExcelReadProcessor` | `.excel_read(sheet)` | Чтение Excel → list[dict] |
| `FileMoveProcessor` | `.file_move(src, dst, mode)` | Copy/move/rename |
| `ArchiveProcessor` | `.archive(mode, format)` | ZIP/TAR |
| `ImageOcrProcessor` | `.ocr(lang)` | OCR (pytesseract) |
| `ImageResizeProcessor` | `.image_resize(w, h)` | Ресайз (Pillow) |
| `RegexProcessor` | `.regex(pattern, action)` | Regex extract/replace/match |
| `TemplateRenderProcessor` | `.render_template(tpl)` | Jinja2 |
| `HashProcessor` | `.hash(algorithm)` | sha256/md5/sha512 |
| `EncryptProcessor` | `.encrypt(key)` | AES Fernet |
| `DecryptProcessor` | `.decrypt(key)` | AES Fernet |
| `ShellExecProcessor` | `.shell(cmd, allowed)` | Shell с whitelist |
| `EmailComposeProcessor` | `.email(to, subj, tpl)` | SMTP email с шаблоном |

## Framework Patterns (patterns.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `SwitchProcessor` | `.switch(field, cases)` | n8n — case/match роутинг |
| `MergeProcessor` | `.merge(props, mode)` | n8n — объединение properties в body |
| `BatchWindowProcessor` | `.batch_window(window)` | Benthos — time-window batching |
| `DeduplicateProcessor` | `.deduplicate(key_fn)` | Benthos — дедупликация в окне |
| `FormatterProcessor` | `.format_text(template)` | Zapier — строковое форматирование |
| `DebounceProcessor` | `.debounce(key_fn, delay)` | Zapier — debounce повторов |

## Web Automation (web.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `NavigateProcessor` | `.navigate(url)` | Открыть URL в браузере |
| `ClickProcessor` | `.click(sel)` | Клик по CSS-selector |
| `FillFormProcessor` | `.fill_form(url, fields)` | Заполнение формы |
| `ExtractProcessor` | `.extract(sel)` | Извлечение по CSS |
| `ScreenshotProcessor` | `.screenshot(url)` | Скриншот страницы |
| `RunScenarioProcessor` | `.run_scenario(steps)` | Multi-step сценарий |

## External (external.py)

| Процессор | Builder | Назначение |
|---|---|---|
| `MCPToolProcessor` | `.mcp_tool(uri, tool)` | Вызов внешнего MCP tool |
| `AgentGraphProcessor` | `.agent_graph(name, tools)` | LangGraph agent |
| `CDCProcessor` | `.cdc(profile, tables, strategy)` | Change Data Capture (polling/PG/Oracle) |

## Integration/Export/DQ

| Процессор | Builder | Назначение |
|---|---|---|
| `EventPublishProcessor` | `.publish_event(channel)` | EventBus publish |
| `MemoryLoadProcessor` | `.load_memory()` | Agent memory (Redis) |
| `MemorySaveProcessor` | `.save_memory()` | Agent memory save |
| `ExportProcessor` | `.export(format)` | CSV/Excel/PDF export |
| `DQCheckProcessor` | `.dq_check(rules)` | Data Quality validation |

## Статистика

- **Всего процессоров: 85+**
- **Docstrings coverage**: ~95%
- **Camel EIP coverage**: ~85%
