"""Unit tests for src.backend.core.di.providers.workflow (T-P1.2c split)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.core.di.providers import workflow


@pytest.fixture(autouse=True)
def _reset_workflow_providers():
    yield
    workflow._overrides.clear()


class TestActionBusService:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_bus")
        workflow.set_action_bus_service_provider(mock)
        assert workflow.get_action_bus_service_provider() is mock


class TestActionDispatcher:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_dispatcher")
        workflow.set_action_dispatcher_provider(mock)
        assert workflow.get_action_dispatcher_provider() is mock

    def test_set_none_resets(self) -> None:
        workflow.set_action_dispatcher_provider(MagicMock(name="v1"))
        workflow.set_action_dispatcher_provider(None)
        # No exception
        workflow.get_action_dispatcher_provider()


class TestSchedulerManager:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_scheduler")
        workflow.set_scheduler_manager_provider(mock)
        assert workflow.get_scheduler_manager_provider() is mock


class TestWorkflowEventStore:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_event_store")
        workflow.set_workflow_event_store_provider(mock)
        assert workflow.get_workflow_event_store_provider() is mock


class TestWorkflowStateStore:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_state_store")
        workflow.set_workflow_state_store_provider(mock)
        assert workflow.get_workflow_state_store_provider() is mock


class TestWorkflowStateRowClass:
    def test_get_only(self) -> None:
        from src.backend.core.di.providers.workflow import (
            get_workflow_state_row_class_provider,
        )

        assert callable(get_workflow_state_row_class_provider)


class TestWorkflowMainSession:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_main_session")
        workflow.set_workflow_main_session_provider(mock)
        assert workflow.get_workflow_main_session_provider() is mock


class TestWorkflowInstanceModel:
    def test_get_only(self) -> None:
        from src.backend.core.di.providers.workflow import (
            get_workflow_instance_model_provider,
        )

        assert callable(get_workflow_instance_model_provider)


class TestWorkflowStatusEnum:
    def test_get_only(self) -> None:
        from src.backend.core.di.providers.workflow import (
            get_workflow_status_enum_provider,
        )

        assert callable(get_workflow_status_enum_provider)


class TestResilienceCoordinator:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_coord")
        workflow.set_resilience_coordinator_provider(mock)
        assert workflow.get_resilience_coordinator_provider() is mock


class TestResilienceComponentsReport:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_report")
        workflow.set_resilience_components_report_provider(mock)
        assert workflow.get_resilience_components_report_provider() is mock


class TestRateLimiter:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_rl")
        workflow.set_rate_limiter_provider(mock)
        assert workflow.get_rate_limiter_provider() is mock

    def test_classes_get_only(self) -> None:
        from src.backend.core.di.providers.workflow import (
            get_rate_limit_classes_provider,
        )

        assert callable(get_rate_limit_classes_provider)


class TestLoggers:
    def test_app_logger_set(self) -> None:
        mock = MagicMock(name="custom_app")
        workflow.set_app_logger_provider(mock)
        assert workflow.get_app_logger_provider() is mock

    def test_grpc_logger_set(self) -> None:
        mock = MagicMock(name="custom_grpc")
        workflow.set_grpc_logger_provider(mock)
        assert workflow.get_grpc_logger_provider() is mock

    def test_stream_logger_set(self) -> None:
        mock = MagicMock(name="custom_stream")
        workflow.set_stream_logger_provider(mock)
        assert workflow.get_stream_logger_provider() is mock


class TestCorrelationContextSetter:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_setter")
        workflow.set_correlation_context_setter_provider(mock)
        assert workflow.get_correlation_context_setter_provider() is mock


class TestWorkflowModuleIsolation:
    def test_overrides_isolated(self) -> None:
        workflow.set_action_dispatcher_provider("DISP")
        workflow.set_rate_limiter_provider("RL")
        workflow.set_app_logger_provider("LOG")
        assert workflow.get_action_dispatcher_provider() == "DISP"
        assert workflow.get_rate_limiter_provider() == "RL"
        assert workflow.get_app_logger_provider() == "LOG"
