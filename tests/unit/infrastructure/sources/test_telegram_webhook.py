"""S97 W4 — regression-тесты для Telegram webhook source + DSL builder.

Покрывает:

1. ``TelegramUpdate`` dataclass — default values.
2. ``TelegramWebhookSource.validate_webhook_request`` — accepts all if
   no secret, rejects mismatch, accepts match (constant-time).
3. ``TelegramWebhookSource.parse_update`` — message + callback_query + type filter.
4. ``TelegramWebhookSource.compute_webhook_url`` — base URL trailing slash.
5. DSL ``RouteBuilder.from_telegram`` — instantiation + source binding.
"""

from __future__ import annotations


def test_telegram_update_defaults() -> None:
    """``TelegramUpdate`` имеет sane defaults."""
    from src.backend.infrastructure.sources.telegram_webhook import TelegramUpdate

    u = TelegramUpdate(update_id=42)
    assert u.update_id == 42
    assert u.message is None
    assert u.callback_query is None
    assert u.raw == {}


def test_validate_webhook_request_no_secret() -> None:
    """Если ``secret_token`` None — все запросы accepted."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(bot_token="123:ABC")
    assert source.validate_webhook_request(b'{"update_id": 1}', None) is True
    assert source.validate_webhook_request(b"{}", "anything") is True


def test_validate_webhook_request_match() -> None:
    """Secret token match → ``True``."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(bot_token="123:ABC", secret_token="topsecret")
    assert source.validate_webhook_request(b"{}", "topsecret") is True


def test_validate_webhook_request_mismatch() -> None:
    """Secret token mismatch → ``False``."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(bot_token="123:ABC", secret_token="topsecret")
    assert source.validate_webhook_request(b"{}", "wrong-secret") is False
    assert source.validate_webhook_request(b"{}", None) is False


def test_parse_update_message() -> None:
    """Message update → ``TelegramUpdate.message`` set."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(bot_token="123:ABC")
    payload = {
        "update_id": 100,
        "message": {"message_id": 1, "text": "/start", "chat": {"id": 123}},
    }
    u = source.parse_update(payload)
    assert u is not None
    assert u.update_id == 100
    assert u.message == "/start"
    assert u.callback_query is None


def test_parse_update_callback_query() -> None:
    """Callback query update → ``TelegramUpdate.callback_query`` set."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(
        bot_token="123:ABC", allowed_updates=("callback_query",)
    )
    payload = {"update_id": 101, "callback_query": {"id": "cb1", "data": "btn_yes"}}
    u = source.parse_update(payload)
    assert u is not None
    assert u.callback_query == "btn_yes"
    assert u.message is None


def test_parse_update_filtered_out() -> None:
    """Update type NOT в ``allowed_updates`` → ``None``."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(
        bot_token="123:ABC", allowed_updates=("callback_query",)
    )
    payload = {"update_id": 102, "message": {"message_id": 1, "text": "/start"}}
    u = source.parse_update(payload)
    assert u is None


def test_compute_webhook_url_no_trailing_slash() -> None:
    """``compute_webhook_url`` handles base without trailing slash."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(bot_token="123:ABC")
    url = source.compute_webhook_url("https://bot.example.com")
    assert url == "https://bot.example.com/api/v1/telegram/123:ABC"


def test_compute_webhook_url_trailing_slash() -> None:
    """``compute_webhook_url`` strips trailing slash из base URL."""
    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
    )

    source = TelegramWebhookSource(bot_token="123:ABC")
    url = source.compute_webhook_url("https://bot.example.com/")
    assert url == "https://bot.example.com/api/v1/telegram/123:ABC"


def test_dsl_from_telegram_instantiates() -> None:
    """``RouteBuilder.from_telegram`` создаёт валидный builder + source binding."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_telegram(
        "support_bot",
        bot_token="123:ABC",
        secret_token="topsecret",
        allowed_updates=("message", "callback_query"),
    )
    assert b.route_id == "support_bot"
    assert b.source == "telegram:support_bot"
    assert hasattr(b, "_telegram_source")
    assert b._telegram_source.bot_token == "123:ABC"
    assert b._telegram_source.secret_token == "topsecret"
    assert b._telegram_source.allowed_updates == ("message", "callback_query")


def test_dsl_from_telegram_default_allowed_updates() -> None:
    """Default ``allowed_updates`` = ``("message",)``."""
    from src.backend.dsl.builders.base import RouteBuilder

    b = RouteBuilder.from_telegram("simple_bot", bot_token="456:DEF")
    assert b._telegram_source.allowed_updates == ("message",)
    assert b._telegram_source.secret_token is None
    assert b._telegram_source.offset == 0


def test_telegram_mixin_in_sources_mixin_mro() -> None:
    """``TelegramSourcesMixin`` доступен через :class:`SourcesMixin`."""
    from src.backend.dsl.builders.sources_mixin import SourcesMixin

    mro_names = {c.__name__ for c in SourcesMixin.__mro__}
    assert "TelegramSourcesMixin" in mro_names
    assert hasattr(SourcesMixin, "from_telegram")
