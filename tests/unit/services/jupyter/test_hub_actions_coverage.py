"""Тесты hub_actions: base64/name-резолв, register-ветки (T3 ratchet 67%→≥90%)."""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from src.backend.services.jupyter.hub_actions import (
    HubRunError,
    register_jupyter_hub_actions,
)
from src.backend.services.jupyter.hub_run_orchestrator import HubRunResult


def _hub_result() -> HubRunResult:
    return HubRunResult(
        notebook_name="run_model",
        notebook_path="/hub/run_model.ipynb",
        parameters={},
        outputs=[],
        duration_seconds=1.0,
        cells_executed=3,
        errors=[],
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.mark.asyncio
async def test_run_decodes_b64_and_derives_name_from_path() -> None:
    """b64 декодируется; имя выводится из notebook_path (без .ipynb)."""
    service_module = __import__(
        "src.backend.services.jupyter.hub_actions", fromlist=["run_hub_notebook"]
    )
    captured: dict[str, object] = {}

    async def fake_run(**kwargs: object) -> HubRunResult:
        captured.update(kwargs)
        return _hub_result()

    with patch.object(service_module, "run_hub_notebook", fake_run):
        service = service_module.get_jupyter_hub_run_service()
        result = await service.run(
            notebook_path="projects/scoring/run_model.ipynb",
            notebook_content_b64=_b64(b"nb-bytes"),
            parameters={"p": 1},
        )

    assert result["notebook_name"] == "run_model"
    assert result["cells_executed"] == 3
    assert captured["notebook_content"] == b"nb-bytes"
    assert captured["notebook_name"] == "run_model"
    assert captured["parameters"] == {"p": 1}


@pytest.mark.asyncio
async def test_run_invalid_b64_raises_hub_error() -> None:
    service_module = __import__(
        "src.backend.services.jupyter.hub_actions", fromlist=["HubRunError"]
    )
    service = service_module.get_jupyter_hub_run_service()
    with pytest.raises(HubRunError, match="not valid base64"):
        await service.run(notebook_content_b64="!!!not-base64!!!")


@pytest.mark.asyncio
async def test_run_without_any_notebook_source_raises() -> None:
    service_module = __import__(
        "src.backend.services.jupyter.hub_actions", fromlist=["HubRunError"]
    )
    service = service_module.get_jupyter_hub_run_service()
    with pytest.raises(HubRunError, match="notebook_name"):
        await service.run()


@pytest.mark.asyncio
async def test_run_inline_content_gets_default_name() -> None:
    service_module = __import__(
        "src.backend.services.jupyter.hub_actions", fromlist=["run_hub_notebook"]
    )
    captured: dict[str, object] = {}

    async def fake_run(**kwargs: object) -> HubRunResult:
        captured.update(kwargs)
        return _hub_result()

    service = service_module.get_jupyter_hub_run_service()
    with patch.object(service_module, "run_hub_notebook", fake_run):
        await service.run(notebook_content=b"raw-bytes")

    assert captured["notebook_name"] == "inline_notebook"
    assert captured["notebook_content"] == b"raw-bytes"


# ── register_jupyter_hub_actions: три ветки регистрации ─────────────


def test_register_with_register_many() -> None:
    class RegistryWithMany:
        registered: list[object] = []

        def register_many(self, specs):  # type: ignore[no-untyped-def]
            RegistryWithMany.registered = list(specs)

    result = register_jupyter_hub_actions(RegistryWithMany())
    assert result == ["jupyter.hub_run"]
    assert RegistryWithMany.registered[0].action == "jupyter.hub_run"


def test_register_fallback_to_register() -> None:
    class RegistryWithRegister:
        kwargs: dict[str, object] = {}

        def register(self, **kwargs: object) -> None:
            RegistryWithRegister.kwargs = kwargs

    result = register_jupyter_hub_actions(RegistryWithRegister())
    assert result == ["jupyter.hub_run"]
    assert RegistryWithRegister.kwargs["action"] == "jupyter.hub_run"
    assert RegistryWithRegister.kwargs["payload_model"] is None


def test_register_without_methods_raises_type_error() -> None:
    class EmptyRegistry:
        pass

    with pytest.raises(TypeError, match="no register"):
        register_jupyter_hub_actions(EmptyRegistry())
