"""Unit-тесты LdapQueryProcessor — Wave [wave:s5/k3-w3-processor-pack-3]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ldap_query import LdapQueryProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_ldap_query", True)


@pytest.mark.asyncio
async def test_fails_when_no_lib(monkeypatch: pytest.MonkeyPatch) -> None:
    # Эмулируем ImportError для обоих библиотек
    import sys
    monkeypatch.setitem(sys.modules, "aioldap3", None)
    monkeypatch.setitem(sys.modules, "ldap3", None)
    proc = LdapQueryProcessor(
        server="ldap://x:389",
        search_base="dc=test",
        search_filter="(uid=*)",
    )
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.error is not None and "not available" in ex.error.lower()


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_ldap_query", False)
    proc = LdapQueryProcessor(
        server="ldap://x", search_base="dc=t", search_filter="(uid=*)"
    )
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("ldap_query_status") == "skipped"


def test_validates_constructor() -> None:
    with pytest.raises(ValueError, match="server"):
        LdapQueryProcessor(server="", search_base="dc=t", search_filter="(uid=*)")
    with pytest.raises(ValueError, match="search_base"):
        LdapQueryProcessor(
            server="ldap://x", search_base="", search_filter="(uid=*)"
        )
