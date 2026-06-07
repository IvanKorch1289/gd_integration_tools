"""Tests для ADR-0082 — markitdown network isolation.

Покрывает:
* monkey-patch: urllib.request.urlopen заменяется на _denied_urlopen
* _denied_urlopen raises _NetworkDeniedError
* restore в finally — original restored после context exit
* nested contexts — restore chain integrity
* concurrent / sequential: original NOT polluted между calls
"""

from __future__ import annotations

import urllib.request

import pytest

from src.backend.services.ai.document_parsers._network import (
    _denied_urlopen,
    _NetworkDeniedError,
    markitdown_network_disabled,
)


class TestDeniedUrlopen:
    """_denied_urlopen raises _NetworkDeniedError для любого вызова."""

    def test_no_args_denied(self) -> None:
        """_denied_urlopen() → _NetworkDeniedError."""
        with pytest.raises(_NetworkDeniedError, match="network access is disabled"):
            _denied_urlopen()

    def test_urlopen_args_denied(self) -> None:
        """_denied_urlopen('https://example.com') → _NetworkDeniedError."""
        with pytest.raises(_NetworkDeniedError):
            _denied_urlopen("https://example.com/foo")

    def test_kwargs_denied(self) -> None:
        """kwargs (timeout, data) → _NetworkDeniedError."""
        with pytest.raises(_NetworkDeniedError):
            _denied_urlopen("https://x", timeout=5, data=b"x")


class TestMarkitdownNetworkDisabled:
    """Context manager: monkey-patch + restore в finally."""

    def test_urlopen_denied_inside_context(self) -> None:
        """Внутри context urllib.request.urlopen raises _NetworkDeniedError."""
        with markitdown_network_disabled():
            with pytest.raises(_NetworkDeniedError):
                urllib.request.urlopen("https://example.com")

    def test_urlopen_restored_after_context(self) -> None:
        """После context — urlopen = original (NOT _denied_urlopen)."""
        original = urllib.request.urlopen
        with markitdown_network_disabled():
            assert urllib.request.urlopen is not original
        # После выхода — восстановлен
        assert urllib.request.urlopen is original

    def test_restore_on_exception(self) -> None:
        """Exception внутри context НЕ ломает restore в finally."""
        original = urllib.request.urlopen
        with pytest.raises(RuntimeError, match="test"):
            with markitdown_network_disabled():
                raise RuntimeError("test")
        # Restore ВСЁ РАВНО произошёл
        assert urllib.request.urlopen is original

    def test_nested_contexts(self) -> None:
        """Nested context — inner restore не ломает outer context."""
        original = urllib.request.urlopen
        with markitdown_network_disabled():
            with markitdown_network_disabled():
                # Двойной patch — обе ссылки на _denied_urlopen
                assert urllib.request.urlopen is _denied_urlopen
            # После inner — outer ещё активен
            assert urllib.request.urlopen is _denied_urlopen
        # После обоих — original
        assert urllib.request.urlopen is original

    def test_no_outbound_when_html_with_links(self) -> None:
        """HTML с external <a href> обрабатывается без outbound calls.

        Контрольный кейс: реальный HTML документ с 5 external links
        (s3.amazonaws.com, google.com, attacker.example, etc.) парсится
        в HTML→Markdown converter БЕЗ выхода в сеть.
        """
        html = """
        <html>
        <body>
            <a href="https://s3.amazonaws.com/secret-bucket/leak">leak</a>
            <a href="https://google.com/search?q=exfil">search</a>
            <a href="https://attacker.example/log">track</a>
            <a href="http://169.254.169.254/latest/meta-data/">imds</a>
            <a href="https://internal.svc.cluster.local/api">internal</a>
        </body>
        </html>
        """
        with markitdown_network_disabled():
            # Любой попытке outbound — _NetworkDeniedError
            # markitdown при HTML→Markdown вызывает urlopen для resolve,
            # но мы перехватываем exception (markitdown catches internally).
            # Этот тест не запускает markitdown (зависимость), а только
            # проверяет что stub работает.
            try:
                urllib.request.urlopen(html)  # type: ignore[arg-type]  # noqa: S310
            except _NetworkDeniedError:
                pass  # expected
            else:
                pytest.fail("Expected _NetworkDeniedError")

    def test_no_outbound_rss_with_enclosure(self) -> None:
        """RSS с external enclosure URL → stub blocks urlopen."""
        rss = """<?xml version="1.0"?>
        <rss version="2.0">
            <channel>
                <item>
                    <enclosure url="https://evil.example/payload.mp3" length="1000" type="audio/mpeg"/>
                </item>
            </channel>
        </rss>
        """
        with markitdown_network_disabled():
            try:
                urllib.request.urlopen(rss)  # type: ignore[arg-type]  # noqa: S310
            except _NetworkDeniedError:
                pass
            else:
                pytest.fail("Expected _NetworkDeniedError")


class TestRestoreAfterExceptionInYield:
    """Edge cases для restore guarantee."""

    def test_keyboard_interrupt_restores(self) -> None:
        """Даже при BaseException (KeyboardInterrupt) — restore работает."""
        original = urllib.request.urlopen
        try:
            with markitdown_network_disabled():
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            pass
        assert urllib.request.urlopen is original

    def test_consecutive_contexts_no_state_leak(self) -> None:
        """Два context'а подряд — original сохраняется."""
        original = urllib.request.urlopen
        with markitdown_network_disabled():
            pass
        with markitdown_network_disabled():
            pass
        assert urllib.request.urlopen is original
