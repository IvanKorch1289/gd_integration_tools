from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import asyncio
import json
import uuid
from typing import Any

import httpx

from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubClient
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("services.jupyter.execution")

class JupyterBackendMixin:
    """jupyter backend internals (server, upload, session, cell execution) для NotebookExecutionService. S60 W1 extraction."""

    __slots__ = ()

    async def _wait_for_server(
        self, user_name: str, *, timeout: float, interval: float = 1.0
    ) -> Any:
        """Poll server readiness until timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            server = await self._hub.get_server(user_name)
            if server and server.ready:
                return server
            await asyncio.sleep(interval)
        raise JupyterExecutionError(
            f"Server for user={user_name} did not become ready within {timeout}s"
        )

    async def _upload_notebook(
        self, server_url: str, path: str, content: dict[str, Any]
    ) -> None:
        """Upload notebook via ``PUT /api/contents/{path}``."""
        client = self._hub.http
        url = f"{server_url}/api/contents/{path}"
        payload = {
            "type": "notebook",
            "format": "json",
            "content": content,
        }
        try:
            resp = await client.put(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JupyterExecutionError(
                f"Upload failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc

    async def _create_session(
        self, server_url: str, notebook_path: str
    ) -> dict[str, Any]:
        """Create session (kernel) via ``POST /api/sessions``."""
        client = self._hub.http
        url = f"{server_url}/api/sessions"
        payload = {
            "path": notebook_path,
            "name": notebook_path,
            "type": "notebook",
            "kernel": {"name": self._settings.default_kernel},
        }
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise JupyterExecutionError(
                f"Session creation failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc

    async def _execute_cell(
        self,
        server_url: str,
        kernel_id: str,
        source: str,
        *,
        timeout: float,
    ) -> list[dict[str, Any]]:
        """Execute single cell via WebSocket kernel channel."""
        try:
            import websockets
        except ImportError as exc:
            raise JupyterExecutionError(
                "websockets package required for notebook execution. "
                "Install: uv sync --extra jupyter"
            ) from exc

        ws_url = self._server_to_ws_url(server_url)
        uri = f"{ws_url}/api/kernels/{kernel_id}/channels"

        msg_id = str(uuid.uuid4())
        execute_msg = {
            "header": {
                "msg_id": msg_id,
                "username": "gd-integration-tools",
                "session": msg_id,
                "msg_type": "execute_request",
                "version": "5.2",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": source,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
            },
        }

        outputs: list[dict[str, Any]] = []

        try:
            async with websockets.connect(uri) as ws:  # type: ignore[var-annotated]
                await ws.send(json.dumps(execute_msg))

                # Wait for execute_reply with msg_id matching our request
                deadline = asyncio.get_event_loop().time() + timeout
                while asyncio.get_event_loop().time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg = json.loads(raw)
                    msg_type = msg.get("msg_type", "")
                    parent_id = msg.get("parent_header", {}).get("msg_id")

                    if parent_id != msg_id:
                        continue

                    if msg_type == "stream":
                        outputs.append(
                            {
                                "output_type": "stream",
                                "name": msg["content"].get("name", "stdout"),
                                "text": msg["content"].get("text", ""),
                            }
                        )
                    elif msg_type == "execute_result":
                        outputs.append(
                            {
                                "output_type": "execute_result",
                                "execution_count": msg["content"].get("execution_count"),
                                "data": msg["content"].get("data", {}),
                            }
                        )
                    elif msg_type == "error":
                        outputs.append(
                            {
                                "output_type": "error",
                                "ename": msg["content"].get("ename", ""),
                                "evalue": msg["content"].get("evalue", ""),
                                "traceback": msg["content"].get("traceback", []),
                            }
                        )
                    elif msg_type == "execute_reply":
                        status = msg["content"].get("status", "ok")
                        if status != "ok":
                            _logger.warning("Cell execution status=%s", status)
                        break
                else:
                    raise JupyterExecutionError(
                        f"Cell execution timed out after {timeout}s"
                    )
        except asyncio.TimeoutError as exc:
            raise JupyterExecutionError(
                f"Cell execution timed out after {timeout}s"
            ) from exc
        except Exception as exc:
            raise JupyterExecutionError(f"WebSocket error: {exc}") from exc

        return outputs

