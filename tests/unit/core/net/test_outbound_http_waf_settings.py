"""A3 (ADR-0385): ``OutboundHttpClient`` применяет настроенную WAF-policy.

Дефект
------
``OutboundHttpClient.__init__`` подставлял ``policy or WafPolicy()`` —
пустую permissive-policy (deny-list пуст, ``strict=False``,
payload-limit не задан). Вызывающие, которые не передавали policy явно
(``make_http_client``, прямые ``OutboundHttpClient(...)`` в gemini/claude/
http_sink/webhook_sink/search_providers), обходили настройку WAF: в prod
``strict=True`` + allowlist из ``config_profiles/prod.yml`` не действовали.

Ожидание
--------
* без явной policy клиент берёт policy из ``waf_settings``;
* явная policy имеет приоритет;
* настроенный deny/strict реально блокирует запрос (WafBypassError).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from src.backend.core.net.outbound_http import OutboundHttpClient
from src.backend.core.net.waf import WafBypassError, WafPolicy

_WAF_SETTINGS_PATH = "src.backend.core.config.waf.waf_settings"


def _settings_stub(**overrides: object) -> SimpleNamespace:
    """Заглушка ``waf_settings`` с дефолтами dev-профиля."""
    defaults: dict[str, object] = {
        "allow_hosts": (),
        "deny_hosts": (),
        "strict": False,
        "max_payload_bytes": 10 * 1024 * 1024,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


@pytest.fixture()
def transport() -> httpx.MockTransport:
    return httpx.MockTransport(_ok_handler)


class TestDefaultPolicyFromSettings:
    """Policy по умолчанию строится из ``waf_settings``."""

    def test_policy_reflects_settings(self) -> None:
        """Allow/deny-списки и strict берутся из настроек."""
        stub = _settings_stub(
            allow_hosts=("allowed.example.com",),
            deny_hosts=("banned.example.com",),
            strict=True,
        )
        with patch(_WAF_SETTINGS_PATH, stub):
            client = OutboundHttpClient()
        policy = client._policy
        assert policy.allow_hosts == frozenset({"allowed.example.com"})
        assert policy.deny_hosts == frozenset({"banned.example.com"})
        assert policy.strict is True

    def test_explicit_policy_wins(self) -> None:
        """Явно переданная policy не заменяется настройками."""
        explicit = WafPolicy(deny_hosts=frozenset({"only.example.com"}))
        stub = _settings_stub(deny_hosts=("other.example.com",))
        with patch(_WAF_SETTINGS_PATH, stub):
            client = OutboundHttpClient(policy=explicit)
        assert client._policy is explicit

    def test_settings_failure_falls_back_to_permissive(self) -> None:
        """Недоступные настройки не роняют создание клиента."""
        with patch(_WAF_SETTINGS_PATH, None):
            client = OutboundHttpClient()
        assert client._policy.deny_hosts == frozenset()

    @pytest.mark.asyncio
    async def test_deny_host_from_settings_blocks_request(
        self, transport: httpx.MockTransport
    ) -> None:
        """Хост из deny-списка настроек блокируется (было — проходил)."""
        stub = _settings_stub(deny_hosts=("banned.example.com",))
        with patch(_WAF_SETTINGS_PATH, stub):
            client = OutboundHttpClient()
            client._client._transport = transport  # type: ignore[attr-defined]
            with pytest.raises(WafBypassError):
                await client.get("https://banned.example.com/data")

    @pytest.mark.asyncio
    async def test_strict_allowlist_blocks_foreign_host(
        self, transport: httpx.MockTransport
    ) -> None:
        """strict=True + allowlist: чужой хост блокируется."""
        stub = _settings_stub(allow_hosts=("allowed.example.com",), strict=True)
        with patch(_WAF_SETTINGS_PATH, stub):
            client = OutboundHttpClient()
            client._client._transport = transport  # type: ignore[attr-defined]
            with pytest.raises(WafBypassError):
                await client.get("https://foreign.example.com/data")
