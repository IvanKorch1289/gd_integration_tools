"""Regression test for AuthFacade's fail-closed SAML contract."""

from __future__ import annotations

import pytest

from src.backend.core.auth.facade import AuthFacade


@pytest.mark.unit
@pytest.mark.asyncio
async def test_raw_saml_assertion_requires_configured_acs_flow() -> None:
    result = await AuthFacade().verify_request("raw-assertion", method="saml")

    assert result.is_authenticated is False
    # Cycle 92 L10: production metadata includes ``assertion_len`` debug
    # info alongside error code. Assert on subset, not exact equality —
    # otherwise future debug fields break this test.
    assert result.metadata["error"] == "saml_requires_acs_flow"
    assert "assertion_len" in result.metadata
