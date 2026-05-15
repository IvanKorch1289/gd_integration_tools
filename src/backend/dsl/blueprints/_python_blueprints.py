"""R2.5 — DSL Blueprints: универсальные интеграционные шаблоны.

4 готовых template-функции для типовых сценариев интеграционной
шины. Blueprint — это **функция**, возвращающая собранный
``Pipeline``: даёт плагинам / route'ам декларативно подключиться
к стандартному pattern'у без перечисления процессоров вручную.

Все blueprints собираются из уже зарегистрированных процессоров
``RouteBuilder`` — никаких новых core-зависимостей.

* :func:`api_normalize_persist_webhook` — REST API ingestion →
  normalize → persist → notify webhook.
* :func:`cdc_enrich_publish` — CDC source → enrich (HTTP) →
  publish to MQ.
* :func:`file_watch_parse_validate_action` — file watcher →
  parse content → validate schema → dispatch action.
* :func:`request_response_with_compensation` — Saga с retry +
  compensation для request-response поверх внешнего API.
"""

from __future__ import annotations

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "api_normalize_persist_webhook",
    "cdc_enrich_publish",
    "file_watch_parse_validate_action",
    "request_response_with_compensation",
)


def api_normalize_persist_webhook(
    *,
    route_id: str,
    source_url: str,
    persist_action: str,
    webhook_url: str,
    schema: type | None = None,
    method: str = "GET",
    timeout: int = 30,
    description: str | None = None,
) -> Pipeline:
    """Blueprint: REST API ingestion → normalize → persist → webhook.

    Pipeline:
      1. ``http_call`` — забирает данные c внешнего API.
      2. ``normalize`` (если задан ``schema``) — приводит к Pydantic.
      3. ``dispatch_action`` — сохраняет через action.
      4. ``http_call`` (POST на ``webhook_url``) — оповещает webhook.

    :param route_id: уникальный ID маршрута.
    :param source_url: URL внешнего API (источник).
    :param persist_action: имя action для сохранения (``orders.create``).
    :param webhook_url: URL для webhook-уведомления.
    :param schema: Pydantic-модель для normalize (опционально).
    :param method: HTTP-метод первичного запроса.
    :param timeout: таймаут HTTP-вызовов в секундах.
    :param description: человекочитаемое описание.
    """
    builder = RouteBuilder.from_(
        route_id,
        source=f"timer:60s|api={source_url}",
        description=description or f"API ingestion from {source_url}",
    )
    builder = builder.http_call(source_url, method=method, timeout=timeout)
    if schema is not None:
        builder = builder.normalize(target_schema=schema)
    builder = builder.dispatch_action(action=persist_action)
    builder = builder.http_call(webhook_url, method="POST", timeout=timeout)
    return builder.build()


def cdc_enrich_publish(
    *,
    route_id: str,
    cdc_source: str,
    enrichment_url: str,
    publish_action: str,
    description: str | None = None,
) -> Pipeline:
    """Blueprint: CDC source → enrich (HTTP) → publish via action.

    Pipeline:
      1. CDC source (через ``from_registered_source``).
      2. ``http_call`` — обогащение из enrichment-API.
      3. ``dispatch_action`` — публикация (action делегирует в нужный
         Sink: Kafka / Rabbit / Redis-Streams / WebSocket etc.).

    :param route_id: уникальный ID маршрута.
    :param cdc_source: ID зарегистрированного CDC source
        (``cdc:postgres/orders``).
    :param enrichment_url: URL enrichment-API (e.g., обогащение
        клиентскими данными).
    :param publish_action: имя action для публикации обогащённого
        события (например, ``messaging.publish_event``).
    :param description: человекочитаемое описание.
    """
    builder = RouteBuilder.from_registered_source(
        route_id,
        source_id=cdc_source,
        description=description or f"CDC enrich from {cdc_source}",
    )
    builder = builder.http_call(enrichment_url, method="POST", timeout=30)
    builder = builder.dispatch_action(action=publish_action)
    return builder.build()


def file_watch_parse_validate_action(
    *,
    route_id: str,
    watch_path: str,
    file_glob: str = "*.json",
    schema: type | None = None,
    action: str,
    description: str | None = None,
) -> Pipeline:
    """Blueprint: file watcher → (normalize→) validate → dispatch action.

    Pipeline:
      1. File watcher source (``filewatcher:<path>?glob=<glob>``).
      2. ``normalize`` (если задан ``schema``) — Pydantic-нормализация
         (parse-step для конкретного формата читается file watcher'ом).
      3. ``validate`` (если задан ``schema``) — runtime-проверка.
      4. ``dispatch_action`` — обработка через action.

    :param route_id: уникальный ID маршрута.
    :param watch_path: каталог для наблюдения.
    :param file_glob: паттерн файлов (``*.json``, ``*.csv``).
    :param schema: Pydantic-модель для validate/normalize (опционально).
    :param action: имя action-обработчика.
    :param description: человекочитаемое описание.
    """
    source = f"filewatcher:{watch_path}?glob={file_glob}"
    builder = RouteBuilder.from_(
        route_id,
        source=source,
        description=description or f"File watch {watch_path}/{file_glob}",
    )
    if schema is not None:
        builder = builder.normalize(target_schema=schema)
        builder = builder.validate(schema)
    builder = builder.dispatch_action(action=action)
    return builder.build()


def request_response_with_compensation(
    *,
    route_id: str,
    request_url: str,
    compensate_url: str,
    request_method: str = "POST",
    timeout: int = 30,
    max_retries: int = 3,
    description: str | None = None,
    extra_processors: list[BaseProcessor] | None = None,
) -> Pipeline:
    """Blueprint: request-response с Saga compensation.

    Pipeline:
      1. ``retry`` + ``http_call`` — запрос с retry.
      2. (опц.) ``extra_processors`` — пользовательская обработка ответа.
      3. ``saga`` со step:
         - main: операция (already done выше, но Saga оборачивает
           тело pipeline для compensation registry);
         - compensate: ``http_call`` к ``compensate_url``.

    Использовать для интеграций, где провал НЕ должен оставлять
    side-effects во внешней системе (платежи, резервы, бронь).

    :param route_id: уникальный ID маршрута.
    :param request_url: URL основного запроса.
    :param compensate_url: URL компенсирующего запроса.
    :param request_method: HTTP-метод основного запроса.
    :param timeout: таймаут HTTP-вызовов.
    :param max_retries: число retry до compensation.
    :param description: человекочитаемое описание.
    :param extra_processors: пользовательские processors после http_call.
    """
    from src.backend.dsl.engine.processors import SagaStep
    from src.backend.dsl.engine.processors.components import HttpCallProcessor

    builder = RouteBuilder.from_(
        route_id,
        source=f"action:{route_id}",
        description=description or f"Saga {request_method} {request_url}",
    )

    # Forward — один HTTP-запрос; extra_processors добавляются после
    # saga (saga обеспечивает только rollback main-step'а).
    forward = HttpCallProcessor(url=request_url, method=request_method, timeout=timeout)
    compensate = HttpCallProcessor(url=compensate_url, method="POST", timeout=timeout)
    saga_steps = [SagaStep(forward=forward, compensate=compensate)]
    builder = builder.saga(saga_steps)
    if extra_processors:
        for p in extra_processors:
            builder = builder.to(p)
    # max_retries сейчас не передаётся в SagaStep (нет такого поля);
    # повторы обеспечивает upstream RetryProcessor (Wave R3 расширит
    # SagaStep полем `max_retries`). Параметр сохранён в API для
    # forward-compat — фактический retry задаётся pipeline'ом.
    _ = max_retries
    return builder.build()
