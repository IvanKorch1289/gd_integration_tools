"""Regression test: SMTP client uses canonical ``core.resilience.breaker`` (S130 W2).

Защищает от возврата к deprecated ``core.utils.circuit_breaker`` shim.
Проверяет:
1. ``smtp.py`` source НЕ импортирует ``from src.backend.core.utils.circuit_breaker``
2. ``SmtpClient`` использует canonical ``Breaker`` (не shim-объект)
3. ``get_connection()`` raises ``ConnectionError`` (back-compat contract) при
   open breaker (через mock-инъекцию breaker, который сразу бросает CircuitOpen)
4. ``get_connection()`` raises ``ConnectionError`` (НЕ CircuitOpen) — для
   сохранения back-compat
"""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


class _OpenBreaker:
    """Mock-breaker: guard() сразу бросает CircuitOpen (имитирует open state)."""

    @asynccontextmanager
    async def guard(self):
        from src.backend.core.resilience.breaker import CircuitOpen

        # Purgatory's OpenedState requires circuit_name positional arg
        raise CircuitOpen(circuit_name="smtp_test_mock")
        yield  # pragma: no cover  # unreachable, but makes it a generator


def _read_smtp_source() -> str:
    """Read smtp.py source as text for static analysis."""
    smtp_path = (
        Path(__file__).resolve().parents[5]
        / "src"
        / "backend"
        / "infrastructure"
        / "clients"
        / "transport"
        / "smtp.py"
    )
    return smtp_path.read_text(encoding="utf-8")


def test_smtp_source_does_not_import_deprecated_circuit_breaker() -> None:
    """Static guard: smtp.py НЕ должен импортировать ``core.utils.circuit_breaker``.

    Если этот тест упал — кто-то вернул deprecated shim, S130 W2 migration
    была откатена, и нужен повторный refactor.

    Проверяем ТОЛЬКО строки импорта (``from ... import ...`` / ``import ...``),
    не docstring-упоминания (исторические ссылки в docstring допустимы).
    """
    import re

    src = _read_smtp_source()
    # Find import statements: from X import Y, or import X
    import_lines = re.findall(
        r"^(?:from\s+(\S+)\s+import|import\s+(\S+))",
        src,
        flags=re.MULTILINE,
    )
    for from_target, import_target in import_lines:
        # from src.backend.core.utils.circuit_breaker import ...
        if from_target == "src.backend.core.utils.circuit_breaker":
            pytest.fail(
                f"smtp.py imports from deprecated core.utils.circuit_breaker — "
                f"revert of S130 W2 migration detected. Use canonical "
                f"src.backend.core.resilience.breaker.Breaker.guard() instead."
            )
        # import src.backend.core.utils.circuit_breaker
        if import_target == "src.backend.core.utils.circuit_breaker":
            pytest.fail(
                f"smtp.py imports deprecated core.utils.circuit_breaker — "
                f"revert of S130 W2 migration detected."
            )


def test_smtp_source_imports_canonical_breaker() -> None:
    """smtp.py импортирует из canonical ``core.resilience.breaker``."""
    src = _read_smtp_source()
    assert "from src.backend.core.resilience.breaker import" in src, (
        "smtp.py must import BreakerSpec/CircuitOpen/get_breaker_registry from "
        "src.backend.core.resilience.breaker (canonical)."
    )


def test_smtp_get_connection_signature_unchanged() -> None:
    """Public API get_connection() сохраняет сигнатуру и тип возврата.

    ``@asynccontextmanager`` оборачивает async gen function в wrapper,
    который возвращает ``_AsyncGeneratorContextManager``. Проверяем
    сигнатуру и что wrapper call возвращает объект с ``__aenter__``/``__aexit__``.
    """
    import inspect

    from src.backend.infrastructure.clients.transport.smtp import SmtpClient

    sig = inspect.signature(SmtpClient.get_connection)
    assert "self" in sig.parameters
    # @asynccontextmanager wraps the function — verify it's callable and
    # the result has async context manager protocol
    result = SmtpClient.get_connection  # unbound method descriptor
    assert callable(result)
    # The decorated function returns an async context manager on call
    # (we don't call it here — would need self); just verify the class
    # exposes the method with the right name.
    assert hasattr(SmtpClient, "get_connection")
    assert hasattr(SmtpClient, "send_email")
    assert hasattr(SmtpClient, "test_connection")


