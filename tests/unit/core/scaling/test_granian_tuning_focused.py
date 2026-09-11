"""Focused tests for ``GranianTuning`` (Sprint 24 cont coverage ratchet).

Цель: поднять покрытие ``src/backend/core/scaling/granian_tuning.py``
с ~97% до 100% путём покрытия edge-cases build_cli_command + computed fields.

Контракт API:
- ``GranianTuning`` — Pydantic-settings с YAML-loader.
- ``resolved_workers`` — int|auto → cpu_count (min 2).
- ``resolved_blocking_threads`` — auto → workers*4.
- ``resolved_interface`` — feature-flag gated (RSGI vs ASGI).
- ``build_cli_command(app, host, port, granian_cmd)`` → list[str].
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.scaling.granian_tuning import GranianTuning, granian_tuning


class TestGranianTuningDefaults:
    """``GranianTuning()`` defaults."""

    def test_init_default(self) -> None:
        """Default — все поля с sane defaults."""
        t = GranianTuning()
        assert t.workers == "auto"
        assert t.blocking_threads == "auto"
        assert t.interface in ("rsgi", "asgi")
        assert t.loop in ("uvloop", "asyncio")
        assert t.http in ("auto", "1", "2")
        assert isinstance(t.access_log, bool)
        assert isinstance(t.log_level, str)

    def test_yaml_group(self) -> None:
        """``yaml_group='granian'`` для config_loader."""
        assert GranianTuning.yaml_group == "granian"

    def test_env_prefix(self) -> None:
        """``env_prefix='GRANIAN_'``."""
        assert GranianTuning.model_config["env_prefix"] == "GRANIAN_"


class TestResolvedWorkers:
    """``resolved_workers`` — auto → max(2, cpu_count)."""

    def test_auto_with_cpu_count_2(self) -> None:
        """``workers='auto'`` → max(2, cpu_count)."""
        t = GranianTuning(workers="auto")
        with patch("os.cpu_count", return_value=4):
            result = t.resolved_workers
        assert result == 4

    def test_auto_with_cpu_count_8(self) -> None:
        """``workers='auto'`` с cpu_count=8 → 8."""
        t = GranianTuning(workers="auto")
        with patch("os.cpu_count", return_value=8):
            result = t.resolved_workers
        assert result == 8

    def test_auto_with_cpu_count_1_min_2(self) -> None:
        """``workers='auto'`` с cpu_count=1 → минимум 2."""
        t = GranianTuning(workers="auto")
        with patch("os.cpu_count", return_value=1):
            result = t.resolved_workers
        assert result == 2  # minimum 2 enforced.

    def test_auto_with_cpu_count_none_min_2(self) -> None:
        """``workers='auto'`` с cpu_count=None → минимум 2."""
        t = GranianTuning(workers="auto")
        with patch("os.cpu_count", return_value=None):
            result = t.resolved_workers
        assert result == 2

    def test_explicit_workers_int(self) -> None:
        """``workers=4`` → resolved_workers=4."""
        t = GranianTuning(workers=4)
        assert t.resolved_workers == 4

    def test_explicit_workers_zero(self) -> None:
        """``workers=0`` → 0 (без auto)."""
        t = GranianTuning(workers=0)
        assert t.resolved_workers == 0


class TestResolvedBlockingThreads:
    """``resolved_blocking_threads`` — auto → workers*4."""

    def test_auto_with_workers_2(self) -> None:
        """``blocking_threads='auto', workers=2`` → 8 (2*4)."""
        t = GranianTuning(workers=2, blocking_threads="auto")
        assert t.resolved_blocking_threads == 8

    def test_auto_with_workers_4(self) -> None:
        """``blocking_threads='auto', workers=4`` → 16."""
        t = GranianTuning(workers=4, blocking_threads="auto")
        assert t.resolved_blocking_threads == 16

    def test_explicit_blocking_threads(self) -> None:
        """``blocking_threads=100`` → 100."""
        t = GranianTuning(blocking_threads=100)
        assert t.resolved_blocking_threads == 100


class TestResolvedInterface:
    """``resolved_interface`` — feature-flag gated."""

    def test_flag_off_returns_asgi(self) -> None:
        """``granian_rsgi_mode_enabled=False`` → 'asgi'."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = False
            t = GranianTuning(interface="rsgi")
            assert t.resolved_interface == "asgi"
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_flag_on_returns_interface(self) -> None:
        """``granian_rsgi_mode_enabled=True`` → 'rsgi'."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(interface="rsgi")
            assert t.resolved_interface == "rsgi"
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_flag_on_asgi(self) -> None:
        """``granian_rsgi_mode_enabled=True, interface='asgi'`` → 'asgi'."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(interface="asgi")
            assert t.resolved_interface == "asgi"
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_feature_flags_import_failure_returns_asgi(self) -> None:
        """``feature_flags`` import failure → 'asgi' (fail-safe)."""
        import sys

        # Force ImportError by removing module temporarily.
        saved = sys.modules.pop(
            "src.backend.core.config.features", None
        )
        try:
            # Patch the import to raise.
            import builtins

            original_import = builtins.__import__

            def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
                if "config.features" in name:
                    raise ImportError("forced for test")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = mock_import
            try:
                t = GranianTuning(interface="rsgi")
                assert t.resolved_interface == "asgi"
            finally:
                builtins.__import__ = original_import
        finally:
            if saved is not None:
                sys.modules["src.backend.core.config.features"] = saved


