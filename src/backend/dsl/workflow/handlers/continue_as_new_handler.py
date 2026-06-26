"""ContinueAsNew runtime handler (S171 M10 P0).

Per https://docs.temporal.io/best-practices/worker#manage-event-history-growth,
worker должен прочитать marker из exchange и вызвать
``temporalio.workflow.continue_as_new()``.

Этот модуль — runtime-сторона маркера, который ставит
:class:`WorkflowContinueAsNewProcessor` в DSL.

Pattern (Ponytail, D169): handler — тонкая обёртка, lazy temporalio import.
"""
from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.workflow.continue_as_new_handler")

__all__ = ("ContinueAsNewHandler",)

_MARKER_KEY = "continue_as_new_requested"


class ContinueAsNewHandler:
    """Обработчик маркера Continue-As-New в exchange.

    Используется в Temporal worker'е после каждого workflow step.
    Если в exchange есть marker — handler формирует аргументы
    для ``workflow.continue_as_new()`` и вызывает его.
    """

    def extract_marker(self, exchange: Any) -> dict[str, Any] | None:
        """Извлечь marker из exchange (если есть)."""
        if not hasattr(exchange, "in_message"):
            return None
        body = getattr(exchange.in_message, "body", None)
        if not isinstance(body, dict):
            return None
        marker = body.get(_MARKER_KEY)
        if not isinstance(marker, dict):
            return None
        if not marker.get("requested"):
            return None
        return marker

    def should_continue(self, exchange: Any) -> bool:
        """Должен ли worker вызвать ``continue_as_new()``?"""
        return self.extract_marker(exchange) is not None

    def build_continue_args(
        self,
        marker: dict[str, Any],
        *,
        current_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Сформировать kwargs для ``workflow.continue_as_new()``.

        Args:
            marker: Marker из :meth:`extract_marker`.
            current_input: Текущий input workflow (для случая ``same_input=True``).

        Returns:
            Dict с ключами ``input`` и ``search_attributes``
            для передачи в ``temporalio.workflow.continue_as_new(**kwargs)``.
        """
        if marker.get("same_input") and current_input is not None:
            input_data: Any = current_input
        else:
            input_data = marker.get("body_snapshot", current_input or {})
        return {
            "input": input_data,
            "search_attributes": marker.get("search_attributes", {}),
        }

    def perform_continue(
        self,
        marker: dict[str, Any],
        *,
        current_input: dict[str, Any] | None = None,
    ) -> None:
        """Вызвать ``temporalio.workflow.continue_as_new()``.

        Lazy import: temporalio SDK ~15-20MB, не подтягиваем до первого вызова.
        Должен вызываться ТОЛЬКО внутри Temporal workflow context.
        """
        try:
            from temporalio import workflow
        except ImportError as exc:
            _logger.warning(
                "continue_as_new.temporalio.unavailable",
                extra={"hint": "pip install temporalio"},
            )
            raise ImportError(
                "temporalio не установлен — ContinueAsNew недоступен"
            ) from exc

        args = self.build_continue_args(marker, current_input=current_input)
        _logger.info(
            "continue_as_new invoked input_keys=%s search_attrs=%s",
            list(args["input"].keys()) if isinstance(args["input"], dict) else "?",
            list(args["search_attributes"].keys()),
        )
        # workflow.continue_as_new — Temporal API
        workflow.continue_as_new(
            *(args["input"],) if isinstance(args["input"], list) else (),
            **args,
        )
