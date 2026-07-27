"""Regression test for AuthFacade's fail-closed SAML contract."""

from __future__ import annotations

import pytest

from src.backend.core.auth.facade import AuthFacade


@pytest.mark.unit
@pytest.mark.asyncio
async def test_raw_saml_assertion_requires_configured_acs_flow() -> None:
    result = await AuthFacade().verify_request("raw-assertion", method="saml")

    assert result.is_authenticated is False
    assert result.metadata == {"error": "saml_requires_acs_flow"}
