"""Unit tests for LdapQueryProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ldap_query import LdapQueryProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestLdapQueryProcessor:
    def test_init_empty_server_raises(self) -> None:
        with pytest.raises(ValueError, match="server must be non-empty"):
            LdapQueryProcessor("", "dc=example", "(objectClass=person)")

    def test_init_empty_search_base_raises(self) -> None:
        with pytest.raises(ValueError, match="search_base must be non-empty"):
            LdapQueryProcessor("ldap://host", "", "(objectClass=person)")

    def test_init_empty_search_filter_raises(self) -> None:
        with pytest.raises(ValueError, match="search_filter must be non-empty"):
            LdapQueryProcessor("ldap://host", "dc=example", "")

    def test_apply_target_body(self) -> None:
        proc = LdapQueryProcessor("ldap://host", "dc=example", "(obj=person)")
        ex = _ex({})
        proc._apply_target(ex, [{"cn": "Alice"}])
        assert ex.in_message.body == {"ldap_result": [{"cn": "Alice"}]}

    def test_apply_target_properties(self) -> None:
        proc = LdapQueryProcessor(
            "ldap://host", "dc=example", "(obj=person)", to="properties.users"
        )
        ex = _ex({})
        proc._apply_target(ex, [{"cn": "Alice"}])
        assert ex.properties["users"] == [{"cn": "Alice"}]

    @pytest.mark.asyncio
    async def test_process_feature_flag_off(self) -> None:
        with patch(
            "src.backend.core.config.features.feature_flags.proc_ldap_query", False
        ):
            proc = LdapQueryProcessor("ldap://host", "dc=example", "(obj=person)")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.properties.get("ldap_query_status") == "skipped"

    @pytest.mark.asyncio
    async def test_process_import_error(self) -> None:
        with (
            patch(
                "src.backend.core.config.features.feature_flags.proc_ldap_query", True
            ),
            patch.object(LdapQueryProcessor, "_search_sync", side_effect=ImportError),
        ):
            proc = LdapQueryProcessor("ldap://host", "dc=example", "(obj=person)")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.status.name == "failed"
            assert "ldap3 not available" in ex.error

    @pytest.mark.asyncio
    async def test_process_success(self) -> None:
        with (
            patch(
                "src.backend.core.config.features.feature_flags.proc_ldap_query", True
            ),
            patch.object(
                LdapQueryProcessor, "_search_sync", return_value=[{"cn": "Alice"}]
            ),
        ):
            proc = LdapQueryProcessor("ldap://host", "dc=example", "(obj=person)")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.in_message.body == {"ldap_result": [{"cn": "Alice"}]}

    def test_to_spec_defaults(self) -> None:
        proc = LdapQueryProcessor("ldap://host", "dc=example", "(obj=person)")
        spec = proc.to_spec()
        assert spec == {
            "ldap_query": {
                "server": "ldap://host",
                "search_base": "dc=example",
                "search_filter": "(obj=person)",
            }
        }

    def test_to_spec_full(self) -> None:
        proc = LdapQueryProcessor(
            "ldaps://host",
            "dc=example",
            "(obj=person)",
            bind_dn="cn=admin",
            password="secret",
            attributes=["cn", "mail"],
            to="body.users",
            use_ssl=True,
        )
        spec = proc.to_spec()
        assert spec["ldap_query"] == {
            "server": "ldaps://host",
            "search_base": "dc=example",
            "search_filter": "(obj=person)",
            "bind_dn": "cn=admin",
            "password": "secret",
            "attributes": ["cn", "mail"],
            "to": "body.users",
            "use_ssl": True,
        }
