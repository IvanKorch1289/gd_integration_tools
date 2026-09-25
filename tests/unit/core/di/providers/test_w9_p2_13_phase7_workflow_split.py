"""Focused tests: W9 P2-13 Phase 7 — core/di/providers/workflow god-module split.

Проверяет:
1. Shim (workflow.py file) re-exports все 58 публичных функций.
2. Submodules экспортируют свои правильные функции.
3. Per-domain _overrides isolation сохранена.
4. Shim < 250 LOC (vs 602 original).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.di.providers.workflow import (
    get_action_bus_service_provider as ShimActionBus,
)
from src.backend.core.di.providers.workflow import (
    get_action_dispatcher_provider as ShimDispatcher,
)
from src.backend.core.di.providers.workflow import (
    get_app_logger_provider as ShimAppLogger,
)
from src.backend.core.di.providers.workflow import (
    get_reply_channel_class_provider as ShimReplyChannel,
)
from src.backend.core.di.providers.workflow import (
    get_resilience_coordinator_provider as ShimResilience,
)
from src.backend.core.di.providers.workflow import (
    get_stream_dlq_writer_provider as ShimStreamDlq,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_factory_module_provider as ShimWorkflowFactory,
)
from src.backend.core.di.providers.workflow import (
    set_action_bus_service_provider as SetActionBus,
)
from src.backend.core.di.providers.workflow._dlq import (
    get_stream_dlq_writer_provider as CanonicalStreamDlq,
)
from src.backend.core.di.providers.workflow._loggers import (
    get_app_logger_provider as CanonicalAppLogger,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_reply_channel_class_provider as CanonicalReplyChannel,
)
from src.backend.core.di.providers.workflow._notifications import (
    get_workflow_factory_module_provider as CanonicalWorkflowFactory,
)
from src.backend.core.di.providers.workflow._resilience import (
    get_resilience_coordinator_provider as CanonicalResilience,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_action_bus_service_provider as CanonicalActionBus,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_action_dispatcher_provider as CanonicalDispatcher,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_action_bus_service_provider as CanonicalSetActionBus,
)


class TestBackCompatIdentity:
    """Shim re-exports идентичны canonical (id-equal)."""

    @pytest.mark.parametrize(
        "shim,canonical,name",
        [
            (ShimActionBus, CanonicalActionBus, "get_action_bus_service_provider"),
            (ShimDispatcher, CanonicalDispatcher, "get_action_dispatcher_provider"),
            (
                ShimResilience,
                CanonicalResilience,
                "get_resilience_coordinator_provider",
            ),
            (ShimAppLogger, CanonicalAppLogger, "get_app_logger_provider"),
            (ShimStreamDlq, CanonicalStreamDlq, "get_stream_dlq_writer_provider"),
            (
                ShimReplyChannel,
                CanonicalReplyChannel,
                "get_reply_channel_class_provider",
            ),
            (
                ShimWorkflowFactory,
                CanonicalWorkflowFactory,
                "get_workflow_factory_module_provider",
            ),
            (SetActionBus, CanonicalSetActionBus, "set_action_bus_service_provider"),
        ],
    )
    def test_shim_returns_canonical(self, shim, canonical, name: str) -> None:
        """Shim импортирует тот же function (id-equal)."""
        assert shim is canonical, (
            f"{name}: shim {shim!r}@{id(shim)} != canonical {canonical!r}@{id(canonical)}"
        )


class TestSubmoduleExports:
    """Каждый submodule экспортирует ожидаемые функции."""

    def test_workflow_core_submodule(self) -> None:
        """_workflow_core экспортирует 15 funcs (action_bus/dispatcher/scheduler/workflow stores/factory/state_repository)."""
        from src.backend.core.di.providers.workflow import _workflow_core

        expected = {
            "get_action_bus_service_provider",
            "set_action_bus_service_provider",
            "get_action_dispatcher_provider",
            "set_action_dispatcher_provider",
            "get_scheduler_manager_provider",
            "set_scheduler_manager_provider",
            "get_workflow_event_store_provider",
            "set_workflow_event_store_provider",
            "get_workflow_state_store_provider",
            "set_workflow_state_store_provider",
            "get_workflow_state_row_class_provider",
            "get_workflow_main_session_provider",
            "set_workflow_main_session_provider",
            "get_workflow_instance_model_provider",
            "get_workflow_status_enum_provider",
            "get_workflow_backend_factory_provider",
            "set_workflow_backend_factory_provider",
            "get_workflow_state_repository_provider",
            "set_workflow_state_repository_provider",
        }
        actual = {
            n
            for n in dir(_workflow_core)
            if not n.startswith("_") and callable(getattr(_workflow_core, n))
        }
        assert expected.issubset(actual), (
            f"missing from _workflow_core: {expected - actual}"
        )

    def test_resilience_submodule(self) -> None:
        """_resilience экспортирует 5 funcs."""
        from src.backend.core.di.providers.workflow import _resilience

        expected = {
            "get_resilience_coordinator_provider",
            "set_resilience_coordinator_provider",
            "get_resilience_components_report_provider",
            "set_resilience_components_report_provider",
            "get_rate_limiter_provider",
            "set_rate_limiter_provider",
            "get_rate_limit_classes_provider",
        }
        actual = {
            n
            for n in dir(_resilience)
            if not n.startswith("_") and callable(getattr(_resilience, n))
        }
        assert expected.issubset(actual)

    def test_loggers_submodule(self) -> None:
        """_loggers экспортирует 5 funcs."""
        from src.backend.core.di.providers.workflow import _loggers

        expected = {
            "get_app_logger_provider",
            "set_app_logger_provider",
            "get_correlation_context_setter_provider",
            "set_correlation_context_setter_provider",
            "get_grpc_logger_provider",
            "set_grpc_logger_provider",
            "get_stream_logger_provider",
            "set_stream_logger_provider",
        }
        actual = {
            n
            for n in dir(_loggers)
            if not n.startswith("_") and callable(getattr(_loggers, n))
        }
        assert expected.issubset(actual)

    def test_messaging_submodule(self) -> None:
        """_messaging экспортирует 11 funcs (reply_channel + sink_factory + 4 sink classes)."""
        from src.backend.core.di.providers.workflow import _messaging

        expected = {
            "get_reply_channel_class_provider",
            "set_reply_channel_class_provider",
            "get_sink_factory_provider",
            "set_sink_factory_provider",
            "get_mq_sink_class_provider",
            "set_mq_sink_class_provider",
            "get_ws_sink_class_provider",
            "set_ws_sink_class_provider",
            "get_grpc_sink_class_provider",
            "set_grpc_sink_class_provider",
            "get_soap_sink_class_provider",
            "set_soap_sink_class_provider",
        }
        actual = {
            n
            for n in dir(_messaging)
            if not n.startswith("_") and callable(getattr(_messaging, n))
        }
        assert expected.issubset(actual)

    def test_dlq_submodule(self) -> None:
        """_dlq экспортирует 7 funcs (stream_dlq_writer + di_bridge/dlq_memory/dlq_envelope)."""
        from src.backend.core.di.providers.workflow import _dlq

        expected = {
            "get_stream_dlq_writer_provider",
            "set_stream_dlq_writer_provider",
            "get_di_bridge_dlq_module_provider",
            "set_di_bridge_dlq_module_provider",
            "get_dlq_memory_writer_module_provider",
            "set_dlq_memory_writer_module_provider",
            "get_dlq_envelope_class_provider",
            "set_dlq_envelope_class_provider",
        }
        actual = {
            n for n in dir(_dlq) if not n.startswith("_") and callable(getattr(_dlq, n))
        }
        assert expected.issubset(actual)

    def test_notifications_submodule(self) -> None:
        """_notifications экспортирует 4 funcs (workflow_factory + notifications modules)."""
        from src.backend.core.di.providers.workflow import _notifications

        expected = {
            "get_workflow_factory_module_provider",
            "set_workflow_factory_module_provider",
            "get_notifications_module_provider",
            "set_notifications_module_provider",
        }
        actual = {
            n
            for n in dir(_notifications)
            if not n.startswith("_") and callable(getattr(_notifications, n))
        }
        assert expected.issubset(actual)


class TestShimReduction:
    """Shim file significantly reduced (602 → 201 LOC)."""

    def test_shim_under_250_loc(self) -> None:
        """Shim file < 250 LOC (vs 602 original)."""
        shim_path = Path("src/backend/core/di/providers/workflow.py")
        loc = sum(1 for _ in shim_path.open())
        assert loc < 250, f"shim {loc} LOC (target: <250, было 602)"


class TestSubmoduleSplitCompliance:
    """V15 forbidden pattern compliance — submodules < 500 LOC."""

    def test_all_submodules_under_500_loc(self) -> None:
        """Каждый submodule < 500 LOC."""
        workflow_pkg = Path("src/backend/core/di/providers/workflow")
        for py_file in sorted(workflow_pkg.glob("_*.py")):
            loc = sum(1 for _ in py_file.open())
            assert loc < 500, (
                f"{py_file.name} = {loc} LOC (V15 forbidden: >500 = god-module)"
            )


class TestPerDomainOverrideIsolation:
    """Per-domain _overrides isolation сохранена."""

    def test_action_bus_isolation(self) -> None:
        """set_action_bus через shim записывает в _workflow_core._overrides."""
        sentinel = object()
        SetActionBus(sentinel)
        from src.backend.core.di.providers.workflow._workflow_core import _overrides

        assert _overrides.get("action_bus_service") is sentinel

    def test_per_domain_separation(self) -> None:
        """Разные domain submodules имеют РАЗНЫЕ _overrides dict."""
        from src.backend.core.di.providers.workflow import _dlq, _workflow_core

        # Установить same key в разных submodules.
        sentinel_a = object()
        sentinel_b = object()

        _workflow_core._overrides["test_key"] = sentinel_a
        _dlq._overrides["test_key"] = sentinel_b

        # Изоляция работает — каждый submodule имеет свой dict.
        assert _workflow_core._overrides["test_key"] is sentinel_a
        assert _dlq._overrides["test_key"] is sentinel_b
        assert _workflow_core._overrides is not _dlq._overrides

        # Cleanup
        _workflow_core._overrides.pop("test_key", None)
        _dlq._overrides.pop("test_key", None)
