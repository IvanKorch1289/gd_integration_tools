"""P2 regression test (Cycle 10, production-grade plan).

``PgRunnerBackend.await_completion`` / ``await_external_signal`` emit
``DeprecationWarning`` на каждом вызове. Production callers должны
мигрировать на ``TemporalWorkflowBackend``.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/infrastructure/workflow/test_pg_runner_deprecation_warning.py -v
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.workflow.backend import WorkflowHandle
from src.backend.infrastructure.workflow.pg_runner_backend import (
    PgRunnerWorkflowBackend,
)


@pytest.fixture
def backend() -> PgRunnerWorkflowBackend:
    """Mock PgRunnerBackend с stub state/event stores."""
    state_store = MagicMock()
    state_store.get = AsyncMock(return_value=None)
    event_store = MagicMock()
    event_store.latest_seq = AsyncMock(return_value=0)
    event_store.read_events = AsyncMock(return_value=[])

    backend = PgRunnerWorkflowBackend.__new__(PgRunnerWorkflowBackend)
    backend._state_store = state_store
    backend._event_store = event_store
    backend._poll_interval_s = 0.001  # very fast poll
    backend._poll_max_interval_s = 0.005
    return backend


@pytest.fixture
def handle() -> WorkflowHandle:
    """Stub WorkflowHandle."""
    import uuid

    return WorkflowHandle(
        workflow_id="test_wf",
        run_id=str(uuid.uuid4()),
        namespace="default",
    )


class TestAwaitCompletionDeprecation:
    """``await_completion`` эмитит DeprecationWarning."""

    def test_emits_deprecation_warning(
        self, backend: PgRunnerWorkflowBackend, handle: WorkflowHandle
    ) -> None:
        """Вызов await_completion с коротким timeout → DeprecationWarning."""
        import asyncio

        # state_store.get возвращает None → raise KeyError (до timeout)
        # но мы перехватываем только warning
        with pytest.warns(DeprecationWarning, match="await_completion deprecated"):
            try:
                asyncio.run(
                    asyncio.wait_for(
                        backend.await_completion(handle=handle),
                        timeout=1.0,
                    )
                )
            except (KeyError, asyncio.TimeoutError):
                pass


class TestAwaitExternalSignalDeprecation:
    """``await_external_signal`` эмитит DeprecationWarning."""

    def test_emits_deprecation_warning(
        self, backend: PgRunnerWorkflowBackend, handle: WorkflowHandle
    ) -> None:
        """Вызов await_external_signal с timeout → DeprecationWarning.

        timeout=timedelta(milliseconds=1) → сразу timed_out после первого
        polling iteration. Тест проверяет только warning emission.
        """
        import asyncio

        with pytest.warns(
            DeprecationWarning, match="await_external_signal deprecated"
        ):
            try:
                asyncio.run(
                    asyncio.wait_for(
                        backend.await_external_signal(
                            handle=handle,
                            signal_name="test_signal",
                            timeout=timedelta(milliseconds=50),
                        ),
                        timeout=1.0,
                    )
                )
            except (asyncio.TimeoutError, Exception):
                pass

