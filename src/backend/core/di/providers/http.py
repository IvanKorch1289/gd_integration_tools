"""HTTP/transport domain providers — HTTP, SMTP, Express, browser, stream, factories.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 31 funcs (16 get + 15 set) + 1 private helper
(``_noop_express_metrics_recorder``).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_INFRA = "src." + "backend.infrastructure"

_overrides: dict[str, Any] = {}


# ─────────────── HTTP-клиент (Wave 6.3, services/ai/ai_agent.py) ───────────────


def get_http_client_provider() -> Any:
    """Возвращает singleton ``HttpClient`` (см. ``HttpClientProtocol``)."""
    if "http_client" in _overrides:
        return _overrides["http_client"]
    module = resolve_module("clients.transport.http")
    return module.get_http_client_dependency()


def set_http_client_provider(client: Any) -> None:
    _overrides["http_client"] = client


# ─────────────── SMTP client ───────────────


def get_smtp_client_provider() -> Any:
    """Возвращает singleton ``SmtpClient`` (см. ``SmtpClientProtocol``)."""
    if "smtp_client" in _overrides:
        return _overrides["smtp_client"]
    module = resolve_module("clients.transport.smtp")
    return module.smtp_client


def set_smtp_client_provider(client: Any) -> None:
    _overrides["smtp_client"] = client


# ─────────────── Express messenger client ───────────────


def get_express_client_provider() -> Any:
    """Возвращает singleton ``ExpressClient`` (см. ``ExpressClientProtocol``)."""
    if "express_client" in _overrides:
        return _overrides["express_client"]
    module = resolve_module("clients.external.express")
    return module.get_express_client()


def set_express_client_provider(client: Any) -> None:
    _overrides["express_client"] = client


# ─────────────── Express dialog/session stores (Mongo) ───────────────


def get_express_dialog_store_provider() -> Any:
    """Возвращает singleton ``MongoExpressDialogStore``."""
    if "express_dialog_store" in _overrides:
        return _overrides["express_dialog_store"]
    module = resolve_module("repos.express_dialogs")
    return module.get_express_dialog_store()


def set_express_dialog_store_provider(store: Any) -> None:
    _overrides["express_dialog_store"] = store


def get_express_session_store_provider() -> Any:
    """Возвращает singleton ``MongoExpressSessionStore``."""
    if "express_session_store" in _overrides:
        return _overrides["express_session_store"]
    module = resolve_module("repos.express_sessions")
    return module.get_express_session_store()


def set_express_session_store_provider(store: Any) -> None:
    _overrides["express_session_store"] = store


# ─────────────── Express metrics recorder ───────────────


def get_express_metrics_recorder_provider() -> Any:
    """Возвращает callable ``record_express_command_received``.

    Если функция отсутствует (минимальный профиль без prometheus_client),
    возвращается no-op.
    """
    if "express_metrics_recorder" in _overrides:
        return _overrides["express_metrics_recorder"]
    module = resolve_module("observability.metrics")
    return getattr(
        module, "record_express_command_received", _noop_express_metrics_recorder
    )


def set_express_metrics_recorder_provider(recorder: Any) -> None:
    _overrides["express_metrics_recorder"] = recorder


def _noop_express_metrics_recorder(bot: str, command: str) -> None:
    """Заглушка, если backend метрик недоступен."""
    return


# ─────────────── Express BotX client / factory / message class ───────────────


def get_express_bot_client_factory_provider() -> Any:
    """Возвращает фабрику ``get_express_client(bot_name)`` для Express BotX.

    Реализация: ``dsl.engine.processors.express._common.get_express_client``.
    Этот common-модуль нагружает infra-клиент через ленивый импорт.
    """
    if "express_bot_client_factory" in _overrides:
        return _overrides["express_bot_client_factory"]
    module = resolve_module("dsl.processors.express_common")
    return module.get_express_client


def set_express_bot_client_factory_provider(factory: Any) -> None:
    _overrides["express_bot_client_factory"] = factory


def get_express_botx_message_class_provider() -> Any:
    """Возвращает класс ``BotxMessage`` (DTO для Express)."""
    if "express_botx_message_class" in _overrides:
        return _overrides["express_botx_message_class"]
    module = resolve_module("clients.external.express_bot")
    return module.BotxMessage


# ─────────────── Browser automation ───────────────


def get_browser_client_provider() -> Any:
    """Возвращает singleton ``BrowserClient`` (см. ``BrowserClientProtocol``)."""
    if "browser_client" in _overrides:
        return _overrides["browser_client"]
    module = resolve_module("clients.transport.browser")
    return module.get_browser_client()


def set_browser_client_provider(client: Any) -> None:
    _overrides["browser_client"] = client


# ─────────────── External DB session manager ───────────────


def get_external_session_manager_provider() -> Any:
    """Возвращает фабрику ``DatabaseSessionManager`` для внешних БД.

    Реализация: ``infrastructure.database.session_manager
    .get_external_session_manager`` — фабрика, принимающая ``profile_name``.
    """
    if "external_session_manager" in _overrides:
        return _overrides["external_session_manager"]
    module = resolve_module("database.session_manager")
    return module.get_external_session_manager


def set_external_session_manager_provider(factory: Any) -> None:
    _overrides["external_session_manager"] = factory


# ─────────────── Import gateway factory (W24 ImportService) ───────────────


def get_import_gateway_factory_provider() -> Any:
    """Возвращает фабрику ``build_import_gateway(kind)`` для W24 ImportService.

    Реализация: ``infrastructure.import_gateway.build_import_gateway``.
    """
    if "import_gateway_factory" in _overrides:
        return _overrides["import_gateway_factory"]
    module = resolve_module("import_gateway")
    return module.build_import_gateway


def set_import_gateway_factory_provider(factory: Any) -> None:
    _overrides["import_gateway_factory"] = factory


# ─────────────── Redis coordinator primitives ───────────────


def get_redis_hash_factory_provider() -> Any:
    """Возвращает класс ``RedisHash`` (фабрика per-key инстансов)."""
    if "redis_hash_factory" in _overrides:
        return _overrides["redis_hash_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisHash


def set_redis_hash_factory_provider(factory: Any) -> None:
    _overrides["redis_hash_factory"] = factory


def get_redis_set_factory_provider() -> Any:
    """Возвращает класс ``RedisSet`` (фабрика per-key инстансов)."""
    if "redis_set_factory" in _overrides:
        return _overrides["redis_set_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisSet


def set_redis_set_factory_provider(factory: Any) -> None:
    _overrides["redis_set_factory"] = factory


def get_redis_pubsub_factory_provider() -> Any:
    """Возвращает класс ``RedisPubSub`` (фабрика per-channel инстансов)."""
    if "redis_pubsub_factory" in _overrides:
        return _overrides["redis_pubsub_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisPubSub


def set_redis_pubsub_factory_provider(factory: Any) -> None:
    _overrides["redis_pubsub_factory"] = factory


def get_redis_cursor_factory_provider() -> Any:
    """Возвращает класс ``RedisCursor`` (CAS-cursor)."""
    if "redis_cursor_factory" in _overrides:
        return _overrides["redis_cursor_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisCursor


def set_redis_cursor_factory_provider(factory: Any) -> None:
    _overrides["redis_cursor_factory"] = factory


# ─────────────── FastStream client (subscriber decorators) ───────────────


def get_stream_client_provider() -> Any:
    """Возвращает singleton ``StreamClient`` (FastStream роутеры)."""
    if "stream_client" in _overrides:
        return _overrides["stream_client"]
    module = resolve_module("clients.messaging.stream")
    return module.stream_client


def set_stream_client_provider(client: Any) -> None:
    _overrides["stream_client"] = client


__all__ = (
    "get_browser_client_provider",
    "get_express_bot_client_factory_provider",
    "get_express_botx_message_class_provider",
    "get_express_client_provider",
    "get_express_dialog_store_provider",
    "get_express_metrics_recorder_provider",
    "get_express_session_store_provider",
    "get_external_session_manager_provider",
    "get_http_client_provider",
    "get_import_gateway_factory_provider",
    "get_redis_cursor_factory_provider",
    "get_redis_hash_factory_provider",
    "get_redis_pubsub_factory_provider",
    "get_redis_set_factory_provider",
    "get_smtp_client_provider",
    "get_stream_client_provider",
    "set_browser_client_provider",
    "set_express_bot_client_factory_provider",
    "set_express_client_provider",
    "set_express_dialog_store_provider",
    "set_express_metrics_recorder_provider",
    "set_express_session_store_provider",
    "set_external_session_manager_provider",
    "set_http_client_provider",
    "set_import_gateway_factory_provider",
    "set_redis_cursor_factory_provider",
    "set_redis_hash_factory_provider",
    "set_redis_pubsub_factory_provider",
    "set_redis_set_factory_provider",
    "set_smtp_client_provider",
    "set_stream_client_provider",
)
