"""S75 W3 — KernelSpec discovery: multiple kernels support.

FINAL_REPORT_V2 направление #1: «Множественные kernels — ⚠️». До S75
поддерживался только ``settings.default_kernel`` (один kernel). Real
deployments имеют multiple kernels: ``python3``, ``python2``,
``ir`` (R), ``julia-1.6``, ``sas``, etc.

**Design**:
* ``KernelSpecDiscovery.discover_available()`` — обёртка вокруг
  ``jupyter_client.kernelspec.KernelSpecManager.get_all_specs()``.
  Lazy-import ``jupyter_client`` (opt-in dep, ``[jupyter]`` extra).
* Returns ``dict[str, dict[str, str]]`` — kernel_name → spec dict
  (resource_dir, display_name, language, argv).
* Graceful fallback: если jupyter_client не установлен →
  ``{"python3": default_spec}`` (single fallback kernel).
* ``JupyterHubSettings.available_kernels`` (NEW optional field) —
  pydantic list[str] из YAML. Если empty, discovery использует
  ``jupyter_client``.

**Use case** (FINAL_REPORT_V2 направление #1):
* JupyterHub admin registers multiple kernels (Python, R, Julia).
* ``KernelSpecDiscovery`` queries local jupyter_client для available
  list (на JupyterHub worker, не Hub itself).
* ``JupyterHubSettings.available_kernels = ["python3", "ir", "julia-1.6"]``
  — explicit whitelist (для security/audit).
* ``NotebookExecutionService.execute_notebook`` chooses kernel
  based on notebook ``metadata.kernelspec.name`` (cell-tag driven)
  or ``settings.default_kernel`` (fallback).

Limitations:
* Discovery queries LOCAL jupyter_client (на worker node, не Hub).
  Если worker не имеет всех kernels — discovery покажет только то
  что installed locally.
* Для Hub-based: use JupyterHub API ``/api/kernelspecs`` (separate
  integration, S75 W3 stub).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("services.jupyter.kernelspec")

__all__ = ("KernelSpecDiscovery", "DEFAULT_FALLBACK_SPECS")


# Default fallback если jupyter_client не установлен — single python3
# spec для backward compat с pre-S75 кодом.
DEFAULT_FALLBACK_SPECS: dict[str, dict[str, str]] = {
    "python3": {
        "resource_dir": "",
        "display_name": "Python 3 (fallback)",
        "language": "python",
        "argv": ["python3", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
    }
}


class KernelSpecDiscovery:
    """S75 W3 — multi-kernel discovery wrapper.

    Singleton (singleton pattern via instance, не module-level) — caller
    can hold reference и share across requests.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, str]] | None = None

    def discover_available(self) -> dict[str, dict[str, str]]:
        """Discover available kernelspecs на этом worker.

        Returns:
            Dict ``{kernel_name: spec_dict}``. spec_dict keys:
            ``resource_dir``, ``display_name``, ``language``, ``argv``.

        **Caching**: результат cached при первом вызове. Jupyter
        kernelspecs редко меняются в runtime. Cache invalidation
        manual (caller can ``self._cache = None`` для refresh).

        **Fallback**: если ``jupyter_client`` не установлен или
        ``get_all_specs()`` fails → ``DEFAULT_FALLBACK_SPECS``
        (single python3 entry).
        """
        if self._cache is not None:
            return self._cache

        try:
            from jupyter_client.kernelspec import (
                KernelSpecManager,  # type: ignore[import-not-found]
            )
        except ImportError:
            _logger.warning(
                "jupyter_client не установлен, fallback to python3 only. "
                "Install: uv sync --extra jupyter"
            )
            self._cache = dict(DEFAULT_FALLBACK_SPECS)
            return self._cache

        try:
            ksm = KernelSpecManager()
            raw_specs = ksm.get_all_specs()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "KernelSpecManager.get_all_specs() failed: %s — fallback to defaults",
                exc,
            )
            self._cache = dict(DEFAULT_FALLBACK_SPECS)
            return self._cache

        # Convert to our spec format (subset of jupyter_client fields)
        normalized: dict[str, dict[str, str]] = {}
        for kernel_name, spec in raw_specs.items():
            argv = spec.get("argv", [])
            # argv may contain placeholders like {connection_file} — keep
            # them as-is для caller rendering.
            normalized[kernel_name] = {
                "resource_dir": spec.get("resource_dir", ""),
                "display_name": spec.get("display_name", kernel_name),
                "language": spec.get("language", "python"),
                "argv": json_args(argv),
            }
        self._cache = normalized
        _logger.info(
            "KernelSpecDiscovery: %d kernels available: %s",
            len(normalized),
            list(normalized.keys()),
        )
        return self._cache

    def filter_by_whitelist(self, whitelist: list[str]) -> dict[str, dict[str, str]]:
        """Filter discovered kernels by explicit whitelist.

        Args:
            whitelist: list of kernel names to keep. Empty list
                означает «all kernels» (no filtering).

        Returns:
            Filtered dict (subset of discover_available()).

        Use case: JupyterHubSettings.available_kernels (security
        policy — restrict kernels для multi-tenant deployments).
        """
        all_kernels = self.discover_available()
        if not whitelist:
            return all_kernels
        filtered = {
            name: spec for name, spec in all_kernels.items() if name in whitelist
        }
        # Whitelist entries которых нет в discovery → warning (config
        # drift: settings reference kernel, но не installed).
        missing = set(whitelist) - set(filtered.keys())
        if missing:
            _logger.warning(
                "Kernel whitelist contains kernels not installed locally: %s", missing
            )
        return filtered

    def clear_cache(self) -> None:
        """Invalidate cache (next call re-runs discovery)."""
        self._cache = None


def json_args(argv: list[Any]) -> list[str]:
    """Convert argv list to JSON-serializable list of strings.

    jupyter_client.spec argv may contain strings + connection_file
    template dict. We coerce всё to str.
    """
    return [str(a) for a in argv]
