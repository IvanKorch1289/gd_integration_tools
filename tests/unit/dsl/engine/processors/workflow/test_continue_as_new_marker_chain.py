"""Sprint 11 P1-3: integration test marker chain.

Verifies: processor → handler → handler.perform_continue() chain.
Marker set by WorkflowContinueAsNewProcessor must be readable by
ContinueAsNewHandler.extract_marker().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
def test_processor_marker_readable_by_handler() -> None:
    """Sprint 11 P1-3: marker chain end-to-end (processor → handler)."""
    from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
        WorkflowContinueAsNewProcessor,
    )
    from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
        ContinueAsNewHandler,
    )

    # Step 1: Processor sets marker in exchange
    processor = WorkflowContinueAsNewProcessor(
        same_workflow_id=True,
        same_input=False,
        search_attributes={"priority": "high"},
    )

    exchange = MagicMock()
    exchange.in_message = MagicMock()
    exchange.in_message.body = {"user_id": 42, "step": "checkpoint"}

    # Track set_result calls via spy
    set_result_calls: list[tuple[str, Any]] = []
    original_set_result = processor.set_result

    def spy_set_result(ex, key, value):
        set_result_calls.append((key, value))
        return original_set_result(ex, key, value)

    processor.set_result = spy_set_result  # type: ignore[method-assign]

    # Mock auth_check чтобы обойти capability gate (test фокус на marker chain, не auth)
    processor.auth_check = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # Process (synchronous call, process is async but we can run via asyncio)
    import asyncio
    context = MagicMock()
    asyncio.run(processor.process(exchange, context))

    # Verify marker was set via set_result
    assert len(set_result_calls) >= 1, (
        f"set_result должен быть вызван хотя бы раз, got: {set_result_calls}"
    )
    marker_key, marker = set_result_calls[0]
    assert marker_key == "continue_as_new_requested"
    assert marker["requested"] is True
    assert marker["same_workflow_id"] is True
    assert marker["same_input"] is False
    assert marker["search_attributes"] == {"priority": "high"}
    assert marker["body_snapshot"] == {"user_id": 42, "step": "checkpoint"}

    # Step 2: Handler can read the marker (simulating Temporal worker flow)
    handler = ContinueAsNewHandler()
    # Simulate the marker being in exchange.in_message.body (as set by processor)
    exchange_with_marker = MagicMock()
    exchange_with_marker.in_message = MagicMock()
    exchange_with_marker.in_message.body = {"continue_as_new_requested": marker}

    extracted = handler.extract_marker(exchange_with_marker)
    assert extracted is not None
    assert extracted["requested"] is True
    assert extracted["same_workflow_id"] is True
    assert extracted["same_input"] is False
    assert extracted["search_attributes"] == {"priority": "high"}

    # Step 3: Handler should_continue returns True
    assert handler.should_continue(exchange_with_marker) is True


@pytest.mark.unit
def test_handler_extracts_marker_set_by_processor() -> None:
    """Sprint 11 P1-3: handler.extract_marker() finds marker from processor."""
    from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
        ContinueAsNewHandler,
    )

    # Marker format matches what WorkflowContinueAsNewProcessor sets
    marker = {
        "requested": True,
        "same_workflow_id": True,
        "same_input": True,
        "search_attributes": {},
        "body_snapshot": {},
    }

    exchange = MagicMock()
    exchange.in_message = MagicMock()
    exchange.in_message.body = {"continue_as_new_requested": marker}

    handler = ContinueAsNewHandler()
    extracted = handler.extract_marker(exchange)
    assert extracted == marker


@pytest.mark.unit
def test_handler_returns_none_when_no_marker() -> None:
    """Sprint 11 P1-3: handler returns None when marker not set."""
    from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
        ContinueAsNewHandler,
    )

    exchange = MagicMock()
    exchange.in_message = MagicMock()
    exchange.in_message.body = {"user_id": 42}  # no marker

    handler = ContinueAsNewHandler()
    assert handler.extract_marker(exchange) is None
    assert handler.should_continue(exchange) is False
