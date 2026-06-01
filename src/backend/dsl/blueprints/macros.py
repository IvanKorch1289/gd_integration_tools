"""DSL Macros — pre-built patterns для типовых интеграционных сценариев.

Каждый макрос создаёт Pipeline с Apache Camel-style паттернами.
Новичок может использовать макрос как отправную точку,
а опытный разработчик — как baseline для кастомизации.

Категории:
- ETL: extract → transform → load (с retry, DLQ, circuit breaker)
- Relay: webhook/event fan-out (recipient list, multicast)
- AI: RAG search → prompt → LLM → parse (с PII-маскировкой)
- CRUD: create/update/delete с аудитом и event publishing
- Scraping: web extraction + pagination
- Sync: безопасная синхронизация с external API
"""

from __future__ import annotations

from typing import Any, Callable

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    DeadLetterProcessor,
    DispatchActionProcessor,
    LogProcessor,
    RetryProcessor,
)

__all__ = (
    "etl_pipeline",
    "webhook_relay",
    "ai_qa_pipeline",
    "safe_action",
    "crud_with_audit",
    "scrape_and_store",
    "format_bridge",
    "polling_etl",
)


def etl_pipeline(
    route_id: str,
    source: str,
    extract_action: str,
    transform_fn: Callable[[Exchange[Any], Any], None],
    load_action: str,
    *,
    retry_attempts: int = 3,
    use_circuit_breaker: bool = True,
    normalize_schema: type | None = None,
    description: str = "",
) -> Pipeline:
    """ETL pipeline: extract → normalize → transform → load.

    Включает Circuit Breaker для защиты от каскадных сбоев,
    Normalizer для приведения данных к единому формату,
    и OnCompletion для уведомления о результате.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник данных (e.g., "timer:60s", "internal:etl").
        extract_action: Action для извлечения данных.
        transform_fn: Функция трансформации.
        load_action: Action для загрузки данных.
        retry_attempts: Количество попыток при ошибке.
        use_circuit_breaker: Включить Circuit Breaker.
        normalize_schema: Pydantic-модель для нормализации.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый ETL pipeline.

    Example::

        pipeline = etl_pipeline(
            route_id="etl.orders",
            source="timer:300s",
            extract_action="external_db.query",
            transform_fn=transform_orders,
            load_action="analytics.insert_batch",
        )
    """
    builder = RouteBuilder.from_(
        route_id, source=source, description=description or f"ETL: {route_id}"
    )

    extract_proc = DispatchActionProcessor(action=extract_action)

    if use_circuit_breaker:
        builder = builder.circuit_breaker(
            processors=[
                RetryProcessor(processors=[extract_proc], max_attempts=retry_attempts)
            ],
            failure_threshold=5,
            recovery_timeout=60.0,
            fallback_processors=[LogProcessor(level="error")],
        )
    else:
        builder = builder.retry(processors=[extract_proc], max_attempts=retry_attempts)

    if normalize_schema:
        builder = builder.normalize(target_schema=normalize_schema)

    builder = (
        builder.process_fn(transform_fn)
        .dispatch_action(load_action)
        .on_completion(processors=[LogProcessor(level="info")])
    )
    return builder.build()


def webhook_relay(
    route_id: str,
    source: str,
    targets: list[str],
    *,
    parallel: bool = True,
    with_dead_letter: bool = True,
    description: str = "",
) -> Pipeline:
    """Webhook relay: 1 вход → N выходов с DLQ.

    Использует Recipient List для fan-out и Dead Letter Channel
    для обработки ошибок при доставке.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник webhook (e.g., "webhook:/incoming").
        targets: Список target route_id для рассылки.
        parallel: Параллельная или последовательная доставка.
        with_dead_letter: Включить DLQ для недоставленных.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый relay pipeline.
    """
    builder = RouteBuilder.from_(
        route_id, source=source, description=description or f"Relay: {route_id}"
    )

    if with_dead_letter:
        builder = builder.dead_letter(
            processors=[DispatchActionProcessor(action="notify.send")]
        )

    builder = (
        builder.idempotent(lambda ex: ex.meta.correlation_id, ttl_seconds=3600)
        .recipient_list(lambda ex: targets, parallel=parallel)
        .log(f"Relayed to {len(targets)} targets")
    )
    return builder.build()


