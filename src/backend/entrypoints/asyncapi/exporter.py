"""AsyncAPI 3.0 экспортёр поверх FastStream-брокеров.

Использует :class:`faststream.specification.AsyncAPI` (FastStream 0.6+)
и собирает спецификацию из routers, инициализированных в
:class:`StreamClient` (см. ``infrastructure/clients/messaging/stream.py``).

Для каждого настроенного брокера (Redis / RabbitMQ / Kafka) вызываем
``add_broker(...)`` — пропуская те, что отсутствуют (например, Kafka,
если ``settings.kafka`` не определён).

Все import faststream — eager: faststream уже зависимость first-class
проекта (см. ``pyproject.toml``). Если broker не может быть прочитан
(например, тестовый сценарий), функция возвращает спецификацию без
указанных каналов, не падает.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from faststream.specification import Specification

__all__ = ("build_asyncapi_spec", "build_asyncapi_yaml", "build_asyncapi_json")


_DEFAULT_TITLE = "gd_integration_tools"
_DEFAULT_VERSION = "1.0.0"
_DEFAULT_DESCRIPTION = (
    "AsyncAPI 3.0 спецификация интеграционной шины gd_integration_tools."
    " Содержит описание FastStream-источников (Redis / RabbitMQ / Kafka)."
)


def _collect_brokers() -> list[tuple[str, Any]]:
    """Собирает список ``(name, broker)`` из живого ``StreamClient``.

    Брокеры получаем через ``router.broker`` (FastStream Router держит
    реальный broker внутри). Если router не инициализирован
    (settings disabled / отсутствует), запись пропускается.

    StreamClient может не подняться в dev_light / тестовой среде
    (отсутствие зависимостей, версия FastStream без некоторых kwargs) —
    в этом случае возвращаем пустой список, чтобы endpoint отдавал
    корректный AsyncAPI без каналов вместо HTTP 500.
    """
    try:
        from src.backend.infrastructure.clients.messaging.stream import (
            get_stream_client,
        )

        client = get_stream_client()
    except Exception as _:  # noqa: BLE001 — намеренно широкий guard для endpoint resilience
        return []

    pairs: list[tuple[str, Any]] = []

    for attr, label in (
        ("redis_router", "redis"),
        ("rabbit_router", "rabbit"),
        ("kafka_router", "kafka"),
    ):
        router = getattr(client, attr, None)
        if router is None:
            continue
        broker = getattr(router, "broker", None)
        if broker is None:
            continue
        pairs.append((label, broker))

    return pairs


def _empty_spec_dict(title: str, version: str, description: str) -> dict[str, Any]:
    """Минимальный валидный AsyncAPI 3.0.0 без брокеров.

    Используется когда :class:`StreamClient` не поднялся (dev_light /
    тесты / отсутствие зависимостей). Спецификация остаётся валидной
    AsyncAPI 3.0 — пустые ``channels`` и ``operations`` допускаются.
    """
    return {
        "asyncapi": "3.0.0",
        "info": {"title": title, "version": version, "description": description},
        "servers": {},
        "channels": {},
        "operations": {},
        "components": {},
    }


def build_asyncapi_spec(
    title: str = _DEFAULT_TITLE,
    version: str = _DEFAULT_VERSION,
    description: str = _DEFAULT_DESCRIPTION,
) -> Specification | None:
    """Строит :class:`Specification` AsyncAPI 3.0 для текущего ``StreamClient``.

    Args:
        title: Название API в спецификации.
        version: Версия API.
        description: Описание для info-секции.

    Returns:
        ``Specification`` (``to_yaml`` / ``to_json`` / ``to_jsonable``) при
        наличии хотя бы одного broker'а; ``None`` если broker'ов нет —
        тогда вызывающий должен использовать :func:`_empty_spec_dict`.
    """
    from faststream.specification import AsyncAPI

    pairs = _collect_brokers()

    if not pairs:
        return None

    _, first_broker = pairs[0]
    spec = AsyncAPI(
        first_broker,
        title=title,
        version=version,
        description=description,
        schema_version="3.0.0",
    )

    for _, broker in pairs[1:]:
        spec.add_broker(broker)

    return spec.to_specification()


def build_asyncapi_yaml(
    title: str = _DEFAULT_TITLE,
    version: str = _DEFAULT_VERSION,
    description: str = _DEFAULT_DESCRIPTION,
) -> str:
    """Возвращает AsyncAPI 3.0 YAML-строку."""
    spec = build_asyncapi_spec(title, version, description)
    if spec is not None:
        return spec.to_yaml()

    import yaml

    return yaml.safe_dump(
        _empty_spec_dict(title, version, description),
        sort_keys=False,
        allow_unicode=True,
    )


def build_asyncapi_json(
    title: str = _DEFAULT_TITLE,
    version: str = _DEFAULT_VERSION,
    description: str = _DEFAULT_DESCRIPTION,
) -> str:
    """Возвращает AsyncAPI 3.0 JSON-строку."""
    spec = build_asyncapi_spec(title, version, description)
    if spec is not None:
        return spec.to_json()

    import json

    return json.dumps(_empty_spec_dict(title, version, description), indent=2)
