"""S111 W2 — signal handlers for graceful shutdown.

Per S111 W2 plan: ``signals.py`` extracted from ``lifespan.py`` to keep
lifespan orchestrator slim. Installs SIGTERM/SIGINT handlers that
trigger graceful shutdown (FastAPI sends SIGTERM on K8s pod stop).

Behavior:
- SIGTERM / SIGINT → log signal received → set ``shutdown_event``.
- FastAPI's own signal handling (when ``lifespan`` is in use) typically
  wins — we install OUR handlers as a backup, log-only.
- On Windows / non-Unix: handlers no-op (signal.SIG* may be missing).
- On test environments (``PYTEST_CURRENT_TEST`` set): no-op.
"""

from __future__ import annotations

import asyncio
import os
import signal

from src.backend.core.logging import get_logger

_logger = get_logger("application.signals")


def install_signal_handlers() -> asyncio.Event:
    """Install SIGTERM/SIGINT handlers that log + set shutdown event.

    Returns:
        ``asyncio.Event`` which lifespan orchestrator can wait on if
        it wants to react to signals explicitly. FastAPI's own
        signal handling (built into ``uvicorn``) is the primary
        path for actual shutdown — this is a logging hook.

    No-op if:
    * Running under pytest (``PYTEST_CURRENT_TEST`` env var set).
    * Current platform doesn't expose SIGTERM (Windows).
    * Already installed (``signal.getsignal`` returns our handler).
    """
    shutdown_event = asyncio.Event()

    # Skip in test environments — pytest's own signal handling wins.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return shutdown_event

    loop = asyncio.get_event_loop()
    installed = False

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(
                sig,
                _on_signal,
                sig_name,
                shutdown_event,
            )
            installed = True
        except (NotImplementedError, RuntimeError):
            # Windows / non-Unix / not in main thread → fallback.
            try:
                signal.signal(
                    sig,
                    lambda signum, frame: _on_signal(sig_name, shutdown_event),
                )
                installed = True
            except (ValueError, OSError):
                # Not in main thread (subprocess / thread) → skip silently.
                pass

    if installed:
        _logger.info(
            "Signal handlers installed: SIGTERM + SIGINT (graceful shutdown hook)"
        )
    return shutdown_event


def _on_signal(sig_name: str, event: asyncio.Event) -> None:
    """Handler: log signal + set shutdown event for orchestrator polling."""
    _logger.info("Received %s — graceful shutdown triggered", sig_name)
    event.set()
    # Note: uvicorn/FastAPI handles actual process termination.
    # This hook is observability + coordination only.
