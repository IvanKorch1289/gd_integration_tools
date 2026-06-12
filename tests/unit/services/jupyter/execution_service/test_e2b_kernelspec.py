"""S75 W4 — tests для E2BExecutionBackend + KernelSpecDiscovery
(FINAL_REPORT_V2 #2 + направление #1 multi-kernels closure)."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from unittest.mock import MagicMock, patch

import pytest


# E2BExecutionBackend tests
# ============================================================================


def test_e2b_backend_uses_env_api_key() -> None:
    """E2BExecutionBackend берёт E2B_API_KEY из env если не передан."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
    )

    os.environ["E2B_API_KEY"] = "e2b_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    backend = E2BExecutionBackend()
    assert backend.api_key_configured is True


def test_e2b_backend_no_api_key() -> None:
    """Без API key (no env, no arg) → api_key_configured = False."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
    )

    os.environ.pop("E2B_API_KEY", None)
    backend = E2BExecutionBackend()
    assert backend.api_key_configured is False


def test_e2b_backend_explicit_api_key_overrides_env() -> None:
    """Explicit api_key arg приоритетнее env."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
    )

    os.environ["E2B_API_KEY"] = "e2b_env_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    backend = E2BExecutionBackend(
        api_key="e2b_explicit_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    assert backend._api_key == "e2b_explicit_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_e2b_execute_raises_without_api_key() -> None:
    """execute_with_params без API key → E2BExecutionError (fail-loud)."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
    )
    from src.backend.services.jupyter.execution_service.e2b_backend import (
        E2BExecutionError,
    )

    os.environ.pop("E2B_API_KEY", None)
    backend = E2BExecutionBackend()

    with tempfile.NamedTemporaryFile(suffix=".ipynb", delete=False) as f:
        f.write(b"{}")
        nb_path = f.name

    try:
        with pytest.raises(E2BExecutionError, match="E2B_API_KEY not set"):
            await backend.execute_with_params(
                notebook_path=nb_path, parameters={"x": 1}
            )
    finally:
        os.unlink(nb_path)


@pytest.mark.asyncio
async def test_e2b_execute_notebook_not_found() -> None:
    """execute_with_params с несуществующим path → FileNotFoundError."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
    )

    backend = E2BExecutionBackend(api_key="e2b_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    with pytest.raises(FileNotFoundError, match="Notebook не найден"):
        await backend.execute_with_params(
            notebook_path="/nonexistent/notebook.ipynb",
            parameters={"x": 1},
        )


@pytest.mark.asyncio
async def test_e2b_inject_parameters() -> None:
    """_inject_parameters adds assignment lines для each param."""
    from src.backend.services.jupyter.execution_service.e2b_backend import (
        E2BExecutionBackend,
    )

    source = "x = 1\ny = 2"
    result = E2BExecutionBackend._inject_parameters(
        source, {"alpha": 100, "beta": "hello"}
    )
    assert "x = 1" in result
    assert "alpha = 100" in result
    assert "beta = 'hello'" in result  # repr() для strings
    assert "injected parameters" in result


# Factory integration tests
# ============================================================================


def test_factory_creates_e2b_backend_no_key() -> None:
    """factory.create('e2b') → E2BExecutionBackend (lazy key validation)."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
        ExecutionBackendFactory,
    )

    os.environ.pop("E2B_API_KEY", None)
    factory = ExecutionBackendFactory()
    backend = factory.create("e2b")
    assert isinstance(backend, E2BExecutionBackend)
    assert backend.api_key_configured is False


def test_factory_creates_e2b_backend_with_key() -> None:
    """factory.create('e2b', api_key=...) → E2BExecutionBackend with key."""
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
        ExecutionBackendFactory,
    )

    factory = ExecutionBackendFactory()
    backend = factory.create(
        "e2b",
        api_key="e2b_test_cccccccccccccccccccccccccccccccc",
    )
    assert isinstance(backend, E2BExecutionBackend)
    assert backend.api_key_configured is True


# KernelSpecDiscovery tests
# ============================================================================


def test_kernelspec_discovery_fallback() -> None:
    """Если jupyter_client не установлен → DEFAULT_FALLBACK_SPECS."""
    from src.backend.services.jupyter.execution_service import (
        DEFAULT_FALLBACK_SPECS,
        KernelSpecDiscovery,
    )

    # Simulate jupyter_client missing
    import sys

    original = sys.modules.get("jupyter_client.kernelspec")
    sys.modules["jupyter_client.kernelspec"] = None  # force ImportError

    try:
        d = KernelSpecDiscovery()
        d.clear_cache()
        kernels = d.discover_available()
        assert kernels == DEFAULT_FALLBACK_SPECS
        assert "python3" in kernels
    finally:
        if original is not None:
            sys.modules["jupyter_client.kernelspec"] = original
        else:
            sys.modules.pop("jupyter_client.kernelspec", None)


def test_kernelspec_discovery_cached() -> None:
    """Первый вызов → discovery; второй → cache (same instance)."""
    from src.backend.services.jupyter.execution_service import (
        KernelSpecDiscovery,
    )

    d = KernelSpecDiscovery()
    d.clear_cache()
    k1 = d.discover_available()
    k2 = d.discover_available()
    assert k1 is k2, "Second call should return cached dict (same object)"


def test_kernelspec_clear_cache() -> None:
    """clear_cache() → следующий call re-discovers."""
    from src.backend.services.jupyter.execution_service import (
        KernelSpecDiscovery,
    )

    d = KernelSpecDiscovery()
    d.clear_cache()
    k1 = d.discover_available()
    d.clear_cache()
    k2 = d.discover_available()
    # После clear, dict NEW (но content same если discovery consistent)
    assert k1 == k2


def test_kernelspec_filter_by_whitelist_empty() -> None:
    """Empty whitelist → all kernels."""
    from src.backend.services.jupyter.execution_service import (
        DEFAULT_FALLBACK_SPECS,
        KernelSpecDiscovery,
    )

    # Force fallback
    import sys

    original = sys.modules.get("jupyter_client.kernelspec")
    sys.modules["jupyter_client.kernelspec"] = None

    try:
        d = KernelSpecDiscovery()
        d.clear_cache()
        all_kernels = d.discover_available()
        filtered = d.filter_by_whitelist([])
        assert filtered == all_kernels
        # Should contain python3 (from fallback)
        assert "python3" in filtered
    finally:
        if original is not None:
            sys.modules["jupyter_client.kernelspec"] = original
        else:
            sys.modules.pop("jupyter_client.kernelspec", None)


def test_kernelspec_filter_by_whitelist_subset() -> None:
    """Whitelist filter применяется к discovered kernels."""
    from src.backend.services.jupyter.execution_service import (
        KernelSpecDiscovery,
    )

    # Mock jupyter_client to return multi-kernel specs
    import sys

    mock_ksm = MagicMock()
    mock_ksm.get_all_specs.return_value = {
        "python3": {
            "resource_dir": "/kernels/python3",
            "display_name": "Python 3",
            "language": "python",
            "argv": ["python3", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        },
        "ir": {
            "resource_dir": "/kernels/ir",
            "display_name": "R",
            "language": "R",
            "argv": ["R", "--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"],
        },
        "julia-1.6": {
            "resource_dir": "/kernels/julia-1.6",
            "display_name": "Julia 1.6",
            "language": "julia",
            "argv": ["julia", "-i", "--startup-file=no", "{connection_file}"],
        },
    }
    fake_module = MagicMock()
    fake_module.KernelSpecManager = MagicMock(return_value=mock_ksm)
    original = sys.modules.get("jupyter_client.kernelspec")
    sys.modules["jupyter_client.kernelspec"] = fake_module

    try:
        d = KernelSpecDiscovery()
        d.clear_cache()
        all_kernels = d.discover_available()
        assert "python3" in all_kernels
        assert "ir" in all_kernels
        assert "julia-1.6" in all_kernels

        # Whitelist только python3 + ir
        filtered = d.filter_by_whitelist(["python3", "ir"])
        assert "python3" in filtered
        assert "ir" in filtered
        assert "julia-1.6" not in filtered
    finally:
        if original is not None:
            sys.modules["jupyter_client.kernelspec"] = original
        else:
            sys.modules.pop("jupyter_client.kernelspec", None)


def test_kernelspec_filter_whitelist_drift_warning() -> None:
    """Whitelist reference missing kernel → warning (не error)."""
    from src.backend.services.jupyter.execution_service import (
        KernelSpecDiscovery,
    )

    import sys

    # Only python3 available
    mock_ksm = MagicMock()
    mock_ksm.get_all_specs.return_value = {
        "python3": {
            "resource_dir": "/k/p3",
            "display_name": "Python 3",
            "language": "python",
            "argv": ["python3", "-m", "ipykernel"],
        },
    }
    fake_module = MagicMock()
    fake_module.KernelSpecManager = MagicMock(return_value=mock_ksm)
    original = sys.modules.get("jupyter_client.kernelspec")
    sys.modules["jupyter_client.kernelspec"] = fake_module

    try:
        d = KernelSpecDiscovery()
        d.clear_cache()
        # Whitelist references несуществующий kernel "ir"
        filtered = d.filter_by_whitelist(["python3", "ir"])
        # Только python3 остаётся
        assert "python3" in filtered
        assert "ir" not in filtered
        # Warning logged (test passed = no exception raised)
    finally:
        if original is not None:
            sys.modules["jupyter_client.kernelspec"] = original
        else:
            sys.modules.pop("jupyter_client.kernelspec", None)


def test_default_fallback_specs_structure() -> None:
    """DEFAULT_FALLBACK_SPECS имеет правильную structure (resource_dir, display_name, language, argv)."""
    from src.backend.services.jupyter.execution_service import (
        DEFAULT_FALLBACK_SPECS,
    )

    assert "python3" in DEFAULT_FALLBACK_SPECS
    spec = DEFAULT_FALLBACK_SPECS["python3"]
    assert "resource_dir" in spec
    assert "display_name" in spec
    assert "language" in spec
    assert "argv" in spec
    assert spec["language"] == "python"
    assert isinstance(spec["argv"], list)
