from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("services.jupyter.execution")


class NbClientExecutionBackend:
    """Local notebook execution via nbclient (no JupyterHub required).

    Usage::

        backend = NbClientExecutionBackend(kernel_name="python3")
        outputs = await backend.execute(cells=[{"cell_type": "code", "source": "1+1"}])
    """

    def __init__(self, kernel_name: str = "python3", timeout: float = 60.0) -> None:
        self._kernel_name = kernel_name
        self._timeout = timeout

    async def execute(
        self, cells: list[dict[str, Any]], *, notebook_path: str = "local.ipynb"
    ) -> list[dict[str, Any]]:
        """Execute cells locally via nbclient.NotebookClient.

        Returns:
            List of output dicts per cell (same format as Hub execution).
        """
        try:
            import nbclient
        except ImportError as exc:
            raise JupyterExecutionError(
                "nbclient required for local execution. "
                "Install: uv sync --extra jupyter"
            ) from exc

        svc = NotebookExecutionService.__new__(NotebookExecutionService)
        nb = svc._build_ipynb(notebook_path, cells)

        client = nbclient.NotebookClient(
            nb,
            kernel_name=self._kernel_name,
            timeout=self._timeout,
            resources={"metadata": {"path": "."}},
        )

        results: list[dict[str, Any]] = []
        try:
            with client.setup_kernel():
                for idx, cell in enumerate(cells):
                    if cell.get("cell_type") != "code":
                        continue
                    client.execute_cell(cell=nb.cells[idx], cell_index=idx)
                    outputs = []
                    for output in nb.cells[idx].outputs:
                        out_type = output.output_type
                        if out_type == "stream":
                            outputs.append(
                                {
                                    "output_type": "stream",
                                    "name": output.name,
                                    "text": output.text,
                                }
                            )
                        elif out_type == "execute_result":
                            outputs.append(
                                {
                                    "output_type": "execute_result",
                                    "execution_count": output.execution_count,
                                    "data": output.data,
                                }
                            )
                        elif out_type == "error":
                            outputs.append(
                                {
                                    "output_type": "error",
                                    "ename": output.ename,
                                    "evalue": output.evalue,
                                    "traceback": output.traceback,
                                }
                            )
                    results.append({"cell_index": idx, "outputs": outputs})
        except Exception as exc:
            raise JupyterExecutionError(
                f"Local nbclient execution failed: {exc}"
            ) from exc

        return results