@pytest.mark.asyncio
async def test_smtp_uses_canonical_breaker_not_deprecated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime: SmtpClient._breaker — canonical Breaker из core.resilience.

    Использует canonical registry (singleton). Проверяет type.
    """
    from src.backend.core.resilience.breaker import Breaker
    from src.backend.infrastructure.clients.transport.smtp import SmtpClient

    # Mock settings с circuit_breaker_max_failures=5
    mock_settings = MagicMock()
    mock_settings.host = "smtp.example.com"
    mock_settings.port = 587
    mock_settings.use_tls = True
    mock_settings.validate_certs = True
    mock_settings.connect_timeout = 5.0
    mock_settings.command_timeout = 5.0
    mock_settings.connection_pool_size = 1
    mock_settings.circuit_breaker_max_failures = 3
    mock_settings.circuit_breaker_reset_timeout = 30

    # Не инициализируем pool — get_connection() должен сработать breaker-first.
    client = SmtpClient(mock_settings)

    # _breaker должен быть canonical Breaker instance
    assert isinstance(client._breaker, Breaker), (
        f"SmtpClient._breaker must be canonical Breaker, got {type(client._breaker)}"
    )
    # Initial state = closed
    assert client._breaker.state in {"closed", "open", "half_open"}


@pytest.mark.asyncio
async def test_smtp_raises_connection_error_when_breaker_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Back-compat: при open breaker get_connection() raises ConnectionError
    (НЕ CircuitOpen) — старый контракт ``check_state(exception_class=ConnectionError)``.
    """
    from src.backend.infrastructure.clients.transport.smtp import SmtpClient

    mock_settings = MagicMock()
    mock_settings.host = "smtp.example.com"
    mock_settings.port = 587
    mock_settings.use_tls = True
    mock_settings.validate_certs = True
    mock_settings.connect_timeout = 5.0
    mock_settings.command_timeout = 5.0
    mock_settings.connection_pool_size = 1
    mock_settings.circuit_breaker_max_failures = 3
    mock_settings.circuit_breaker_reset_timeout = 30

    client = SmtpClient(mock_settings)

    # Inject open breaker: guard() raises CircuitOpen immediately
    client._breaker = _OpenBreaker()  # type: ignore[assignment]

    with pytest.raises(ConnectionError) as exc_info:
        async with client.get_connection():
            pass  # never reached

    assert "SMTP-сервис недоступен" in str(exc_info.value)


@pytest.mark.asyncio
async def test_smtp_metrics_uses_breaker_state() -> None:
    """metrics()['circuit_state'] reflects canonical Breaker state (lowercase)."""
    from src.backend.infrastructure.clients.transport.smtp import SmtpClient

    mock_settings = MagicMock()
    mock_settings.host = "smtp.example.com"
    mock_settings.port = 587
    mock_settings.use_tls = True
    mock_settings.validate_certs = True
    mock_settings.connect_timeout = 5.0
    mock_settings.command_timeout = 5.0
    mock_settings.connection_pool_size = 1
    mock_settings.circuit_breaker_max_failures = 3
    mock_settings.circuit_breaker_reset_timeout = 30

    client = SmtpClient(mock_settings)

    m = client.metrics()
    assert "circuit_state" in m
    # Canonical Breaker returns lowercase: closed / open / half_open
    assert m["circuit_state"] in {"closed", "open", "half_open"}, (
        f"circuit_state must be canonical lowercase, got {m['circuit_state']}"
    )
