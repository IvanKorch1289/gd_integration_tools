"""Tests for ``src.backend.services.ai.document_parsers._network``.

V15 R-V15-5: network isolation для markitdown-engine.
"""

from __future__ import annotations

import urllib.request

import pytest

from src.backend.services.ai.document_parsers import _network as mod_pkg
from src.backend.services.ai.document_parsers._network import (
    _NetworkDeniedError,
    _denied_urlopen,
    markitdown_network_disabled,
)


class TestDeniedUrlopen:
    """_denied_urlopen() всегда бросает _NetworkDeniedError."""

    def test_raises_with_args(self) -> None:
        with pytest.raises(_NetworkDeniedError):
            _denied_urlopen("http://example.com")

    def test_raises_with_kwargs(self) -> None:
        with pytest.raises(_NetworkDeniedError):
            _denied_urlopen(url="http://example.com")

    def test_raises_with_no_args(self) -> None:
        with pytest.raises(_NetworkDeniedError):
            _denied_urlopen()

    def test_error_message_mentions_settings(self) -> None:
        with pytest.raises(_NetworkDeniedError) as exc_info:
            _denied_urlopen()
        # Должно упомянуть network_mode='off' или settings
        msg = str(exc_info.value)
        assert "network" in msg.lower() or "off" in msg.lower()

    def test_network_denied_is_runtime_error(self) -> None:
        # _NetworkDeniedError наследует от RuntimeError (стандартная иерархия)
        assert issubclass(_NetworkDeniedError, RuntimeError)


class TestMarkitdownNetworkDisabled:
    """markitdown_network_disabled() — context manager."""

    def test_replaces_urlopen_inside(self) -> None:
        original = urllib.request.urlopen
        with markitdown_network_disabled():
            assert urllib.request.urlopen is not original
            assert urllib.request.urlopen is _denied_urlopen
        # После выхода — восстановлен
        assert urllib.request.urlopen is original

    def test_restores_urlopen_on_exception(self) -> None:
        original = urllib.request.urlopen
        with pytest.raises(RuntimeError):
            with markitdown_network_disabled():
                assert urllib.request.urlopen is _denied_urlopen
                raise RuntimeError("test")
        # Восстановлен даже при исключении
        assert urllib.request.urlopen is original

    def test_urlopen_denied_inside_block(self) -> None:
        with markitdown_network_disabled():
            with pytest.raises(_NetworkDeniedError):
                urllib.request.urlopen("http://example.com")

    def test_urlopen_works_outside_block(self) -> None:
        original = urllib.request.urlopen
        # За пределами context manager urlopen — original
        assert urllib.request.urlopen is original

    def test_nested_context_managers(self) -> None:
        original = urllib.request.urlopen
        with markitdown_network_disabled():
            inner_urlopen = urllib.request.urlopen
            with markitdown_network_disabled():
                # Внутри nested — снова _denied_urlopen
                assert urllib.request.urlopen is _denied_urlopen
            # После выхода nested — restored к inner уровню
            assert urllib.request.urlopen is inner_urlopen
        # После выхода outer — restored к original
        assert urllib.request.urlopen is original


class TestYieldsNone:
    """Context manager yield'ит None."""

    def test_yields_none(self) -> None:
        with markitdown_network_disabled() as value:
            assert value is None


class TestAllExports:
    """__all__ проверка."""

    def test_exports_markitdown_network_disabled(self) -> None:
        assert "markitdown_network_disabled" in mod_pkg.__all__
        assert len(mod_pkg.__all__) == 1

    def test_function_callable(self) -> None:
        assert callable(markitdown_network_disabled)