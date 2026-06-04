"""Unit tests for src.backend.core.di.providers.http (T-P1.2c split)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.core.di.providers import http


class TestHttpClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_http")
        http.set_http_client_provider(mock)
        assert http.get_http_client_provider() is mock


class TestSmtpClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_smtp")
        http.set_smtp_client_provider(mock)
        assert http.get_smtp_client_provider() is mock


class TestExpressClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_express")
        http.set_express_client_provider(mock)
        assert http.get_express_client_provider() is mock


class TestExpressDialogStore:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_dialog_store")
        http.set_express_dialog_store_provider(mock)
        assert http.get_express_dialog_store_provider() is mock


class TestExpressSessionStore:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_session_store")
        http.set_express_session_store_provider(mock)
        assert http.get_express_session_store_provider() is mock


class TestExpressMetricsRecorder:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_recorder")
        http.set_express_metrics_recorder_provider(mock)
        assert http.get_express_metrics_recorder_provider() is mock

    def test_noop_helper_callable(self) -> None:
        # _noop_express_metrics_recorder must be callable (S38 S30 W5 ref)
        assert callable(http._noop_express_metrics_recorder)
        # Should not raise
        result = http._noop_express_metrics_recorder(bot="b1", command="c1")
        assert result is None


class TestExpressBotClientFactory:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_bot_factory")
        http.set_express_bot_client_factory_provider(mock)
        assert http.get_express_bot_client_factory_provider() is mock


class TestExpressBotxMessageClass:
    def test_get_only(self) -> None:
        # No set_ function — verify import
        from src.backend.core.di.providers.http import (
            get_express_botx_message_class_provider,
        )

        assert callable(get_express_botx_message_class_provider)


class TestBrowserClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_browser")
        http.set_browser_client_provider(mock)
        assert http.get_browser_client_provider() is mock


class TestExternalSessionManager:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_session_mgr")
        http.set_external_session_manager_provider(mock)
        assert http.get_external_session_manager_provider() is mock


class TestImportGatewayFactory:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_import_factory")
        http.set_import_gateway_factory_provider(mock)
        assert http.get_import_gateway_factory_provider() is mock


class TestRedisCoordinatorFactories:
    def test_hash_set_overrides(self) -> None:
        mock = MagicMock(name="custom_redis_hash")
        http.set_redis_hash_factory_provider(mock)
        assert http.get_redis_hash_factory_provider() is mock

    def test_set_set_overrides(self) -> None:
        mock = MagicMock(name="custom_redis_set")
        http.set_redis_set_factory_provider(mock)
        assert http.get_redis_set_factory_provider() is mock

    def test_pubsub_set_overrides(self) -> None:
        mock = MagicMock(name="custom_redis_pubsub")
        http.set_redis_pubsub_factory_provider(mock)
        assert http.get_redis_pubsub_factory_provider() is mock

    def test_cursor_set_overrides(self) -> None:
        mock = MagicMock(name="custom_redis_cursor")
        http.set_redis_cursor_factory_provider(mock)
        assert http.get_redis_cursor_factory_provider() is mock


class TestStreamClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_stream_client")
        http.set_stream_client_provider(mock)
        assert http.get_stream_client_provider() is mock


class TestHttpModuleIsolation:
    """_overrides isolated between http subdomains (and from other domains)."""

    def test_http_overrides_isolated(self) -> None:
        http.set_http_client_provider("HTTP")
        http.set_smtp_client_provider("SMTP")
        http.set_redis_hash_factory_provider("HASH")
        assert http.get_http_client_provider() == "HTTP"
        assert http.get_smtp_client_provider() == "SMTP"
        assert http.get_redis_hash_factory_provider() == "HASH"
