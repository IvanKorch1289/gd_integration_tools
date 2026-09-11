"""Mock connector для route simulation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RecordedCall:
    """Записанный вызов mock connector'а."""

    method: str
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    response: Any = None
    timestamp: float = 0.0
    duration_ms: float = 0.0


class MockConnector:
    """In-memory mock для external systems (DB, HTTP, MQ, file).

    Поддерживает:
    - Запись всех вызовов.
    - Программируемые responses (per-method).
    - Default responses.

    Не делает реальных side effects.
    """

    def __init__(
        self,
        *,
        name: str,
        default_response: Any = None,
    ) -> None:
        self.name = name
        self.calls: list[RecordedCall] = []
        self._responses: dict[str, Any] = {}
        self._default_response = default_response

    def set_response(self, method: str, response: Any) -> None:
        """Программируемый response для метода."""
        self._responses[method] = response

    def record(
        self,
        method: str,
        *args: Any,
        response: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Записать вызов и вернуть programmed response.

        Args:
            method: имя метода (для inspection).
            *args: positional args.
            response: override response (default = programmed/default).
            **kwargs: keyword args.

        Returns:
            Configured response.

        """
        start = time.time()
        # Resolve response: explicit > programmed > default.
        actual_response = response
        if actual_response is None:
            actual_response = self._responses.get(method, self._default_response)
        duration_ms = (time.time() - start) * 1000
        self.calls.append(
            RecordedCall(
                method=method,
                args=args,
                kwargs=kwargs,
                response=actual_response,
                timestamp=time.time(),
                duration_ms=duration_ms,
            )
        )
        return actual_response

    def reset(self) -> None:
        """Очистить все recorded calls."""
        self.calls.clear()
        self._responses.clear()

    @property
    def call_count(self) -> int:
        """Количество записанных вызовов."""
        return len(self.calls)

    def __repr__(self) -> str:
        return f"MockConnector(name={self.name!r}, calls={len(self.calls)})"
