"""Регрессия декодирования base64 в Jupyter Hub action."""

from __future__ import annotations

import pytest

from src.backend.services.jupyter.hub_actions import _RunHubNotebookService
from src.backend.services.jupyter.hub_run_orchestrator import HubRunError


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_rejects_invalid_base64_as_hub_error() -> None:
    """binascii.Error преобразуется в стабильный HubRunError."""
    service = _RunHubNotebookService()

    with pytest.raises(HubRunError, match="not valid base64"):
        await service.run(notebook_content_b64="not-valid-base64!!!")