def ai_qa_pipeline(
    route_id: str,
    source: str = "internal:ai",
    *,
    query_field: str = "question",
    top_k: int = 5,
    provider: str | None = None,
    model: str | None = None,
    response_schema: type | None = None,
    max_tokens: int = 4096,
    description: str = "",
) -> Pipeline:
    """AI Q&A pipeline: RAG → prompt → PII mask → LLM → unmask → parse.

    Полный цикл обработки вопроса с использованием RAG,
    PII-маскировки и ограничения по токенам.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник (обычно "internal:ai").
        query_field: Поле с вопросом в body.
        top_k: Количество результатов RAG-поиска.
        provider: LLM провайдер (openai, anthropic, ...).
        model: Конкретная модель.
        response_schema: Pydantic-модель для парсинга ответа.
        max_tokens: Максимум токенов в промпте.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый AI Q&A pipeline.

    Example::

        pipeline = ai_qa_pipeline(
            route_id="ai.support",
            query_field="question",
            top_k=10,
            provider="anthropic",
            response_schema=SupportAnswerSchema,
        )
    """
    builder = (
        RouteBuilder.from_(
            route_id, source=source, description=description or f"AI Q&A: {route_id}"
        )
        .timeout(
            processors=[DispatchActionProcessor(action="rag.search")], seconds=15.0
        )
        .rag_search(query_field=query_field, top_k=top_k)
        .compose_prompt(
            template="Контекст:\n{context}\n\nВопрос: {" + query_field + "}\nОтвет:",
            context_property="vector_results",
        )
        .token_budget(max_tokens=max_tokens)
        .sanitize_pii()
        .call_llm(provider=provider, model=model)
        .restore_pii()
    )
    if response_schema:
        builder = builder.parse_llm_output(schema=response_schema)

    return builder.build()


def safe_action(
    route_id: str,
    action: str,
    *,
    source: str = "",
    max_retries: int = 3,
    dlq_action: str | None = None,
    timeout_seconds: float = 30.0,
    description: str = "",
) -> Pipeline:
    """Action с retry, timeout и optional dead-letter queue.

    Обёртка для любого action с production-ready обработкой ошибок:
    timeout → retry с exponential backoff → DLQ при исчерпании попыток.

    Args:
        route_id: Уникальный идентификатор маршрута.
        action: Имя action для выполнения.
        source: Источник.
        max_retries: Максимум попыток.
        dlq_action: Action для Dead Letter Queue (опционально).
        timeout_seconds: Таймаут на выполнение.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый pipeline с resilience-паттернами.
    """
    builder = RouteBuilder.from_(
        route_id,
        source=source or f"internal:{route_id}",
        description=description or f"Safe action: {action}",
    )

    action_processor = DispatchActionProcessor(action=action)

    if dlq_action:
        builder = builder.do_try(
            try_processors=[
                RetryProcessor(processors=[action_processor], max_attempts=max_retries)
            ],
            catch_processors=[
                LogProcessor(level="error"),
                DeadLetterProcessor(
                    processors=[DispatchActionProcessor(action=dlq_action)]
                ),
            ],
        )
    else:
        builder = builder.retry(processors=[action_processor], max_attempts=max_retries)

    return builder.build()


def crud_with_audit(
    route_id_prefix: str,
    create_action: str,
    update_action: str,
    delete_action: str,
    *,
    event_channel: str = "events.orders",
    source_prefix: str = "internal",
    validate_model: type | None = None,
) -> list[Pipeline]:
    """CRUD pipelines с event publishing для аудита.

    Создаёт 3 маршрута (create/update/delete), каждый:
    - Валидирует входные данные (опционально)
    - Выполняет action
    - Публикует событие для аудита
    - Логирует результат

    Args:
        route_id_prefix: Префикс для route_id (e.g., "orders").
        create_action: Action для создания.
        update_action: Action для обновления.
        delete_action: Action для удаления.
        event_channel: Канал для публикации событий.
        source_prefix: Префикс источника.
        validate_model: Pydantic-модель для валидации.

    Returns:
        list[Pipeline]: Три pipeline (create, update, delete).
    """
    pipelines = []

    for op, action in [
        ("create", create_action),
        ("update", update_action),
        ("delete", delete_action),
    ]:
        builder = RouteBuilder.from_(
            f"{route_id_prefix}.{op}", source=f"{source_prefix}:{route_id_prefix}.{op}"
        )
        if validate_model and op in ("create", "update"):
            builder = builder.validate(validate_model)
        builder = (
            builder.dispatch_action(action)
            .publish_event(event_channel)
            .on_completion(processors=[LogProcessor(level="info")])
        )
        pipelines.append(builder.build())

    return pipelines


