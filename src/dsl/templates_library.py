"""DSL Templates Library — готовые параметризованные шаблоны.

Каждый шаблон — функция, принимающая параметры → возвращающая Pipeline.
Идеально для джунов: скопировал, подставил параметры, готово.

Примеры:
    from app.dsl.templates_library import templates

    # ETL из PostgreSQL в ClickHouse
    pipeline = templates["etl.postgres_to_clickhouse"](
        source_query="SELECT * FROM orders",
        target_table="analytics.orders",
    )

    # Парсинг сайта по cron
    pipeline = templates["web.scrape_scheduled"](
        url="https://example.com/prices",
        selector=".price",
        cron="0 */2 * * *",
    )
"""

from __future__ import annotations

from typing import Any, Callable

from app.dsl.builder import RouteBuilder
from app.dsl.engine.pipeline import Pipeline

__all__ = ("templates", "list_templates", "TemplateInfo")


class TemplateInfo:
    __slots__ = ("name", "description", "parameters", "builder")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, str],
        builder: Callable[..., Pipeline],
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.builder = builder


def _etl_postgres_to_clickhouse(
    source_query: str,
    target_table: str,
    route_id: str = "etl.pg_to_ch",
    cron: str | None = None,
) -> Pipeline:
    """ETL: PostgreSQL query → ClickHouse insert."""
    source = f"cron:{cron}" if cron else "internal:etl"
    return (
        RouteBuilder.from_(route_id, source=source, description="ETL PG→CH")
        .set_property("query", source_query)
        .dispatch_action("external_db.query")
        .dispatch_action("analytics.insert_batch")
        .log("ETL complete")
        .build()
    )


def _web_scrape_scheduled(
    url: str,
    selector: str,
    cron: str = "0 */2 * * *",
    route_id: str = "scrape.scheduled",
    target_action: str = "analytics.insert_batch",
) -> Pipeline:
    """Парсинг сайта по расписанию + сохранение."""
    return (
        RouteBuilder.from_(route_id, source=f"cron:{cron}", description="Scheduled scraping")
        .navigate(url)
        .extract(selector, url=url, output_property="items")
        .dispatch_action(target_action)
        .build()
    )


def _notify_on_event(
    event_source: str,
    email: str,
    subject_template: str,
    route_id: str = "notify.event",
) -> Pipeline:
    """Отправка email при событии."""
    return (
        RouteBuilder.from_(route_id, source=event_source, description="Email notification")
        .set_header("to", email)
        .set_header("subject", subject_template)
        .dispatch_action("tech.send_email")
        .log(f"Notification sent to {email}")
        .build()
    )


def _ai_qa_with_rag(
    question_field: str = "question",
    top_k: int = 5,
    provider: str | None = None,
    route_id: str = "ai.qa_rag",
) -> Pipeline:
    """AI Q&A с RAG — поиск → prompt → LLM → parse."""
    return (
        RouteBuilder.from_(route_id, source="internal:ai", description="AI Q&A with RAG")
        .rag_search(query_field=question_field, top_k=top_k)
        .compose_prompt(
            template="Контекст:\n{context}\n\nВопрос: {question}\nОтвет:",
            context_property="vector_results",
        )
        .token_budget(max_tokens=4096)
        .sanitize_pii()
        .call_llm(provider=provider)
        .restore_pii()
        .build()
    )


def _safe_external_call(
    action: str,
    max_retries: int = 3,
    dlq: bool = True,
    route_id: str | None = None,
) -> Pipeline:
    """Безопасный вызов external API с retry + DLQ."""
    rid = route_id or f"safe.{action}"
    from app.dsl.macros import safe_action

    return safe_action(
        route_id=rid,
        action=action,
        max_retries=max_retries,
        dlq_action=f"{action}.dlq" if dlq else None,
    )


def _crud_with_audit(
    entity: str,
    create_action: str,
    update_action: str,
    delete_action: str,
) -> list[Pipeline]:
    """CRUD + audit + event publishing."""
    from app.dsl.macros import crud_with_audit

    return crud_with_audit(
        route_id_prefix=entity,
        create_action=create_action,
        update_action=update_action,
        delete_action=delete_action,
        event_channel=f"events.{entity}",
    )


def _scheduled_export(
    source_action: str,
    format: str = "excel",
    email: str | None = None,
    cron: str = "0 9 * * MON",
    route_id: str = "export.weekly",
) -> Pipeline:
    """Еженедельный экспорт отчёта + отправка email."""
    builder = (
        RouteBuilder.from_(route_id, source=f"cron:{cron}", description="Scheduled export")
        .dispatch_action(source_action)
        .export(format=format, title="Weekly Report")
    )
    if email:
        builder = builder.set_header("to", email).dispatch_action("tech.send_email")
    return builder.build()


templates: dict[str, TemplateInfo] = {
    "etl.postgres_to_clickhouse": TemplateInfo(
        name="ETL PostgreSQL → ClickHouse",
        description="Загрузка данных из PG в CH для аналитики",
        parameters={
            "source_query": "SQL запрос (SELECT ...)",
            "target_table": "Таблица в ClickHouse",
            "route_id": "ID маршрута",
            "cron": "Расписание (опционально)",
        },
        builder=_etl_postgres_to_clickhouse,
    ),
    "web.scrape_scheduled": TemplateInfo(
        name="Парсинг сайта по расписанию",
        description="Извлечение данных с сайта по CSS-селектору, сохранение в БД",
        parameters={
            "url": "URL страницы",
            "selector": "CSS-селектор",
            "cron": "Расписание",
            "target_action": "Action для сохранения",
        },
        builder=_web_scrape_scheduled,
    ),
    "notify.on_event": TemplateInfo(
        name="Email-уведомление при событии",
        description="Отправка email при получении события из queue/webhook",
        parameters={
            "event_source": "Источник события (queue:name, webhook:path)",
            "email": "Адрес получателя",
            "subject_template": "Тема письма",
        },
        builder=_notify_on_event,
    ),
    "ai.qa_with_rag": TemplateInfo(
        name="AI Q&A с RAG",
        description="Семантический поиск + prompt + LLM + PII mask",
        parameters={
            "question_field": "Поле с вопросом",
            "top_k": "Количество результатов RAG",
            "provider": "LLM провайдер",
        },
        builder=_ai_qa_with_rag,
    ),
    "safe.external_call": TemplateInfo(
        name="Безопасный вызов external API",
        description="Retry с экспоненциальным backoff + DLQ при фейле",
        parameters={
            "action": "Имя action для вызова",
            "max_retries": "Максимум попыток",
            "dlq": "Использовать Dead Letter Queue",
        },
        builder=_safe_external_call,
    ),
    "crud.with_audit": TemplateInfo(
        name="CRUD с аудитом",
        description="3 маршрута (create/update/delete) с публикацией событий",
        parameters={
            "entity": "Имя сущности (orders, users)",
            "create_action": "Action для создания",
            "update_action": "Action для обновления",
            "delete_action": "Action для удаления",
        },
        builder=_crud_with_audit,
    ),
    "export.scheduled": TemplateInfo(
        name="Экспорт отчёта по расписанию",
        description="Weekly/monthly Excel/PDF отчёт + email",
        parameters={
            "source_action": "Action для получения данных",
            "format": "excel/csv/pdf",
            "email": "Email для отправки",
            "cron": "Расписание",
        },
        builder=_scheduled_export,
    ),
}


def list_templates() -> list[dict[str, Any]]:
    """Возвращает список всех шаблонов для UI."""
    return [
        {
            "id": key,
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for key, t in templates.items()
    ]
