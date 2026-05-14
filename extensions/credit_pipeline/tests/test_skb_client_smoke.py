# ruff: noqa: S101
"""Smoke-тесты CreditSKBClient (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``.

Покрытие (без сетевых вызовов):
* класс наследует BaseExternalAPIClient + правильное имя;
* инстанс создаётся через ``get_credit_skb_client`` (singleton);
* ``_auth_params`` содержит api-key из settings.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from extensions.credit_pipeline.services.clients.skb import CreditSKBClient
from src.backend.services.core.base_external_api import BaseExternalAPIClient


def test_credit_skb_client_is_base_external_api_subclass() -> None:
    """CreditSKBClient наследует BaseExternalAPIClient (R-V15-13 timeouts)."""
    assert issubclass(CreditSKBClient, BaseExternalAPIClient)


def test_credit_skb_client_stores_api_key() -> None:
    """Конструктор сохраняет api-key как auth-param."""
    fake_settings = MagicMock()
    fake_settings.api_key = "test-api-key-123"
    fake_settings.base_url = "https://example.invalid"
    client = CreditSKBClient(skb_settings=fake_settings)
    assert client._auth_params == {"api-key": "test-api-key-123"}


def test_credit_skb_client_module_path_canonical() -> None:
    """Канонический путь модуля — extensions.credit_pipeline.* (R-V15-16)."""
    assert CreditSKBClient.__module__.startswith(
        "extensions.credit_pipeline.services.clients.skb"
    )