class TestBuildCliCommand:
    """``build_cli_command()`` — формирует список args."""

    def test_basic_command(self) -> None:
        """Базовая команда: granian --interface ... --host ... --port ... etc."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2, blocking_threads=4)
            cmd = t.build_cli_command(app="src.main:app")
            assert cmd[0] == "granian"
            assert "--interface" in cmd
            assert "--host" in cmd
            assert "--port" in cmd
            assert "--workers" in cmd
            assert "--loop" in cmd
            assert "--http" in cmd
            assert "--log-level" in cmd
            assert "--backlog" in cmd
            assert "--threads" in cmd
            assert "src.main:app" in cmd[-1]
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_custom_host_port(self) -> None:
        """Custom host/port."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2)
            cmd = t.build_cli_command(
                app="src.app:app", host="0.0.0.0", port=9000
            )
            host_idx = cmd.index("--host")
            assert cmd[host_idx + 1] == "0.0.0.0"
            port_idx = cmd.index("--port")
            assert cmd[port_idx + 1] == "9000"
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_custom_granian_cmd(self) -> None:
        """Custom granian_cmd — single-token (e.g., ``granian2``)."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2)
            cmd = t.build_cli_command(app="x:y", granian_cmd="granian2")
            assert cmd[0] == "granian2"
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_access_log_flag(self) -> None:
        """``access_log=True`` добавляет ``--access-log``."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2, access_log=True)
            cmd = t.build_cli_command(app="x:y")
            assert "--access-log" in cmd
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_no_access_log_flag_when_false(self) -> None:
        """``access_log=False`` не добавляет ``--access-log``."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2, access_log=False)
            cmd = t.build_cli_command(app="x:y")
            assert "--access-log" not in cmd
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_workers_kill_timeout_positive(self) -> None:
        """``granian_kill_timeout > 0`` → ``--workers-kill-timeout N``."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2, granian_kill_timeout=30)
            cmd = t.build_cli_command(app="x:y")
            idx = cmd.index("--workers-kill-timeout")
            assert cmd[idx + 1] == "30"
        finally:
            feature_flags.granian_rsgi_mode_enabled = original

    def test_workers_kill_timeout_zero_no_flag(self) -> None:
        """``granian_kill_timeout=0`` → нет флага."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.granian_rsgi_mode_enabled
        try:
            feature_flags.granian_rsgi_mode_enabled = True
            t = GranianTuning(workers=2, granian_kill_timeout=0)
            cmd = t.build_cli_command(app="x:y")
            assert "--workers-kill-timeout" not in cmd
        finally:
            feature_flags.granian_rsgi_mode_enabled = original


class TestSingleton:
    """Module-level ``granian_tuning`` singleton."""

    def test_singleton_exists(self) -> None:
        """``granian_tuning`` — instance GranianTuning."""
        assert isinstance(granian_tuning, GranianTuning)

    def test_singleton_has_resolved_workers(self) -> None:
        """Singleton имеет resolved_workers attribute."""
        assert hasattr(granian_tuning, "resolved_workers")
        assert isinstance(granian_tuning.resolved_workers, int)


class TestModuleExports:
    """``__all__`` exports."""

    def test_all_count(self) -> None:
        """``__all__`` содержит 2 symbols."""
        from src.backend.core.scaling import granian_tuning

        assert len(granian_tuning.__all__) == 2

    def test_all_names(self) -> None:
        """``GranianTuning`` + ``granian_tuning`` в ``__all__``."""
        from src.backend.core.scaling import granian_tuning

        assert "GranianTuning" in granian_tuning.__all__
        assert "granian_tuning" in granian_tuning.__all__