def scrape_and_store(
    route_id: str,
    url: str,
    selectors: dict[str, str],
    store_action: str,
    *,
    paginate: bool = False,
    max_pages: int = 5,
    next_selector: str = "a.next",
    sort_field: str | None = None,
    description: str = "",
) -> Pipeline:
    """Web scraping pipeline: scrape → paginate → sort → store.

    Полный цикл извлечения данных с сайта:
    - CSS-selector extraction
    - Опциональная пагинация
    - Сортировка результатов
    - Сохранение через action

    Args:
        route_id: Уникальный идентификатор маршрута.
        url: URL для парсинга.
        selectors: CSS-селекторы {field_name: selector}.
        store_action: Action для сохранения результатов.
        paginate: Включить пагинацию.
        max_pages: Максимум страниц при пагинации.
        next_selector: CSS-селектор кнопки "далее".
        sort_field: Поле для сортировки результатов.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый scraping pipeline.
    """
    builder = RouteBuilder.from_(
        route_id, source=f"scrape:{url}", description=description or f"Scrape: {url}"
    )
    builder = builder.scrape(url, selectors=selectors)

    if paginate:
        builder = builder.paginate(
            next_selector=next_selector, max_pages=max_pages, start_url=url
        )

    if sort_field:
        builder = builder.sort(key_field=sort_field)

    builder = builder.dispatch_action(store_action).log("Scraping complete")
    return builder.build()


def format_bridge(
    route_id: str,
    source: str,
    from_format: str,
    to_format: str,
    target_action: str,
    *,
    description: str = "",
) -> Pipeline:
    """Format conversion bridge: receive → convert → forward.

    Конвертирует данные из одного формата в другой
    и пересылает в target action.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник данных.
        from_format: Входной формат (json, xml, yaml, csv, msgpack).
        to_format: Выходной формат.
        target_action: Action для отправки конвертированных данных.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый конвертирующий pipeline.
    """
    return (
        RouteBuilder.from_(
            route_id,
            source=source,
            description=description or f"Bridge: {from_format}→{to_format}",
        )
        .normalize()
        .convert(from_format, to_format)
        .dispatch_action(target_action)
        .build()
    )


def polling_etl(
    route_id: str,
    source_action: str,
    transform_fn: Callable[[Exchange[Any], Any], None] | None = None,
    load_action: str = "analytics.insert_batch",
    *,
    interval_seconds: float = 60.0,
    sort_field: str | None = None,
    description: str = "",
) -> Pipeline:
    """Polling ETL: timer → poll → transform → sort → load.

    Периодически опрашивает источник данных, трансформирует
    и загружает в хранилище.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source_action: Action для получения данных.
        transform_fn: Функция трансформации (опционально).
        load_action: Action для загрузки.
        interval_seconds: Интервал опроса в секундах.
        sort_field: Поле для сортировки перед загрузкой.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый polling ETL pipeline.
    """
    builder = (
        RouteBuilder.from_(
            route_id,
            source=f"timer:{interval_seconds}s",
            description=description or f"Polling ETL: {source_action}",
        )
        .timer(interval_seconds=interval_seconds)
        .poll(source_action)
    )

    if transform_fn:
        builder = builder.process_fn(transform_fn)

    if sort_field:
        builder = builder.sort(key_field=sort_field)

    builder = builder.dispatch_action(load_action).log("Polling ETL complete")
    return builder.build()
