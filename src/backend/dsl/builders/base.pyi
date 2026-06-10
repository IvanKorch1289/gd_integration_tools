"""src.backend.dsl.builders.base — auto-generated .pyi stub (Sprint 14 K3 W2).

Этот файл сгенерирован ``tools/gen_dsl_stubs.py`` через runtime
introspection ``RouteBuilder``. Не редактировать вручную —
обновляйте через ``make dsl-stubs``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Union

from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.builders.data_store_mixin import DataStore
from src.backend.dsl.builders.deferred_execution_mixin import (
    DeferCondition,
    TimestampLike,
)
from src.backend.dsl.builders.template_engine_mixin import Context, PathLike
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow import ChoiceBranch, SagaStep
from src.backend.dsl.processors.plan_execute_processor import (
    ExecutorFn,
    PlannerFn,
    VerifierFn,
)
from src.backend.dsl.processors.reflection_loop_processor import CriticFn, GeneratorFn
from src.backend.dsl.processors.router_specialist_processor import (
    LLMRouterFn,
    SpecialistAgent,
)

class RouteBuilder:
    def ab_test(
        self,
        variant_a: list[BaseProcessor],
        variant_b: list[BaseProcessor],
        *,
        split_percent: int = ...,
        key_fn: Union[Callable[[Exchange[Any]], str], None] = ...,
    ) -> RouteBuilder:
        """Стабильная маршрутизация X% трафика на вариант B."""
        ...

    def agent_branch(
        self,
        *,
        source_property: str,
        branches: dict[str, list[BaseProcessor]],
        default: Union[list[BaseProcessor], None] = ...,
    ) -> RouteBuilder:
        """Verdict-based routing по ``agent_result`` (S27 W1)."""
        ...

    def agent_graph(self, graph_name: str, tools: list[str]) -> RouteBuilder:
        """Запуск LangGraph-агента."""
        ...

    def agent_loop(
        self,
        *,
        processors: list[BaseProcessor],
        max_iterations: int = ...,
        stop_condition_property: Union[str, None] = ...,
        budget_cost_usd: Union[float, None] = ...,
        budget_tokens: Union[int, None] = ...,
    ) -> RouteBuilder:
        """Циклическое выполнение вложенного pipeline (S27 W1)."""
        ...

    def agent_parallel(
        self,
        *,
        agents: list[dict[str, Any]],
        result_property: str = ...,
        timeout_s: Union[float, None] = ...,
        continue_on_error: bool = ...,
    ) -> RouteBuilder:
        """Параллельный fan-out агентов через :class:`asyncio.TaskGroup` (S27 W1)."""
        ...

    def agent_run(
        self,
        *,
        workflow_id: str,
        prompt_ref: Union[str, None] = ...,
        prompt_inline: Union[str, None] = ...,
        policy_ref: Union[str, None] = ...,
        context_property: Union[str, None] = ...,
        result_property: str = ...,
        timeout_s: float = ...,
        max_retries: int = ...,
    ) -> RouteBuilder:
        """Вызов :class:`AIGateway.invoke` по ``workflow_id`` (S27 W1)."""
        ...

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = ...,
        timeout_seconds: float = ...,
    ) -> RouteBuilder:
        """Aggregator: собирает N Exchange по correlation_key в batch."""
        ...

    def ai_invoke(
        self,
        *,
        workflow_id: str,
        prompt_ref: Union[str, None] = ...,
        prompt_inline: Union[str, None] = ...,
        policy_ref: Union[str, None] = ...,
        context_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Алиас :meth:`agent_run` — для семантически нагруженных мест"""
        ...

    def ai_memory_recall(
        self,
        *,
        namespace: str,
        query: Union[str, None] = ...,
        query_property: Union[str, None] = ...,
        k: int = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """RAG-style retrieval из :class:`MemoryProtocol` (S27 W3, ADR-NEW-18)."""
        ...

    def ai_memory_store(
        self,
        *,
        namespace: str,
        key: Union[str, None] = ...,
        key_property: Union[str, None] = ...,
        value_property: str = ...,
        ttl_s: Union[int, None] = ...,
    ) -> RouteBuilder:
        """Запись в :class:`MemoryProtocol` (S27 W3, ADR-NEW-18)."""
        ...

    def ai_rpa(
        self,
        *,
        task: str,
        ui_context: Union[dict[str, Any], None] = ...,
        action_property: str = ...,
        model: str = ...,
        temperature: float = ...,
        to: str = ...,
    ) -> RouteBuilder:
        """AI-driven RPA action selection via LLM (S28 W5, wave:s8/k3-rpa-ai-decide)."""
        ...

    def antifraud_score(self, model: str = ...) -> RouteBuilder:
        """LLM-скоринг антифрода (поверх детерминистических правил)."""
        ...

    def api_proxy(
        self, base_url: str, *, method: str = ..., path: str = ..., timeout: float = ...
    ) -> RouteBuilder:
        """Прозрачный API proxy с request/response трансформацией."""
        ...

    def appeal_ai(self) -> RouteBuilder:
        """Автоматическая обработка клиентских обращений."""
        ...

    def appium_mobile(
        self, platform: str, app_package: str, operation: str
    ) -> RouteBuilder:
        """Appium автоматизация мобильных приложений (android/ios)."""
        ...

    def archive(self, *, mode: str = ..., format: str = ...) -> RouteBuilder:
        """Создать или распаковать архив (ZIP/TAR)."""
        ...

    def audit(
        self,
        *,
        action: Union[str, None] = ...,
        action_from: Union[str, None] = ...,
        actor: str = ...,
        actor_from: Union[str, None] = ...,
        resource_from: Union[str, None] = ...,
        outcome: str = ...,
        outcome_from: Union[str, None] = ...,
        metadata_from: Union[str, None] = ...,
        tenant_id_from: Union[str, None] = ...,
        correlation_id_from: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Записать событие в immutable audit log (Wave 5.1)."""
        ...

    def auth(
        self,
        methods: Union[list[str], str] = ...,
        *,
        result_property: str = ...,
        required: bool = ...,
    ) -> RouteBuilder:
        """Проверяет авторизацию запроса (Wave 8.1)."""
        ...

    def batch(
        self,
        *,
        size: int = ...,
        timeout_ms: int = ...,
        group_by: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Накопление сообщений в окно с flush по N ИЛИ по таймауту."""
        ...

    def batch_delete(
        self,
        table: str,
        ids: Union[list[Any], None] = ...,
        *,
        key_field: str = ...,
        profile: str = ...,
    ) -> RouteBuilder:
        """Batch DELETE через SQLAlchemy core."""
        ...

    def batch_insert(
        self,
        table: str,
        items: Union[list[dict[str, Any]], None] = ...,
        *,
        profile: str = ...,
    ) -> RouteBuilder:
        """Batch INSERT через SQLAlchemy core."""
        ...

    def batch_update(
        self,
        table: str,
        items: Union[list[dict[str, Any]], None] = ...,
        *,
        key_field: str = ...,
        profile: str = ...,
    ) -> RouteBuilder:
        """Batch UPDATE через SQLAlchemy core."""
        ...

    def build(self, *, validate_actions: bool = ...) -> Pipeline:
        """Собирает Pipeline из накопленных процессоров."""
        ...

    def bulkhead(
        self,
        name: str,
        limit: int,
        processors: list[BaseProcessor],
        *,
        wait: bool = ...,
        timeout: Union[float, None] = ...,
    ) -> RouteBuilder:
        """Ограничивает concurrency на ветку — защита провайдера от перегрузки."""
        ...

    def cache(
        self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = ...
    ) -> RouteBuilder:
        """Redis-кеш: проверяет наличие по ключу, пропускает если есть."""
        ...

    def cache_write(
        self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = ...
    ) -> RouteBuilder:
        """Redis-кеш: записывает результат после обработки."""
        ...

    def call_function(
        self,
        ref: str,
        *,
        payload_from: str = ...,
        result_property: str = ...,
        inject: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Вызов Python-функции ``module:fn`` (R-V15-6, V21 security)."""
        ...

    def call_llm(
        self, provider: Union[str, None] = ..., model: Union[str, None] = ...
    ) -> RouteBuilder:
        """LLM chat-completion через ai_agent сервис (с PII-маскировкой)."""
        ...

    def call_llm_with_fallback(
        self, providers: list[str], *, model: str = ...
    ) -> RouteBuilder:
        """LLM с fallback-цепочкой провайдеров."""
        ...

    def cancel_deferred(self) -> RouteBuilder:
        """Отменить pending deferral (clear ``_deferred`` slot)."""
        ...

    def cancel_workflow(
        self,
        workflow_id: str,
        *,
        reason: str = ...,
        namespace: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отмена workflow по ``workflow_id`` (Sprint 12 K3 W7)."""
        ...

    def cdc(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
        *,
        strategy: str = ...,
        interval: float = ...,
        timestamp_column: str = ...,
        batch_size: int = ...,
        channel: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Change Data Capture — подписка на изменения в БД."""
        ...

    def choice(
        self,
        when: list[ChoiceBranch]
        | list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: Union[list[BaseProcessor], None] = ...,
    ) -> RouteBuilder:
        """When/Otherwise: ветвление по JMESPath-веткам или предикатам."""
        ...

    def circuit_breaker(
        self,
        processors: list[BaseProcessor],
        *,
        failure_threshold: int = ...,
        recovery_timeout: float = ...,
        fallback_processors: Union[list[BaseProcessor], None] = ...,
        breaker_name: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Circuit Breaker: fail-fast при повторных ошибках (CLOSED/OPEN/HALF_OPEN)."""
        ...

    def citrix(self, operation: str, session_id: str) -> RouteBuilder:
        """Citrix/RDP-сессия (launch/click/type/screenshot/close)."""
        ...

    def claim_check_in(
        self, *, store: str = ..., ttl_seconds: int = ..., threshold_bytes: int = ...
    ) -> RouteBuilder:
        """Claim Check (store): сохраняет body в Redis/S3, body → {_claim_token: ...}."""
        ...

    def claim_check_out(self) -> RouteBuilder:
        """Claim Check (retrieve): восстанавливает body по _claim_token."""
        ...

    def click(self, url: str, selector: str) -> RouteBuilder:
        """Клик по CSS-селектору."""
        ...

    def clickhouse_insert(self, table: str, *, batch_size: int = ...) -> RouteBuilder:
        """Batch INSERT в ClickHouse ``table`` из exchange body."""
        ...

    def clickhouse_query(self, query: str, *, to_property: str = ...) -> RouteBuilder:
        """SELECT в ClickHouse; результат в ``exchange.properties[to_property]``."""
        ...

    def collect(
        self,
        *,
        field: Union[str, None] = ...,
        key_fn: Union[Callable[[Any], Any], None] = ...,
    ) -> RouteBuilder:
        """Извлекает поле из каждого объекта коллекции в body."""
        ...

    def compliance_labels(self, *, labels: list[str]) -> RouteBuilder:
        """Compliance-метки на Exchange (PII/PCI/FIN/GDPR)."""
        ...

    def compose_prompt(
        self, template: str, context_property: str = ...
    ) -> RouteBuilder:
        """Построение промпта из шаблона + контекста из properties."""
        ...

    def composed_message(
        self,
        splitter: Callable[[Exchange[Any]], Any],
        processors: list[BaseProcessor],
        aggregator: Callable[[list[Exchange[Any]]], Any],
    ) -> RouteBuilder:
        """Composed Message Processor: split → per-part → aggregate."""
        ...

    def compress(self, *, algorithm: str = ..., level: int = ...) -> RouteBuilder:
        """Сжатие body (gzip/brotli/zstd)."""
        ...

    def content_based_router(
        self,
        routes: list[tuple[Callable[[Exchange[Any]], bool], str]],
        *,
        default_endpoint: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Content-Based Router EIP: route по predicate."""
        ...

    def content_enrich(
        self,
        *,
        strategy: str = ...,
        field: str = ...,
        source: Union[str, None] = ...,
        value: Any = ...,
        name: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Content Enricher EIP — http/static/function strategies."""
        ...

    def content_filter(
        self, predicate: Callable[[Exchange[Any]], bool]
    ) -> RouteBuilder:
        """Alias для :meth:`filter` — фильтрует Exchange, останавливает если False."""
        ...

    def content_transform(self, expression: str) -> RouteBuilder:
        """Alias для :meth:`transform` — трансформирует body через JMESPath-выражение."""
        ...

    def correlation_id(self, *, header: str = ...) -> RouteBuilder:
        """Correlation Identifier: проставляет/пропагирует correlation-id."""
        ...

    def cost_tracker(self) -> RouteBuilder:
        """Инициализация cost-словаря в properties (LLM-токены, HTTP, DB, USD)."""
        ...

    def credit_scoring_rag(self, product: str = ...) -> RouteBuilder:
        """Кредитный скоринг через RAG."""
        ...

    def crud_create(
        self, entity: str, *, payload_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_create` (R-V15-12 / 80/20 YAML)."""
        ...

    def crud_delete(
        self, entity: str, *, id_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_delete` (R-V15-12)."""
        ...

    def crud_list(
        self,
        entity: str,
        *,
        filters_from: Union[str, None] = ...,
        page: Union[int, None] = ...,
        size: Union[int, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_list` (R-V15-12)."""
        ...

    def crud_read(
        self, entity: str, *, id_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_get` (R-V15-12)."""
        ...

    def crud_update(
        self,
        entity: str,
        *,
        id_from: str = ...,
        payload_from: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Алиас к :meth:`entity_update` (R-V15-12)."""
        ...

    def customer_chatbot(self, channel: str = ...) -> RouteBuilder:
        """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""
        ...

    def data_store(self, name: str = ..., backend: str = ...) -> DataStore:
        """Get-or-create named :class:`DataStore` (lazy, per-builder scope)."""
        ...

    def data_store_delete(self, key: str) -> RouteBuilder:
        """Удаляет ключ из in-memory store Exchange."""
        ...

    def data_store_get(
        self, key: str, *, default: Any = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Читает значение из in-memory store Exchange."""
        ...

    def data_store_set(self, key: str, value: Any) -> RouteBuilder:
        """Сохраняет значение в in-memory store Exchange."""
        ...

    def db_call_procedure(
        self,
        profile: str,
        name: str,
        *,
        schema: str = ...,
        params_from: str = ...,
        result_property: str = ...,
        dialect: str = ...,
    ) -> RouteBuilder:
        """K3 S5 W8 — вызвать stored procedure через ExternalDatabaseRegistry."""
        ...

    def db_query(self, sql: str, *, result_property: str = ...) -> RouteBuilder:
        """SQL-запрос через SQLAlchemy (с валидацией: DDL/multi-statement запрещены)."""
        ...

    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = ...,
        result_property: str = ...,
        fetch: str = ...,
        commit: bool = ...,
    ) -> RouteBuilder:
        """Выполняет произвольный SQL во внешней БД по profile-имени."""
        ...

    def dead_letter(
        self, processors: list[BaseProcessor], *, dlq_stream: str = ...
    ) -> RouteBuilder:
        """Dead Letter Channel: при ошибке — отправка в Redis stream."""
        ...

    def deadline(
        self, *, timeout_seconds: float = ..., fail_on_exceed: bool = ...
    ) -> RouteBuilder:
        """Установка дedline pipeline; downstream проверяет _deadline_at."""
        ...

    def decompress(self, *, algorithm: str = ...) -> RouteBuilder:
        """Распаковка body (auto-detect или явный algorithm)."""
        ...

    def decrypt(self, key: str) -> RouteBuilder:
        """Дешифрование AES-GCM-сообщения."""
        ...

    def defer_for(self, seconds: int = ...) -> RouteBuilder:
        """Defer execution на ``seconds`` секунд (Airflow-style ``execution_date``)."""
        ...

    def defer_if(self, condition: DeferCondition) -> RouteBuilder:
        """Conditional defer — выполнить defer только если ``condition(exchange)`` truthy."""
        ...

    def defer_until(self, timestamp: TimestampLike) -> RouteBuilder:
        """Defer execution до указанного момента (Airflow-style ``sla``)."""
        ...

    def delay(
        self,
        delay_ms: Union[int, None] = ...,
        *,
        scheduled_time_fn: Union[Callable[[Exchange[Any]], float], None] = ...,
    ) -> RouteBuilder:
        """Delay: задержка на N миллисекунд или до timestamp."""
        ...

    def depends(self, *deps: Union[str, tuple[str, str]]) -> RouteBuilder:
        """Добавляет DI-зависимости к последнему processor (call_function/process_fn)."""
        ...

    def diff(self, other: list[Any]) -> RouteBuilder:
        """Разность body с другим списком."""
        ...

    def directory_scan(
        self,
        path: str,
        pattern: str = ...,
        *,
        recursive: bool = ...,
        max_files: int = ...,
        sort_by: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Сканирует директорию и возвращает список файлов, подходящих под glob."""
        ...

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Union[Callable[[Exchange[Any]], dict[str, Any]], None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Вызывает зарегистрированный action (Service Activator)."""
        ...

    def do_try(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: Union[list[BaseProcessor], None] = ...,
        finally_processors: Union[list[BaseProcessor], None] = ...,
    ) -> RouteBuilder:
        """Try/Catch/Finally: exception handling в pipeline."""
        ...

    def durable_fanout(self, broker: Any, subscribers: list[str]) -> RouteBuilder:
        """Durable Subscriber: fan-out к persistent-подписчикам."""
        ...

    def dynamic_route(
        self, route_expression: Callable[[Exchange[Any]], str]
    ) -> RouteBuilder:
        """Dynamic Router: runtime-вычисление route_id."""
        ...

    def email(self, to: str, subject: str, body_template: str) -> RouteBuilder:
        """Compose + отправка email через SMTP."""
        ...

    def email_driven(
        self,
        mailbox: str = ...,
        subject_filter: Union[str, None] = ...,
        extract: str = ...,
    ) -> RouteBuilder:
        """IMAP → structured data pipeline."""
        ...

    def encrypt(self, key: str) -> RouteBuilder:
        """Шифрование тела сообщения (AES-GCM)."""
        ...

    def enrich(
        self,
        action: str,
        *,
        payload_factory: Union[Callable[[Exchange[Any]], dict[str, Any]], None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Enrich: вызывает action и сохраняет результат в property."""
        ...

    def entity_create(
        self, *, entity: str, payload_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Создать сущность через action ``<entity>.create``."""
        ...

    def entity_delete(
        self, *, entity: str, id_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Удалить сущность через action ``<entity>.delete``."""
        ...

    def entity_get(
        self, *, entity: str, id_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Прочитать сущность через action ``<entity>.get``."""
        ...

    def entity_list(
        self,
        *,
        entity: str,
        filters_from: Union[str, None] = ...,
        page: Union[int, None] = ...,
        size: Union[int, None] = ...,
        page_from: Union[str, None] = ...,
        size_from: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Получить страницу сущностей через action ``<entity>.list``."""
        ...

    def entity_update(
        self,
        *,
        entity: str,
        id_from: str = ...,
        payload_from: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Обновить сущность через action ``<entity>.update``."""
        ...

    def es_index(
        self, index: str, *, doc_id_from: Union[str, None] = ...
    ) -> RouteBuilder:
        """Индексирует документ из body в ES ``index``."""
        ...

    def es_search(self, index: str, query: dict, *, size: int = ...) -> RouteBuilder:
        """Поиск в ES; hits в ``exchange.properties["_es_hits"]``."""
        ...

    def evaluate_rules(
        self,
        *,
        rules: list[Any],
        context_from: Union[str, None] = ...,
        decision_to: str = ...,
        default_decision: str = ...,
    ) -> RouteBuilder:
        """First-match-wins rule engine поверх SimpleEval."""
        ...

    def exactly_once(
        self,
        storage: Any,
        *,
        id_header: str = ...,
        ttl_seconds: int = ...,
        namespace: str = ...,
    ) -> RouteBuilder:
        """Exactly-once: dedup через storage по message-id."""
        ...

    def excel_read(self, *, sheet_name: Union[str, None] = ...) -> RouteBuilder:
        """Читать Excel файл в list[dict]."""
        ...

    def expire(
        self, ttl_seconds: float, *, header_name: str = ..., drop_action: str = ...
    ) -> RouteBuilder:
        """Message Expiration: отбрасывает сообщения старше ``ttl_seconds``."""
        ...

    def expose_proxy(
        self,
        src: str,
        *,
        methods: Union[list[str], None] = ...,
        header_map: Union[dict[str, Any], None] = ...,
    ) -> RouteBuilder:
        """Объявить роут как прокси-вход."""
        ...

    def express_edit(
        self,
        sync_id_from: str = ...,
        *,
        bot: str = ...,
        body: Union[str, None] = ...,
        body_from: Union[str, None] = ...,
        bubble: Union[list[list[dict[str, Any]]], None] = ...,
        keyboard: Union[list[list[dict[str, Any]]], None] = ...,
        status: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Редактировать ранее отправленное Express сообщение."""
        ...

    def express_mention(
        self,
        *,
        mention_type: str = ...,
        target_from: Union[str, None] = ...,
        mention_id: Union[str, None] = ...,
        name_from: Union[str, None] = ...,
        property_name: str = ...,
    ) -> RouteBuilder:
        """Добавить упоминание (user/chat/channel/contact/all) в exchange-property."""
        ...

    def express_reply(
        self,
        body_from: Union[str, None] = ...,
        *,
        bot: str = ...,
        source_sync_id_from: str = ...,
        chat_id_from: str = ...,
        body: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Ответить на исходное сообщение Express (reply-thread)."""
        ...

    def express_send(
        self,
        body: Union[str, None] = ...,
        *,
        bot: str = ...,
        chat_id_from: str = ...,
        body_from: Union[str, None] = ...,
        bubble: Union[list[list[dict[str, Any]]], None] = ...,
        keyboard: Union[list[list[dict[str, Any]]], None] = ...,
        status: str = ...,
        silent_response: bool = ...,
        sync: bool = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправить сообщение в Express чат через BotX API."""
        ...

    def express_send_file(
        self,
        *,
        bot: str = ...,
        chat_id_from: str = ...,
        s3_key_from: Union[str, None] = ...,
        file_data_property: Union[str, None] = ...,
        file_name: Union[str, None] = ...,
        file_name_from: Union[str, None] = ...,
        body: Union[str, None] = ...,
        body_from: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправить файл (S3/LocalFS или exchange-property) в Express чат."""
        ...

    def express_status(
        self, *, bot: str = ..., sync_id_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Запросить статус доставки сообщения по sync_id."""
        ...

    def express_typing(
        self, action: str = ..., *, bot: str = ..., chat_id_from: str = ...
    ) -> RouteBuilder:
        """Отправить/остановить индикатор набора в Express чате."""
        ...

    def extract(
        self, selector: str, url: Union[str, None] = ..., output_property: str = ...
    ) -> RouteBuilder:
        """Извлечение текста по CSS-селектору."""
        ...

    def fallback(self, processors: list[BaseProcessor]) -> RouteBuilder:
        """Fallback-цепочка: последовательно пробует процессоры, останавливается на первом успехе."""
        ...

    def feature_flag(self, name: str) -> RouteBuilder:
        """Привязывает маршрут к feature flag (можно отключить без рестарта)."""
        ...

    def feature_flag_branch(
        self,
        flag: str,
        processors: list[BaseProcessor],
        *,
        resolver: Union[Callable[[str], bool], None] = ...,
    ) -> RouteBuilder:
        """Выполняет ветку процессоров только при включённом feature flag."""
        ...

    def file_move(
        self,
        src: Union[str, None] = ...,
        dst: Union[str, None] = ...,
        *,
        mode: str = ...,
    ) -> RouteBuilder:
        """Копировать или переместить файл."""
        ...

    def fill_form(
        self, url: str, fields: Union[dict, None] = ..., submit: Union[str, None] = ...
    ) -> RouteBuilder:
        """Заполнение формы по полям + опциональный submit."""
        ...

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> RouteBuilder:
        """Фильтрует Exchange — останавливает, если predicate=False."""
        ...

    def find_all(
        self,
        *,
        predicate: Union[Callable[[Any], bool], None] = ...,
        condition: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Фильтрует коллекцию в body по условию."""
        ...

    def findoc_ocr_llm(self, doc_type: str = ...) -> RouteBuilder:
        """OCR + LLM для финансовых документов."""
        ...

    def flatten(self, *, depth: int = ...) -> RouteBuilder:
        """Расплющивает nested lists в body."""
        ...

    def for_each(
        self,
        items_path: str,
        processors: list[BaseProcessor],
        *,
        copy_exchange: bool = ...,
        max_iterations: int = ...,
    ) -> RouteBuilder:
        """For-Each — iterate over a collection, executing sub-processors for each item."""
        ...

    def forward_to(
        self,
        dst: str,
        *,
        pass_headers: bool = ...,
        header_map: Union[dict[str, Any], None] = ...,
        rewrite_path: Union[str, None] = ...,
        timeout: float = ...,
    ) -> RouteBuilder:
        """Переслать текущее сообщение в backend без трансформаций."""
        ...

    def from_(
        cls: Any, route_id: str, source: str, *, description: Union[str, None] = ...
    ) -> RouteBuilder:
        """Точка входа: создаёт новый RouteBuilder."""
        ...

    def from_base64(self, b64_string: Union[str, None] = ...) -> RouteBuilder:
        """Decode base64 string → ``bytes`` (stdlib ``base64``)."""
        ...

    def from_bencode(self, bcode_bytes: Union[bytes, None] = ...) -> RouteBuilder:
        """Parse bencoded bytes → Python object (no external deps)."""
        ...

    def from_csv(self, csv_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse CSV → ``list[dict]``."""
        ...

    def from_eventbus(
        self, topic_pattern: str, *, ack_mode: str = ..., name: Union[str, None] = ...
    ) -> RouteBuilder:
        """Subscribe маршрут на EventBus topic_pattern (V22 NEW)."""
        ...

    def from_excel(self, excel_bytes: Union[bytes, None] = ...) -> RouteBuilder:
        """Parse Excel bytes → ``list[dict]`` (openpyxl)."""
        ...

    def from_file(
        self,
        path: str,
        *,
        pattern: Union[str, None] = ...,
        recursive: bool = ...,
        poll_interval_s: float = ...,
    ) -> RouteBuilder:
        """Camel-style ``from("file:directory?pattern=*")`` — file sensor trigger."""
        ...

    def from_html_unescape(self, html_string: Union[str, None] = ...) -> RouteBuilder:
        """HTML-unescape string (entities → ``<>&"'`` chars)."""
        ...

    def from_http(
        self,
        url: str,
        *,
        expected_status: int = ...,
        method: str = ...,
        body_match: Union[str, None] = ...,
        poll_interval_s: float = ...,
    ) -> RouteBuilder:
        """Camel-style ``from("http:url")`` — HTTP sensor trigger."""
        ...

    def from_imap(
        cls: Any,
        route_id: str,
        host: str,
        port: int,
        user: str,
        password: str,
        *,
        folder: str = ...,
        subject_filter: Union[str, None] = ...,
        from_filter: Union[str, None] = ...,
        **kwargs: Any,
    ) -> RouteBuilder:
        """Фабричный метод: маршрут с источником IMAP IDLE (K3 W5)."""
        ...

    def from_ini(self, ini_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse INI → ``dict`` (stdlib ``configparser``)."""
        ...

    def from_interval(
        self,
        interval_s: float,
        *,
        start_immediately: bool = ...,
        payload: Union[dict[str, Any], None] = ...,
    ) -> RouteBuilder:
        """Camel-style ``from("timer:foo?period=...")`` — periodic trigger."""
        ...

    def from_json(self, *, from_property: str = ...) -> RouteBuilder:
        """Parse JSON string → ``dict``/``list`` в ``out_message.body``."""
        ...

    def from_jwt(
        self, jwt_string: Union[str, None] = ..., *, secret: str, algorithm: str = ...
    ) -> RouteBuilder:
        """Decode JWT ``str`` → claims ``dict`` (verify HS* signature via joserfc)."""
        ...

    def from_markdown(self, md_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse markdown → ``dict`` (extracts ``# heading`` → content)."""
        ...

    def from_msgpack(self, msgpack_bytes: Union[bytes, None] = ...) -> RouteBuilder:
        """Parse msgpack → ``dict``/``list`` (fallback: ``pickle``)."""
        ...

    def from_nats_js(
        cls: Any,
        route_id: str,
        subject: str,
        stream: str,
        durable: str,
        *,
        nats_url: str = ...,
        description: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Точка входа: маршрут из NATS JetStream durable consumer."""
        ...

    def from_parquet(self, parquet_bytes: Union[bytes, None] = ...) -> RouteBuilder:
        """Parse parquet → ``list[dict]`` (pyarrow)."""
        ...

    def from_protobuf_like(self, pb_bytes: Union[bytes, None] = ...) -> RouteBuilder:
        """Decode base64-encoded JSON ``bytes`` → ``dict`` (inverse of to_protobuf_like)."""
        ...

    def from_registered_source(
        cls: Any, route_id: str, source_id: str, *, description: Union[str, None] = ...
    ) -> RouteBuilder:
        """Точка входа W23: маршрут запитывается от зарегистрированного Source."""
        ...

    def from_s3(
        self,
        bucket: str,
        key: str,
        *,
        region: str = ...,
        endpoint_url: Union[str, None] = ...,
        poll_interval_s: float = ...,
    ) -> RouteBuilder:
        """Camel-style ``from("aws-s3:bucket/key")`` — S3 sensor trigger."""
        ...

    def from_sql(
        self,
        dsn: str,
        query: str,
        *,
        predicate: Union[str, None] = ...,
        poll_interval_s: float = ...,
    ) -> RouteBuilder:
        """Camel-style ``from("sql:...")`` — SQL sensor trigger."""
        ...

    def from_toml(self, toml_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse TOML → ``dict`` (``tomllib`` stdlib 3.11+)."""
        ...

    def from_url_encoded(self, url_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse URL-encoded string → ``dict`` (multi-value → ``list``)."""
        ...

    def from_webdav(
        cls: Any,
        route_id: str,
        url: str,
        *,
        watch_path: str = ...,
        poll_interval_seconds: int = ...,
        file_pattern: str = ...,
        username: Union[str, None] = ...,
        password: Union[str, None] = ...,
        processed_marker_path: Union[str, None] = ...,
        marker_dedup: bool = ...,
        description: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Точка входа: WebDAV polling-источник (S13 K3 W2, INF-2.8)."""
        ...

    def from_webhook(self, path: str, *, method: str = ...) -> RouteBuilder:
        """Camel-style ``from("http:host/path")`` — HTTP webhook trigger."""
        ...

    def from_xml(self, xml_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse XML → ``dict`` (через ``xmltodict`` если есть, иначе stdlib)."""
        ...

    def from_yaml(self, yaml_string: Union[str, None] = ...) -> RouteBuilder:
        """Parse YAML → ``dict``/``list``."""
        ...

    def get_feedback_examples(
        self,
        *,
        query_from: str = ...,
        agent_id: Union[str, None] = ...,
        positive_k: int = ...,
        negative_k: int = ...,
        min_similarity: float = ...,
        inject_as: str = ...,
    ) -> RouteBuilder:
        """Few-shot примеры из AI Feedback RAG."""
        ...

    def get_setting(
        self, path: str, *, to: str = ..., default: Any = ...
    ) -> RouteBuilder:
        """Чтение настройки из application config (R-V15-17)."""
        ...

    def graphql_query(
        self,
        endpoint: str,
        query: str,
        *,
        variables: Union[dict[str, Any], None] = ...,
        operation_name: Union[str, None] = ...,
        headers: Union[dict[str, str], None] = ...,
        auth_token: Union[str, None] = ...,
        auth_header: str = ...,
        timeout: float = ...,
        result_property: Union[str, None] = ...,
    ) -> RouteBuilder:
        """GraphQL query/mutation executor."""
        ...

    def group_by(
        self,
        *,
        field: Union[str, None] = ...,
        key_fn: Union[Callable[[Any], Any], None] = ...,
    ) -> RouteBuilder:
        """Группирует коллекцию в body по полю."""
        ...

    def group_by_key(
        self,
        key_path: str,
        sink: Callable[[dict[Any, list[Any]]], Any],
        *,
        window_seconds: float = ...,
    ) -> RouteBuilder:
        """Группировка по ключу (jmespath) в пределах окна."""
        ...

    def guardrails(
        self,
        *,
        max_length: int = ...,
        blocked_patterns: Union[list[str], None] = ...,
        required_fields: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Проверка LLM output на безопасность (длина, blocklist, required fields)."""
        ...

    def guardrails_apply(
        self,
        *,
        stage: str = ...,
        source_property: Union[str, None] = ...,
        on_block: str = ...,
        categories: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Content safety через Llama Guard 3 (S27 W2)."""
        ...

    def hash(self, *, algorithm: str = ...) -> RouteBuilder:
        """Хеширование тела сообщения."""
        ...

    def hitl_approval(
        self,
        hitl_service: Any,
        *,
        title: str,
        description: str = ...,
        approvers: Union[list[str], None] = ...,
        timeout_seconds: float = ...,
        payload_path: Union[str, None] = ...,
        request_info_processors: Union[list[BaseProcessor], None] = ...,
    ) -> RouteBuilder:
        """HITL-approval: приостанавливает pipeline, ожидает approve/reject от оператора."""
        ...

    def http_call(
        self,
        url: str,
        *,
        method: str = ...,
        headers: Union[dict[str, str], None] = ...,
        auth_token: Union[str, None] = ...,
        timeout: float = ...,
        result_property: Union[str, None] = ...,
    ) -> RouteBuilder:
        """HTTP client: GET/POST/PUT/DELETE с таймаутом и headers."""
        ...

    def idempotent(
        self, key_expression: Callable[[Exchange[Any]], str], *, ttl_seconds: int = ...
    ) -> RouteBuilder:
        """Идемпотентный consumer: дедупликация через Redis SET NX EX."""
        ...

    def image_resize(
        self,
        *,
        width: Union[int, None] = ...,
        height: Union[int, None] = ...,
        output_format: str = ...,
    ) -> RouteBuilder:
        """Изменить размер изображения."""
        ...

    def include(self, other: Pipeline) -> RouteBuilder:
        """Включает все процессоры из другого Pipeline (композиция)."""
        ...

    def intersect(self, other: list[Any]) -> RouteBuilder:
        """Пересечение body с другим списком."""
        ...

    def invoke(
        self,
        action: str,
        *,
        mode: str = ...,
        payload_factory: Union[Callable[[Exchange[Any]], dict[str, Any]], None] = ...,
        reply_channel: Union[str, None] = ...,
        result_property: str = ...,
        invocation_id_property: str = ...,
        timeout: Union[float, None] = ...,
        correlation_id: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Вызывает action через :class:`Invoker` (W22) с заданным режимом."""
        ...

    def invoke_workflow(
        self,
        name: str,
        *,
        mode: str = ...,
        args: Union[dict[str, Any], None] = ...,
        namespace: str = ...,
        task_queue: str = ...,
        result_property: str = ...,
        invocation_id_property: str = ...,
        reply_timeout_seconds: float = ...,
        version: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Запуск Workflow (Temporal/LiteTemporal/PgRunner) — R-V15-7 / R-V15-9."""
        ...

    def jdbc_query(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Execute arbitrary SQL against an external JDBC-compatible database profile."""
        ...

    def jinja_template(
        self,
        template_string: str,
        *,
        context_from: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Рендерит Jinja2-шаблон из строки."""
        ...

    def jinja_template_file(
        self, path: str, *, context_from: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Рендерит Jinja2-шаблон из файла."""
        ...

    def jwt_sign(
        self,
        *,
        secret_key: str,
        algorithm: str = ...,
        expires_in_seconds: Union[int, None] = ...,
        output_property: str = ...,
    ) -> RouteBuilder:
        """Подпись payload как JWT-токен (PyJWT)."""
        ...

    def jwt_verify(
        self,
        *,
        secret_key: str,
        algorithm: str = ...,
        header: str = ...,
        output_property: str = ...,
    ) -> RouteBuilder:
        """Проверка JWT из заголовка; claims → property или fail."""
        ...

    def keystroke_replay(self, script_name: str) -> RouteBuilder:
        """Воспроизведение записанного сценария клавиатуры/мыши."""
        ...

    def kyc_aml_verify(self, jurisdiction: str = ...) -> RouteBuilder:
        """KYC/AML верификация клиента."""
        ...

    def lineage(self, tag: str = ...) -> RouteBuilder:
        """Записывает шаг в `_lineage` property (data governance)."""
        ...

    def llm_structured(
        self,
        *,
        model: str,
        output_schema: Any,
        prompt: str,
        retry: int = ...,
        temperature: float = ...,
        cost_budget_usd: Union[float, None] = ...,
        to: str = ...,
        name: Union[str, None] = ...,
    ) -> RouteBuilder:
        """LLM-вызов с гарантированным Pydantic-объектом."""
        ...

    def load_balance(
        self,
        targets: list[str],
        *,
        strategy: str = ...,
        weights: Union[list[float], None] = ...,
        sticky_header: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Load Balancer: round_robin/random/weighted/sticky распределение."""
        ...

    def load_memory(self, session_id_header: str = ...) -> RouteBuilder:
        """Загрузка conversation/facts из AgentMemory (Redis)."""
        ...

    def log(self, level: str = ...) -> RouteBuilder:
        """Логирование текущего состояния Exchange (для отладки)."""
        ...

    def loop(
        self,
        processors: list[BaseProcessor],
        *,
        count: Union[int, None] = ...,
        until: Union[Callable[[Exchange[Any]], bool], None] = ...,
        max_iterations: int = ...,
    ) -> RouteBuilder:
        """Loop — execute sub-processors N times or until condition."""
        ...

    def mask(
        self, *, patterns: Union[list[str], None] = ..., replacement: str = ...
    ) -> RouteBuilder:
        """Маскирование PII/PCI в body (ИНН/СНИЛС/карта/email/телефон)."""
        ...

    def mask_pii(
        self,
        *,
        targets: list[str],
        fields: Union[list[str], None] = ...,
        replacement: str = ...,
        patterns: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Маскировка PII в request/response (Sprint 8A K1 W4)."""
        ...

    def max_by(self, field: str) -> RouteBuilder:
        """Максимум по полю элементов коллекции."""
        ...

    def mcp_tool(
        self, uri: str, tool: str, *, result_property: str = ...
    ) -> RouteBuilder:
        """Вызов внешнего MCP tool."""
        ...

    def min_by(self, field: str) -> RouteBuilder:
        """Минимум по полю элементов коллекции."""
        ...

    def ml_predict(
        self,
        model: str,
        *,
        input_field: str = ...,
        output_property: str = ...,
        model_type: Union[str, None] = ...,
        name: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Выполняет ML-инференс через локальный filesystem model registry."""
        ...

    def mongo_find(
        self, collection: str, query: dict, *, to_property: str = ...
    ) -> RouteBuilder:
        """FIND документов в Mongo; результат в ``exchange.properties[to_property]``."""
        ...

    def mongo_insert(
        self, collection: str, *, document_from: str = ...
    ) -> RouteBuilder:
        """INSERT документа в Mongo ``collection``."""
        ...

    def multicast(
        self, sinks: list[str], *, parallel: bool = ..., name: Union[str, None] = ...
    ) -> RouteBuilder:
        """Multicast EIP — fan-out to multiple sinks (parallel by default)."""
        ...

    def multicast_routes(
        self,
        route_ids: list[str],
        *,
        strategy: str = ...,
        on_error: str = ...,
        timeout: float = ...,
    ) -> RouteBuilder:
        """Fan-out на зарегистрированные DSL-маршруты по route_id."""
        ...

    def navigate(self, url: str) -> RouteBuilder:
        """Открыть URL в браузере (Playwright)."""
        ...

    def normalize(self, target_schema: Union[type, None] = ...) -> RouteBuilder:
        """Normalizer: автоопределение формата (XML/CSV/YAML/JSON) → canonical dict."""
        ...

    def notify(
        self,
        channel: str = ...,
        *,
        template_key: str = ...,
        recipient: Union[str, None] = ...,
        priority: str = ...,
        locale: str = ...,
        context_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправка уведомления через NotificationGateway (Wave 8.3)."""
        ...

    def notify_apprise(
        self,
        channel: str,
        title: str,
        body: str,
        *,
        body_format: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправка уведомления через Apprise (S3 K3 W1, 100+ backends)."""
        ...

    def notify_multi(
        self,
        channels: list[str],
        title: str,
        body: str,
        *,
        body_format: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправка уведомления в несколько Apprise-каналов одновременно (S3 K3 W1)."""
        ...

    def ocr(self, *, lang: str = ...) -> RouteBuilder:
        """OCR — оптическое распознавание текста из изображений/PDF."""
        ...

    def on_completion(
        self,
        processors: list["BaseProcessor"],
        *,
        on_success_only: bool = ...,
        on_failure_only: bool = ...,
    ) -> RouteBuilder:
        """OnCompletion — запуск callback после окончания pipeline (как finally)."""
        ...

    def on_error(
        self,
        *,
        action: Union[str, None] = ...,
        processors: Union[list[BaseProcessor], None] = ...,
        dlq_stream: str = ...,
    ) -> RouteBuilder:
        """Глобальный error handler для pipeline — оборачивает ВСЕ накопленные процессоры."""
        ...

    def or_else(self, *, default: Any) -> RouteBuilder:
        """Подставляет значение по умолчанию, если body пустое/None."""
        ...

    def outbox(self, *, topic: str) -> RouteBuilder:
        """Transactional Outbox: запись события в outbox-таблицу."""
        ...

    def paginate(
        self,
        *,
        next_selector: str = ...,
        item_selector: Union[str, None] = ...,
        max_pages: int = ...,
        start_url: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Multi-page crawling с защитой от циклов и лимитом страниц."""
        ...

    def parallel(
        self, branches: dict[str, list[BaseProcessor]], *, strategy: str = ...
    ) -> RouteBuilder:
        """Параллельное выполнение именованных веток. strategy: all|first."""
        ...

    def parse_llm_output(self, schema: Union[type, None] = ...) -> RouteBuilder:
        """Парсинг LLM-ответа в Pydantic-модель (с попыткой извлечь JSON)."""
        ...

    def partition(
        self,
        *,
        field: Union[str, None] = ...,
        predicate: Union[Callable[[Any], bool], None] = ...,
    ) -> RouteBuilder:
        """Разбивает коллекцию на два списка: подходящие и нет."""
        ...

    def pdf_merge(self) -> RouteBuilder:
        """Объединить несколько PDF в один."""
        ...

    def pdf_read(self, *, extract_tables: bool = ...) -> RouteBuilder:
        """Извлечь текст и таблицы из PDF."""
        ...

    def pii_mask(
        self,
        *,
        scope: str,
        source_property: str = ...,
        target_property: Union[str, None] = ...,
        language: str = ...,
    ) -> RouteBuilder:
        """Reversible PII tokenization через PIITokenizer (S27 W2, ADR-NEW-21)."""
        ...

    def pii_unmask(
        self,
        *,
        source_property: str = ...,
        target_property: Union[str, None] = ...,
        token_map_property: str = ...,
        scope: str = ...,
        strict: bool = ...,
    ) -> RouteBuilder:
        """Восстановить PII по ``token_map`` от ``pii_mask`` (S27 W2)."""
        ...

    def plan_execute(
        self,
        *,
        planner_workflow_id: str,
        executor_workflow_id: str,
        verifier_workflow_id: str,
        max_replans: int = ...,
        plan_output_property: str = ...,
        result_property: str = ...,
        timeout_s: float = ...,
    ) -> RouteBuilder:
        """Plan-and-Execute agentic pattern с verification + replan (S39 W2)."""
        ...

    def plan_execute_with_callbacks(
        self,
        *,
        planner: PlannerFn,
        executor: ExecutorFn,
        verifier: VerifierFn | None = ...,
        max_steps: int = ...,
        max_replans: int = ...,
    ) -> RouteBuilder:
        """Добавить :class:`PlanExecuteProcessor` в pipeline."""
        ...

    def poll(
        self,
        source_action: str,
        *,
        payload: Union[dict[str, Any], None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Periodically вызывает action, результат → body."""
        ...

    def process(self, processor: BaseProcessor) -> RouteBuilder:
        """Добавляет произвольный процессор в pipeline."""
        ...

    def process_fn(
        self,
        func: Callable[[Exchange[Any], "ExecutionContext"], Union[Any, Awaitable[Any]]],
        *,
        name: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Добавляет обычную функцию или coroutine как процессор."""
        ...

    def protocol(self, proto: ProtocolType) -> RouteBuilder:
        """Привязывает маршрут к конкретному протоколу (REST/SOAP/gRPC/...)."""
        ...

    def proxy(
        self,
        src: str,
        dst: str,
        *,
        methods: Union[list[str], None] = ...,
        pass_headers: bool = ...,
        header_map: Union[dict[str, Any], None] = ...,
        rewrite_path: Union[str, None] = ...,
        timeout: float = ...,
    ) -> RouteBuilder:
        """Сокращение: ``expose_proxy(src) → forward_to(dst)``."""
        ...

    def publish_event(self, channel: str) -> RouteBuilder:
        """Публикация события через EventBus."""
        ...

    def purge_channel(
        self, broker: Any, channel: str, *, dry_run: bool = ...
    ) -> RouteBuilder:
        """Очистка очереди/стрима (admin-операция)."""
        ...

    def rag_ingest(
        self,
        *,
        collection: str = ...,
        source_property: Union[str, None] = ...,
        modal: str = ...,
        output_property: str = ...,
    ) -> RouteBuilder:
        """RAG ingest: добавление документа из body/property в vector store (S11 K3 W2)."""
        ...

    def rag_query(
        self,
        *,
        query_field: str = ...,
        top_k: int = ...,
        namespace: Union[str, None] = ...,
        strategy: str = ...,
        max_staleness_hours: Union[float, None] = ...,
        system_prompt: str = ...,
        output_property: str = ...,
    ) -> RouteBuilder:
        """RAG query с выбором стратегии retrieval (S11 K3 W3)."""
        ...

    def rag_search(
        self,
        query_field: str = ...,
        top_k: int = ...,
        namespace: Union[str, None] = ...,
    ) -> RouteBuilder:
        """RAG vector search: top-K ближайших документов по семантике."""
        ...

    def read_file(
        self, path: Union[str, None] = ..., *, binary: bool = ...
    ) -> RouteBuilder:
        """Чтение локального файла в body (text или bytes)."""
        ...

    def read_s3(
        self, bucket: Union[str, None] = ..., key: Union[str, None] = ...
    ) -> RouteBuilder:
        """Загрузка объекта из S3."""
        ...

    def recipient_list(
        self,
        recipients: Union[list[str], Callable[[Exchange[Any]], list[str]]],
        *,
        parallel: bool = ...,
        name: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Recipient List EIP — list or callable ``(exchange) -> list``."""
        ...

    def redirect(
        self,
        target_url: Union[str, None] = ...,
        *,
        status_code: int = ...,
        url_source: Union[str, None] = ...,
        source_key: Union[str, None] = ...,
        allowed_hosts: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Добавляет HTTP-redirect в маршрут."""
        ...

    def redis_delete(self, key: str) -> RouteBuilder:
        """``DEL key`` в Redis."""
        ...

    def redis_get(self, key: str, *, default: Any = ...) -> RouteBuilder:
        """``GET key`` в Redis; ``default`` при отсутствии ключа."""
        ...

    def redis_set(
        self, key: str, value: str, *, ttl_seconds: Union[int, None] = ...
    ) -> RouteBuilder:
        """``SET key value [EX ttl]`` в Redis. ``ttl_seconds=None`` = бессрочно."""
        ...

    def reflection_loop(
        self,
        *,
        generator: GeneratorFn,
        critic: CriticFn,
        max_refinements: int = ...,
        score_threshold: float = ...,
    ) -> RouteBuilder:
        """Добавить :class:`ReflectionLoopProcessor` в pipeline."""
        ...

    def reflection_loop_workflow(
        self,
        *,
        generator_workflow_id: str,
        reflector_workflow_id: str,
        refiner_workflow_id: Union[str, None] = ...,
        max_iterations: int = ...,
        stop_verdict: str = ...,
        result_property: str = ...,
        history_property: Union[str, None] = ...,
        timeout_s: float = ...,
    ) -> RouteBuilder:
        """Generate → Reflect → Refine agentic pattern via workflows (S39 W3)."""
        ...

    def regex(
        self, pattern: str, *, action: str = ..., replacement: str = ...
    ) -> RouteBuilder:
        """Извлечь или заменить текст по регулярному выражению."""
        ...

    def register_filter(self, name: str, fn: Callable[..., Any]) -> RouteBuilder:
        """Register custom Jinja2 filter (chainable)."""
        ...

    def render_document(
        self,
        template_path: PathLike,
        output_path: PathLike,
        context: Context | None = ...,
    ) -> int:
        """Render template file → output file. Returns bytes written."""
        ...

    def render_docx(
        self,
        *,
        template: str,
        context_from: Union[str, None] = ...,
        output_to: str = ...,
    ) -> RouteBuilder:
        """Рендерит шаблон ``.docx`` со встроенными плейсхолдерами ``{{key}}``."""
        ...

    def render_email(
        self, subject_template: str, body_template: str, context: Context | None = ...
    ) -> tuple[str, str]:
        """Render email subject + body. Returns ``(subject, body)`` tuple."""
        ...

    def render_file(
        self, template_path: PathLike, context: Context | None = ...
    ) -> str:
        """Render Jinja2 template из файла (str | Path)."""
        ...

    def render_template(self, template: str) -> RouteBuilder:
        """Рендеринг Jinja2-шаблона."""
        ...

    def render_xlsx(
        self,
        *,
        template: Union[str, None] = ...,
        context_from: Union[str, None] = ...,
        output_to: str = ...,
        mode: str = ...,
    ) -> RouteBuilder:
        """Рендерит ``.xlsx`` (``replace`` placeholders или ``append_table``)."""
        ...

    def reply(
        self,
        reply_channel: Union[str, None] = ...,
        payload: Any = ...,
        *,
        correlation_id: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Публикует reply в ``reply_channel`` (reply_to)."""
        ...

    def reply_to(
        self, broker: Any, *, reply_to_header: str = ..., correlation_header: str = ...
    ) -> RouteBuilder:
        """Return Address: публикует ответ в очередь из reply-to заголовка."""
        ...

    def request(
        self,
        target_channel: str,
        payload: Any = ...,
        *,
        timeout: float = ...,
        correlation_id: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправляет запрос в ``target_channel`` и ждёт reply."""
        ...

    def require_auth(self) -> RouteBuilder:
        """DX-2: валидирует API key или Bearer token."""
        ...

    def require_bearer(self) -> RouteBuilder:
        """DX-2: валидирует Bearer token в Authorization header."""
        ...

    def require_fields(self, *names: str) -> RouteBuilder:
        """DX-2: валидирует что в body есть указанные поля."""
        ...

    def require_header(self, name: str) -> RouteBuilder:
        """DX-2: валидирует присутствие header. Fail route если отсутствует."""
        ...

    def resequence(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        sequence_field: str = ...,
        batch_size: int = ...,
        timeout_seconds: float = ...,
    ) -> RouteBuilder:
        """Resequencer: восстановление порядка сообщений по sequence_field."""
        ...

    def restore_pii(self) -> RouteBuilder:
        """Восстановление PII в ответе после LLM."""
        ...

    def retry(
        self,
        processors: list[BaseProcessor],
        *,
        max_attempts: int = ...,
        delay_seconds: float = ...,
        backoff: str = ...,
    ) -> RouteBuilder:
        """Retry с backoff: повторяет процессоры при ошибке. backoff: fixed|exponential."""
        ...

    def router_specialist(
        self,
        *,
        llm_router: LLMRouterFn,
        specialists: list[SpecialistAgent],
        fallback_specialist: Union[str, None] = ...,
        min_confidence: float = ...,
    ) -> RouteBuilder:
        """Добавить :class:`RouterSpecialistProcessor` в pipeline."""
        ...

    def routing_slip(
        self,
        steps: Union[Callable[[Exchange[Any]], Any], list[str]],
        *,
        header: Union[str, None] = ...,
        strict: bool = ...,
        max_steps: int = ...,
    ) -> RouteBuilder:
        """Routing Slip EIP: динамическая цепочка processors per-message."""
        ...

    def run_scenario(self, steps: Union[list[dict], None] = ...) -> RouteBuilder:
        """Multi-step web сценарий (navigate/click/fill/extract)."""
        ...

    def s3_put(self, key: str, *, body_from: str = ...) -> RouteBuilder:
        """PUT объекта в S3 по ``key`` (body из ``body_from``)."""
        ...

    def saga(self, steps: list[SagaStep]) -> RouteBuilder:
        """Saga-паттерн: последовательные шаги с компенсацией при ошибке."""
        ...

    def saga_lra(
        self,
        steps: list[SagaStep],
        *,
        workflow_id: Union[str, None] = ...,
        run_id: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Saga LRA: долгоживущая сага с persistent checkpoints."""
        ...

    def sample(self, probability: float = ...) -> RouteBuilder:
        """Вероятностный сэмплинг (A/B, canary, debug-sampling)."""
        ...

    def sampling(
        self,
        *,
        rate: Union[int, None] = ...,
        fraction: Union[float, None] = ...,
        time_window_ms: Union[int, None] = ...,
        max_in_window: Union[int, None] = ...,
        seed: Union[int, None] = ...,
    ) -> RouteBuilder:
        """Sampling EIP: probabilistic subset of messages."""
        ...

    def sanitize_pii(self) -> RouteBuilder:
        """Маскирование PII (email/phone/СНИЛС/карт) перед LLM."""
        ...

    def save_memory(self) -> RouteBuilder:
        """Сохранение результата в AgentMemory."""
        ...

    def scan_file(
        self,
        *,
        s3_key_from: Union[str, None] = ...,
        data_property: Union[str, None] = ...,
        on_threat: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Сканировать файл AV-бэкендом (Wave 2.4)."""
        ...

    def scatter_gather(
        self,
        route_ids: list[str],
        *,
        aggregation: str = ...,
        timeout_seconds: float = ...,
    ) -> RouteBuilder:
        """Scatter-Gather: fan-out на N маршрутов + сборка результатов."""
        ...

    def schedule(self, *, cron: str, timezone_name: str = ...) -> RouteBuilder:
        """Defer execution по cron-расписанию (Airflow-style ``schedule_interval``)."""
        ...

    def schema_validate(self, schema: dict[str, Any]) -> RouteBuilder:
        """Валидация body по JSON Schema (Draft 2020-12)."""
        ...

    def scrape(
        self,
        url: Union[str, None] = ...,
        *,
        selectors: Union[dict[str, str], None] = ...,
        output_property: str = ...,
    ) -> RouteBuilder:
        """Извлечение данных с URL через CSS-селекторы (с SSRF-защитой)."""
        ...

    def screenshot(self, url: Union[str, None] = ...) -> RouteBuilder:
        """Скриншот страницы как bytes."""
        ...

    def script_node(
        self,
        code: str,
        *,
        timeout_seconds: float = ...,
        env: Union[dict[str, str], None] = ...,
        allowed_languages: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Выполнить inline Node.js-код (требует ``node`` в PATH)."""
        ...

    def script_python(
        self,
        code: str,
        *,
        timeout_seconds: float = ...,
        env: Union[dict[str, str], None] = ...,
        allowed_languages: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Выполнить inline Python-код через текущий интерпретатор."""
        ...

    def script_ruby(
        self,
        code: str,
        *,
        timeout_seconds: float = ...,
        env: Union[dict[str, str], None] = ...,
        allowed_languages: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Выполнить inline Ruby-код (требует ``ruby`` в PATH)."""
        ...

    def script_shell(
        self,
        code: str,
        *,
        timeout_seconds: float = ...,
        env: Union[dict[str, str], None] = ...,
        allowed_languages: Union[list[str], None] = ...,
    ) -> RouteBuilder:
        """Выполнить shell-скрипт через ``/bin/sh`` (whitelist рекомендуется)."""
        ...

    def semantic_route(
        self,
        intents: dict[str, str],
        *,
        default_route: Union[str, None] = ...,
        query_field: str = ...,
        threshold: float = ...,
        namespace: str = ...,
    ) -> RouteBuilder:
        """Semantic routing — RAG-based intent detection → выбор маршрута."""
        ...

    def session_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        gap_seconds: float = ...,
        watermark_store: WatermarkStore | None = ...,
    ) -> RouteBuilder:
        """Streaming session-окно (закрывается по паузе)."""
        ...

    def set_header(self, key: str, value: Any) -> RouteBuilder:
        """Устанавливает заголовок в in_message."""
        ...

    def set_property(self, key: str, value: Any) -> RouteBuilder:
        """Устанавливает runtime-свойство Exchange."""
        ...

    def shadow_mode(self, processors: list[BaseProcessor]) -> RouteBuilder:
        """Исполняет вложенную ветку в shadow-режиме (без side effects)."""
        ...

    def shell(
        self,
        command: str,
        *,
        args: Union[list[str], None] = ...,
        allowed_commands: Union[list[str], None] = ...,
        timeout_seconds: float = ...,
    ) -> RouteBuilder:
        """Выполнить shell-команду."""
        ...

    def sink_email(
        self,
        *,
        host: str,
        from_addr: str,
        port: int = ...,
        username: Union[str, None] = ...,
        password: Union[str, None] = ...,
        use_tls: bool = ...,
        start_tls: bool = ...,
        default_to: Union[str, None] = ...,
        default_subject: str = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для SMTP-публикации (Sprint 3 W1 K3)."""
        ...

    def sink_file(
        self,
        *,
        path: str,
        mode: str = ...,
        encoding: str = ...,
        ensure_dir: bool = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для записи в local FS (append / write)."""
        ...

    def sink_grpc(
        self,
        *,
        target: str,
        full_method: str,
        secure: bool = ...,
        timeout: float = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для gRPC unary-вызова (Sprint 3 W1 K3)."""
        ...

    def sink_http(
        self,
        *,
        url: str,
        method: str = ...,
        headers: Union[dict[str, str], None] = ...,
        timeout: float = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для REST POST/PUT/PATCH/DELETE через Sink."""
        ...

    def sink_mq(
        self,
        *,
        broker: str,
        url: str,
        topic: str,
        extra: Union[dict[str, Any], None] = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для публикации в Kafka/RabbitMQ/Redis-Streams/NATS."""
        ...

    def sink_mqtt(
        self,
        *,
        host: str,
        topic: str,
        port: Union[int, None] = ...,
        qos: int = ...,
        retain: bool = ...,
        username: Union[str, None] = ...,
        password: Union[str, None] = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для публикации в MQTT-брокер."""
        ...

    def sink_s3(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для выгрузки payload в S3/MinIO."""
        ...

    def sink_soap(
        self,
        *,
        wsdl_url: str,
        operation: str,
        service_name: Union[str, None] = ...,
        port_name: Union[str, None] = ...,
        timeout: float = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для SOAP/WSDL-вызова (Sprint 3 W1 K3)."""
        ...

    def sink_webhook(
        self,
        *,
        url: str,
        event: str,
        secret: Union[str, None] = ...,
        timeout: float = ...,
        extra_headers: Union[dict[str, str], None] = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для outbound webhook с HMAC-подписью."""
        ...

    def sink_ws(
        self,
        *,
        url: str,
        extra_headers: Union[dict[str, str], None] = ...,
        timeout: float = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Camel-style fluent для outbound WebSocket publish."""
        ...

    def skill_invoke(
        self,
        *,
        skill_id: str,
        params_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Вызов AI skill через :class:`SkillRegistry.invoke` (S27 W3, ADR-NEW-22)."""
        ...

    def sliding_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        window_seconds: float = ...,
        step_seconds: float = ...,
        watermark_store: WatermarkStore | None = ...,
    ) -> RouteBuilder:
        """Streaming sliding-окно с перекрытием."""
        ...

    def sort(
        self,
        *,
        key_fn: Union[Callable[[Any], Any], None] = ...,
        key_field: Union[str, None] = ...,
        reverse: bool = ...,
    ) -> RouteBuilder:
        """Sort — сортировка list body по функции ключа или имени поля."""
        ...

    def sort_by(self, field: str, *, reverse: bool = ...) -> RouteBuilder:
        """Сортировка коллекции по полю."""
        ...

    def split(self, expression: str, processors: list[BaseProcessor]) -> RouteBuilder:
        """Splitter: разбиение массива на отдельные Exchange по JMESPath."""
        ...

    def sql_exec(self, query: str, *, params: Union[dict, None] = ...) -> RouteBuilder:
        """INSERT/UPDATE/DELETE с bind-параметрами ``:name``."""
        ...

    def sse_source(
        self, url: str, event_types: Union[list[str], None] = ...
    ) -> RouteBuilder:
        """Source-процессор для Server-Sent Events."""
        ...

    def ssh_exec(
        self,
        host: str,
        command: str,
        *,
        username: Union[str, None] = ...,
        password_from: str = ...,
        key_file: Union[str, None] = ...,
        timeout: float = ...,
        result_property: str = ...,
        continue_on_error: bool = ...,
    ) -> RouteBuilder:
        """Выполняет remote-команду через SSH (asyncssh)."""
        ...

    def sum_by(self, field: str) -> RouteBuilder:
        """Сумма по полю элементов коллекции."""
        ...

    def switch(
        self,
        field: str,
        cases: dict[str, list[BaseProcessor]],
        *,
        default: Union[list[BaseProcessor], None] = ...,
    ) -> RouteBuilder:
        """n8n Switch — case/match роутинг по значению поля."""
        ...

    def telegram_edit(
        self,
        message_id_from: str = ...,
        *,
        bot: str = ...,
        chat_id_from: str = ...,
        body: Union[str, None] = ...,
        body_from: Union[str, None] = ...,
        parse_mode: str = ...,
        inline_keyboard: Union[list[list[dict[str, Any]]], None] = ...,
    ) -> RouteBuilder:
        """Редактировать ранее отправленное Telegram-сообщение."""
        ...

    def telegram_mention(
        self,
        *,
        user_id_from: str,
        display_name_from: Union[str, None] = ...,
        parse_mode: str = ...,
        property_name: str = ...,
        append: bool = ...,
    ) -> RouteBuilder:
        """Создать фрагмент-упоминание пользователя для вставки в текст."""
        ...

    def telegram_reply(
        self,
        body_from: Union[str, None] = ...,
        *,
        bot: str = ...,
        source_message_id_from: str = ...,
        chat_id_from: str = ...,
        body: Union[str, None] = ...,
        parse_mode: str = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Ответить на сообщение Telegram (reply_to_message_id)."""
        ...

    def telegram_send(
        self,
        body: Union[str, None] = ...,
        *,
        bot: str = ...,
        chat_id_from: str = ...,
        body_from: Union[str, None] = ...,
        parse_mode: str = ...,
        inline_keyboard: Union[list[list[dict[str, Any]]], None] = ...,
        reply_keyboard: Union[list[list[str]], None] = ...,
        disable_notification: bool = ...,
        disable_web_page_preview: bool = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправить сообщение в Telegram чат через Bot API."""
        ...

    def telegram_send_file(
        self,
        *,
        bot: str = ...,
        chat_id_from: str = ...,
        s3_key_from: Union[str, None] = ...,
        file_data_property: Union[str, None] = ...,
        file_name: Union[str, None] = ...,
        file_name_from: Union[str, None] = ...,
        body: Union[str, None] = ...,
        body_from: Union[str, None] = ...,
        parse_mode: str = ...,
        disable_notification: bool = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Отправить файл (документ) в Telegram чат."""
        ...

    def telegram_status(
        self, *, bot: str = ..., result_property: str = ...
    ) -> RouteBuilder:
        """Запросить профиль бота (getMe) — health-check Telegram."""
        ...

    def telegram_typing(
        self, action: str = ..., *, bot: str = ..., chat_id_from: str = ...
    ) -> RouteBuilder:
        """Отправить chat-action (typing / upload_photo / …) в Telegram."""
        ...

    def template_render_str(
        self, template_str: str, context: Context | None = ...
    ) -> str:
        """Render Jinja2 template из строки. Returns rendered string."""
        ...

    def tenant_scope(
        self,
        *,
        header: str = ...,
        body_path: Union[str, None] = ...,
        required: bool = ...,
    ) -> RouteBuilder:
        """Multi-tenancy scope: tenant_id из заголовка/body в Exchange."""
        ...

    def terminal_3270(
        self, host: str, port: int = ..., action: str = ...
    ) -> RouteBuilder:
        """IBM 3270 терминал-эмулятор (мейнфрейм)."""
        ...

    def throttle(self, rate: float, *, burst: int = ...) -> RouteBuilder:
        """Throttler: rate-limit N сообщений/сек (token bucket)."""
        ...

    def timeout(
        self,
        processors: list[BaseProcessor],
        *,
        seconds: float = ...,
        fallback_processors: Union[list[BaseProcessor], None] = ...,
    ) -> RouteBuilder:
        """Timeout — wrap sub-processors with a time limit."""
        ...

    def timer(
        self,
        *,
        interval_seconds: Union[float, None] = ...,
        cron: Union[str, None] = ...,
        max_fires: Union[int, None] = ...,
    ) -> RouteBuilder:
        """Scheduled event source: интервал или cron-выражение."""
        ...

    def to(self, processor: BaseProcessor) -> RouteBuilder:
        """Алиас для process() — fluent naming."""
        ...

    def to_avro_like(self, schema: Union[dict[str, Any], None] = ...) -> RouteBuilder:
        """Convert ``dict`` → JSON ``str`` c обёрткой ``{"schema": ..., "data": ...}``."""
        ...

    def to_base64(self) -> RouteBuilder:
        """Encode ``bytes``/``str`` → base64 string (stdlib ``base64``)."""
        ...

    def to_bencode(self) -> RouteBuilder:
        """Convert ``dict``/``list`` → bencoded bytes (bitTorrent metafile)."""
        ...

    def to_compact_json(self) -> RouteBuilder:
        """Convert ``dict`` → minified JSON ``str`` (no indent, no spaces)."""
        ...

    def to_csv(self, *, headers: Union[list[str], None] = ...) -> RouteBuilder:
        """Convert ``list[dict]`` → CSV string."""
        ...

    def to_eventbus(
        self, topic: str, *, payload_ref: str = ..., name: Union[str, None] = ...
    ) -> RouteBuilder:
        """Publish текущий exchange в EventBus topic (V22 NEW)."""
        ...

    def to_excel(self, *, sheet_name: str = ...) -> RouteBuilder:
        """Convert ``list[dict]`` → Excel bytes (openpyxl)."""
        ...

    def to_html_escape(self) -> RouteBuilder:
        """HTML-escape string (``<>&"'`` → entities, ``quote=True``)."""
        ...

    def to_ini(self) -> RouteBuilder:
        """Convert ``dict`` → INI string (stdlib ``configparser``)."""
        ...

    def to_json(self, *, indent: Union[int, None] = ...) -> RouteBuilder:
        """Serialize ``exchange.body`` → JSON string в ``out_message.body``."""
        ...

    def to_jwt(
        self,
        *,
        secret: str,
        algorithm: str = ...,
        claims: Union[dict[str, Any], None] = ...,
    ) -> RouteBuilder:
        """Encode ``exchange.body`` (dict) → JWT string (HS256 default)."""
        ...

    def to_markdown(self) -> RouteBuilder:
        """Convert ``dict`` → markdown string (``# key`` per top-level key)."""
        ...

    def to_msgpack(self) -> RouteBuilder:
        """Convert ``dict``/``list`` → msgpack bytes (fallback: ``pickle``)."""
        ...

    def to_nats_js(
        self,
        subject: str,
        *,
        nats_url: str = ...,
        headers: Union[dict[str, str], None] = ...,
        payload_property: Union[str, None] = ...,
        result_property: str = ...,
    ) -> RouteBuilder:
        """Публикует payload в NATS JetStream (Sink step)."""
        ...

    def to_parquet(self, *, compression: str = ...) -> RouteBuilder:
        """Convert ``list[dict]`` → parquet bytes (pyarrow)."""
        ...

    def to_protobuf_like(self) -> RouteBuilder:
        """Convert ``dict`` → base64-encoded JSON ``bytes`` (protobuf-like wire format)."""
        ...

    def to_route(self, route_id: str, *, result_property: str = ...) -> RouteBuilder:
        """Вызов другого зарегистрированного DSL-маршрута."""
        ...

    def to_toml(self) -> RouteBuilder:
        """Convert ``dict`` → TOML string (``tomli_w``)."""
        ...

    def to_url_encoded(self) -> RouteBuilder:
        """Convert ``dict`` → URL-encoded string (application/x-www-form-urlencoded)."""
        ...

    def to_uuid_string(self) -> RouteBuilder:
        """Generate UUID4 string (``body`` ignored, always fresh)."""
        ...

    def to_xml(self, *, root_tag: str = ...) -> RouteBuilder:
        """Convert ``dict`` → XML string (stdlib ``xml.etree.ElementTree``)."""
        ...

    def to_yaml(self) -> RouteBuilder:
        """Convert ``dict``/``list`` → YAML string."""
        ...

    def token_budget(self, max_tokens: int = ...) -> RouteBuilder:
        """Ограничение по токенам (tiktoken) — обрезка текста до лимита."""
        ...

    def transform(self, expression: str) -> RouteBuilder:
        """Трансформирует body через JMESPath-выражение."""
        ...

    def translate(self, from_format: str, to_format: str) -> RouteBuilder:
        """DEPRECATED: используйте .convert(). translate() — alias для обратной совместимости."""
        ...

    def transport(self, config: TransportConfig) -> RouteBuilder:
        """Настройки транспорта (endpoint, timeout, retry_count, options)."""
        ...

    def tumbling_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        size: int = ...,
        interval_seconds: float = ...,
        watermark_store: WatermarkStore | None = ...,
    ) -> RouteBuilder:
        """Streaming tumbling-окно фиксированного размера."""
        ...

    def tx_categorize(self, taxonomy: str = ...) -> RouteBuilder:
        """Категоризация транзакций (MCC + merchant normalization)."""
        ...

    def unique(
        self,
        *,
        field: Union[str, None] = ...,
        key_fn: Union[Callable[[Any], Any], None] = ...,
    ) -> RouteBuilder:
        """Уникальные элементы коллекции."""
        ...

    def validate(self, model: type) -> RouteBuilder:
        """Pydantic-валидация body; при ошибке Exchange останавливается."""
        ...

    def validate_response(
        self,
        *,
        schema: Union[type, str, None] = ...,
        on_error: str = ...,
        source: str = ...,
    ) -> RouteBuilder:
        """Pydantic-валидация response_body (R-V15-18)."""
        ...

    def validate_schema(
        self, subject: str, *, schema_loader: Any = ...
    ) -> RouteBuilder:
        """Валидация по схеме из реестра (JSON Schema / Avro / Protobuf)."""
        ...

    def web_search(
        self,
        engine: str = ...,
        *,
        query: Union[str, None] = ...,
        query_source: Union[str, None] = ...,
        max_results: int = ...,
        to: str = ...,
        deep_research: bool = ...,
    ) -> RouteBuilder:
        """K3 S5 W9 — web-поиск через WebSearchService (Tavily/Perplexity/SearXNG)."""
        ...

    def webhook_sign(
        self, *, secret: str, header: str = ..., algorithm: str = ...
    ) -> RouteBuilder:
        """HMAC-подпись outgoing webhook'а."""
        ...

    def webhook_verify(
        self,
        *,
        secret: str,
        header: str = ...,
        algorithm: str = ...,
        prefix: Union[str, None] = ...,
        on_mismatch: str = ...,
    ) -> RouteBuilder:
        """Верификация HMAC-подписи входящего webhook'а (timing-safe)."""
        ...

    def windowed_collect(
        self,
        key_from: str,
        dedup_by: str,
        *,
        window_seconds: int = ...,
        dedup_mode: str = ...,
        inject_as: str = ...,
    ) -> RouteBuilder:
        """Накопление и батч-дедупликация сообщений в окне."""
        ...

    def windowed_dedup(
        self,
        key_from: str,
        *,
        key_prefix: str = ...,
        window_seconds: int = ...,
        mode: str = ...,
    ) -> RouteBuilder:
        """Дедупликация в скользящем окне с Redis-персистентностью."""
        ...

    def wire_tap(
        self, sink: str, *, async_: bool = ..., name: Union[str, None] = ...
    ) -> RouteBuilder:
        """Wire Tap EIP — copy exchange to ``sink`` (async by default)."""
        ...

    def with_auth(
        self,
        *,
        token: Union[str, None] = ...,
        api_key: Union[str, None] = ...,
        mtls_cert: Union[str, None] = ...,
    ) -> RouteBuilder:
        """Переопределяет auth для предыдущего step."""
        ...

    def with_headers(self, headers: dict[str, str], *, mode: str = ...) -> RouteBuilder:
        """Переопределяет HTTP-заголовки предыдущего step."""
        ...

    def with_retries(
        self, max_attempts: int, *, backoff: Union[str, float, None] = ...
    ) -> RouteBuilder:
        """Переопределяет количество попыток retry для предыдущего step."""
        ...

    def with_timeout(self, seconds: float) -> RouteBuilder:
        """Переопределяет timeout последнего step."""
        ...

    def word_read(self) -> RouteBuilder:
        """Извлечь текст из .docx файла."""
        ...

    def word_write(self) -> RouteBuilder:
        """Генерировать .docx документ из текста."""
        ...

    def write_file(
        self, path: Union[str, None] = ..., *, format: str = ...
    ) -> RouteBuilder:
        """Запись body в файл. format: auto|json|csv|text."""
        ...

    def write_s3(
        self,
        bucket: Union[str, None] = ...,
        key: Union[str, None] = ...,
        *,
        content_type: str = ...,
    ) -> RouteBuilder:
        """Выгрузка body в S3."""
        ...
