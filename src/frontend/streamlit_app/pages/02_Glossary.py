"""Glossary & FAQ — словарь терминов."""

import streamlit as st

st.set_page_config(page_title="Glossary", page_icon=":book:", layout="wide")
st.header("Словарь терминов и FAQ")

tab_glossary, tab_faq = st.tabs(["Словарь", "FAQ"])

# ─────────── Glossary ───────────

with tab_glossary:
    TERMS = {
        "Action": {
            "description": "Именованная команда, вызывающая метод сервиса. Пример: orders.create.",
            "example": 'action_handler_registry.dispatch("orders.create", payload={...})',
            "related": ["ActionHandlerRegistry", "Service"],
        },
        "ActionHandlerRegistry": {
            "description": "Центральный реестр всех actions. Single source of truth для всех протоколов.",
            "example": "Все REST/gRPC/GraphQL/MQ используют один реестр.",
            "related": ["Action", "Service"],
        },
        "Exchange": {
            "description": "Контейнер данных между шагами pipeline. Содержит in_message, out_message, properties.",
            "example": "exchange.in_message.body — входящие данные",
            "related": ["Pipeline", "Message"],
        },
        "Message": {
            "description": "Объект с body и headers внутри Exchange.",
            "example": "exchange.in_message.body, exchange.in_message.headers",
            "related": ["Exchange"],
        },
        "Pipeline": {
            "description": "Последовательность процессоров = готовый маршрут.",
            "example": "RouteBuilder.from_(...)...build() → Pipeline",
            "related": ["Processor", "RouteBuilder", "Route"],
        },
        "Processor": {
            "description": "Одиночный шаг обработки данных. Получает Exchange, модифицирует его.",
            "example": "DispatchActionProcessor, ValidateProcessor, LogProcessor",
            "related": ["Pipeline", "BaseProcessor"],
        },
        "RouteBuilder": {
            "description": "Fluent API для создания Pipeline методом цепочек.",
            "example": "RouteBuilder.from_().validate().dispatch_action().build()",
            "related": ["Pipeline"],
        },
        "Route / Маршрут": {
            "description": "Зарегистрированный Pipeline с route_id. Доступен из всех протоколов.",
            "example": "route_registry.register(pipeline)",
            "related": ["Pipeline", "RouteRegistry"],
        },
        "Service": {
            "description": "Бизнес-логика: класс с методами (create, update, get...).",
            "example": "OrderService, UserService — наследуют BaseService",
            "related": ["Action", "BaseService"],
        },
        "Middleware": {
            "description": "Прослойка до/после каждого процессора: timeout, metrics, errors.",
            "example": "TimeoutMiddleware, MetricsMiddleware",
            "related": ["ProcessorMiddleware"],
        },
        "Feature Flag": {
            "description": "Переключатель маршрута без деплоя (вкл/выкл).",
            "example": "RouteBuilder.feature_flag('beta_orders')",
            "related": ["Route"],
        },
        "Circuit Breaker": {
            "description": "Защита от каскадных сбоев: временно блокирует сервис после серии ошибок.",
            "example": "CLOSED → OPEN (после N ошибок) → HALF_OPEN → CLOSED",
            "related": ["Resilience"],
        },
        "Correlation ID": {
            "description": "Уникальный ID для связывания логов одного запроса через все сервисы.",
            "example": "В каждом логе: correlation_id=abc123",
            "related": ["Tracing"],
        },
        "DSL": {
            "description": "Domain Specific Language — язык описания маршрутов для интеграций.",
            "example": "RouteBuilder, YAML routes, fluent API",
            "related": ["RouteBuilder", "Pipeline"],
        },
        "DLQ / Dead Letter Queue": {
            "description": "Очередь для упавших сообщений с полным контекстом ошибки.",
            "example": ".do_try(catch=[DeadLetterProcessor(dlq_action='my.dlq')])",
            "related": ["Retry", "Error Handling"],
        },
        "Saga": {
            "description": "Распределённая транзакция с компенсациями при откате.",
            "example": "Создать заказ → Списать деньги → Если упало: Вернуть деньги → Отменить заказ",
            "related": ["Pipeline", "Compensation"],
        },
        "Tenant": {
            "description": "Отдельный клиент/подразделение с изолированными данными.",
            "example": "X-Tenant-ID header → filter queries by tenant_id",
            "related": ["Multi-tenancy"],
        },
    }

    search = st.text_input("Поиск", placeholder="Начните вводить термин...")

    filtered = (
        {
            k: v
            for k, v in TERMS.items()
            if search.lower() in k.lower() or search.lower() in v["description"].lower()
        }
        if search
        else TERMS
    )

    for term, info in sorted(filtered.items()):
        with st.expander(term):
            st.markdown(f"**Описание:** {info['description']}")
            if info.get("example"):
                st.code(info["example"], language="python")
            if info.get("related"):
                st.caption(f"Связанные: {', '.join(info['related'])}")

# ─────────── FAQ ───────────

with tab_faq:
    FAQ = [
        (
            "Как добавить новый маршрут?",
            "Используй RouteBuilder или YAML hot-reload. Файл `*.dsl.yaml` в `config/dsl/` автоматически загружается.",
        ),
        (
            "Как вызвать маршрут через REST?",
            "Маршрут автоматически доступен по `/api/v1/{action_prefix}/{method}`. Проверь `actions` в manage.py.",
        ),
        (
            "Где искать логи?",
            "3 варианта: (1) stdout в debug mode, (2) Graylog в production, (3) `/api/v1/admin/traces` для DSL trace.",
        ),
        (
            "Что делать если сервис недоступен?",
            "Circuit breaker автоматически откроется. Жди recovery_timeout (30s). Смотри /metrics для состояния.",
        ),
        (
            "Как посмотреть все actions?",
            "`make actions` или Streamlit: Routes → Actions.",
        ),
        (
            "Как протестировать pipeline без side-effects?",
            "DSL Playground → включи 'Dry-run'. Или `manage.py validate <route_id>`.",
        ),
        (
            "Как отключить маршрут без деплоя?",
            "Feature flag: в routes/ файле добавь `feature_flag: my_flag`. Toggle через админку.",
        ),
        (
            "Почему мой маршрут не работает через GraphQL?",
            "Убедись что action зарегистрирован в ActionHandlerRegistry. GraphQL генерируется автоматически из реестра.",
        ),
        (
            "Как добавить свой процессор?",
            "1. Отнаследуй BaseProcessor. 2. Зарегистрируй в plugin_registry или entry_points. 3. Используй через `.process(MyProcessor())`.",
        ),
        (
            "Где хранятся секреты?",
            "Vault (production) или .env (dev). Никогда не коммить секреты в код!",
        ),
    ]

    for q, a in FAQ:
        with st.expander(q):
            st.markdown(a)
