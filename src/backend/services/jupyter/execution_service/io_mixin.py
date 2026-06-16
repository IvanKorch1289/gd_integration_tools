from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from src.backend.core.logging import get_logger
from src.backend.services.jupyter.execution_service.errors import JupyterExecutionError

_logger = get_logger("services.jupyter.execution")


from src.backend.services.jupyter.execution_service._protocol import (
    _NotebookExecutionProtocol,
)


class IOMixin(_NotebookExecutionProtocol):
    """export + execute + build_ipynb I/O methods для NotebookExecutionService. S60 W1 extraction."""

    __slots__ = ()

    async def export_notebook(
        self,
        user_name: str,
        notebook_path: str,
        *,
        fmt: str = "html",
        timeout_seconds: float | None = None,
    ) -> bytes:
        """Экспортировать notebook через ``/api/nbconvert``.

        Args:
            user_name: Пользователь JupyterHub.
            notebook_path: Путь к notebook.
            fmt: Формат (``html``, ``pdf``, ``python``).
            timeout_seconds: Таймаут запроса.

        Returns:
            Бинарное содержимое экспортированного файла.
        """
        timeout = timeout_seconds or self._settings.timeout_seconds

        async with self._hub:
            server = await self._hub.get_server(user_name)
            if server is None or not server.ready:
                raise JupyterExecutionError(f"Server not ready for user={user_name}")

            server_url = server.url or ""
            # Notebook Server nbconvert endpoint: POST /api/nbconvert/{format}/{path}
            client = self._hub.http
            url = f"{server_url}/api/nbconvert/{fmt}/{notebook_path}"
            try:
                resp = await client.post(url, timeout=timeout)
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPStatusError as exc:
                raise JupyterExecutionError(
                    f"Export failed: {exc.response.status_code} {exc.response.text}",
                    status_code=exc.response.status_code,
                ) from exc

    async def execute(
        self,
        notebook_path: str,
        *,
        parameters: dict[str, Any] | None = None,
        output_format: str | None = None,
        user_name: str = "default",
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Выполнить локальный Jupyter notebook с параметрами через JupyterHub.

        Args:
            notebook_path: Локальный путь к ``.ipynb`` файлу.
            parameters: Словарь параметров для инжекции в начало notebook
                (добавляется ``code``-ячейка с присваиваниями).
            output_format: Опциональный формат экспорта (``html``, ``pdf``, ``python``).
            user_name: Пользователь JupyterHub (default ``"default"``).
            timeout_seconds: Таймаут выполнения.

        Returns:
            Словарь ``{"outputs": [...], "export_data": bytes | None, "format": str | None}``.
        """
        import os

        if not os.path.isfile(notebook_path):
            raise JupyterExecutionError(f"Notebook file not found: {notebook_path}")

        # 1. Read local notebook
        try:
            import nbformat

            def _read_nbformat() -> Any:
                with open(notebook_path, "r", encoding="utf-8") as fh:
                    return nbformat.read(fh, as_version=4)

            nb = await asyncio.to_thread(_read_nbformat)
            cells = [
                {"cell_type": cell.cell_type, "source": cell.source}
                for cell in nb.cells
            ]
        except ImportError:
            _logger.warning("nbformat not installed — falling back to manual JSON read")

            def _read_json() -> Any:
                with open(notebook_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)

            data = await asyncio.to_thread(_read_json)
            cells = [
                {"cell_type": c.get("cell_type", "code"), "source": c.get("source", "")}
                for c in data.get("cells", [])
            ]
        except Exception as exc:
            raise JupyterExecutionError(
                f"Failed to read notebook {notebook_path}: {exc}"
            ) from exc

        # 2. Inject parameters cell at the top
        if parameters:
            param_source = "\n".join(
                f"{key} = {json.dumps(value)}" for key, value in parameters.items()
            )
            cells.insert(0, {"cell_type": "code", "source": param_source})

        # 3. Execute via Hub
        outputs = await self.execute_notebook(
            user_name=user_name,
            notebook_path=notebook_path,
            cells=cells,
            timeout_seconds=timeout_seconds,
        )

        result: dict[str, Any] = {"outputs": outputs}

        # 4. Optional export
        if output_format:
            export_data = await self.export_notebook(
                user_name=user_name,
                notebook_path=notebook_path,
                fmt=output_format,
                timeout_seconds=timeout_seconds,
            )
            result["export_data"] = export_data
            result["format"] = output_format

        return result

    @staticmethod
    def _build_ipynb(notebook_path: str, cells: list[dict[str, Any]]) -> Any:
        """Build validated .ipynb JSON structure via nbformat.

        Falls back to manual JSON if nbformat is not installed.
        """
        try:
            import nbformat

            nb_cells = []
            for cell in cells:
                cell_type = cell.get("cell_type", "code")
                source = cell.get("source", "")
                if cell_type == "code":
                    nb_cells.append(nbformat.v4.new_code_cell(source=source))
                elif cell_type == "markdown":
                    nb_cells.append(nbformat.v4.new_markdown_cell(source=source))
                else:
                    nb_cells.append(nbformat.v4.new_raw_cell(source=source))

            nb = nbformat.v4.new_notebook(cells=nb_cells)
            nb.metadata.kernelspec = {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
            nbformat.validate(nb)
            return nb
        except ImportError:
            _logger.warning("nbformat not installed — falling back to manual JSON")
            return {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3",
                    }
                },
                "cells": [
                    {
                        "cell_type": cell.get("cell_type", "code"),
                        "metadata": {},
                        "source": cell.get("source", ""),
                        "outputs": [],
                        "execution_count": None,
                    }
                    for cell in cells
                ],
            }
