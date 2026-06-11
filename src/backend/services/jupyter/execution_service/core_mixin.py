from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("services.jupyter.execution")


class CoreMixin:
    """public execute_notebook entry (78 LOC, BIG) для NotebookExecutionService. S60 W1 extraction."""

    __slots__ = ()

    async def execute_notebook(
        self,
        user_name: str,
        notebook_path: str,
        cells: list[dict[str, Any]],
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """Выполнить notebook и вернуть outputs.

        Steps:
        1. Spawn user server (if not ready).
        2. Upload notebook via ``PUT /api/contents/{path}``.
        3. Create session (kernel) via ``POST /api/sessions``.
        4. Execute each ``code`` cell via WebSocket kernel channel.
        5. Stop server (optional, controlled by settings).

        Args:
            user_name: Имя пользователя JupyterHub.
            notebook_path: Путь к notebook (например, ``"analysis.ipynb"``).
            cells: Список cell-объектов ``{"cell_type": "code", "source": str}``.
            timeout_seconds: Таймаут на весь execution (default из settings).

        Returns:
            Список output-объектов per cell::

                [
                    {
                        "cell_index": 0,
                        "outputs": [
                            {"output_type": "stream", "text": "2\n"},
                            {"output_type": "execute_result", "data": {...}},
                        ],
                    },
                    ...
                ]
        """
        timeout = timeout_seconds or self._settings.timeout_seconds

        async with self._hub:
            # 1. Ensure server is running
            server = await self._hub.get_server(user_name)
            if server is None or not server.ready:
                _logger.info("Spawning server for user=%s", user_name)
                await self._hub.start_server(user_name)
                # Wait for server readiness (poll with backoff)
                server = await self._wait_for_server(user_name, timeout=timeout)

            server_url = server.url if server else ""
            if not server_url:
                raise JupyterExecutionError(
                    f"Server URL unavailable for user={user_name}"
                )

            # 2. Upload notebook
            await self._upload_notebook(
                server_url, notebook_path, self._build_ipynb(notebook_path, cells)
            )

            # 3. Create session → kernel
            session = await self._create_session(server_url, notebook_path)
            kernel_id = session.get("kernel", {}).get("id")
            if not kernel_id:
                raise JupyterExecutionError(
                    "Kernel ID not returned from session creation"
                )

            # 4. Execute cells
            results: list[dict[str, Any]] = []
            try:
                for idx, cell in enumerate(cells):
                    if cell.get("cell_type") != "code":
                        continue
                    outputs = await self._execute_cell(
                        server_url, kernel_id, cell["source"], timeout=timeout
                    )
                    results.append({"cell_index": idx, "outputs": outputs})
            finally:
                # Optional: cleanup — leave server running for reuse
                pass

            return results
