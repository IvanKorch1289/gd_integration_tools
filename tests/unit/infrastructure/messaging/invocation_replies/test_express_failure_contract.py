"""P2 (2026-10-15) audit: behavioral test для messaging failure contract.

Audit P2 говорит: переименование ``except Exception as _`` →
``except Exception as exc`` + logger.exception — НЕ достаточно.
Главный вопрос: что получает caller при сбое reply-канала?

Возможные минимально совместимые контракты:

1. **typed error result** — channel.send() возвращает error-envelope
   вместо ``None``, caller видит failure явно;
2. **DLQ** — failed reply пишется в DLQ для retry, channel.send()
   не блокирует;
3. **re-raise typed exception** — channel.send() бросает
   ``ReplyChannelFailure``, caller решает retry/skip;
4. **documented fail-safe** — channel.send() возвращает ``None``,
   но failure записывается в metric/audit (silent для caller,
   visible для observability).

Текущая реализация (express.py, Proposal 4): **option 4** —
logger.exception + return (silent для caller). Audit требует
behavioral test, который ПРОВЕРЯЕТ что это действительно visible
в observability, а не silent data loss.

Этот файл — не mass-rewrite. Behavioral test, который фиксирует
контракт: ``send()`` failure логируется с exc_type и не теряет
invocation_id. Если кто-то поменяет на silent (без лога) или
на raise (без documented contract) — тест упадёт.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.backend.core.interfaces.invoker import (
    InvocationResponse,
    InvocationStatus,
)
from src.backend.infrastructure.messaging.invocation_replies.express import (
    ExpressReplyChannel,
)


# ─────────────────────────── helpers ───────────────────────────


def _make_response(
    *,
    invocation_id: str = "inv-audit-p2-001",
    status: InvocationStatus = InvocationStatus.OK,
    metadata: dict[str, Any] | None = None,
    result: Any = "ok",
    error: str | None = None,
) -> InvocationResponse:
    return InvocationResponse(
        invocation_id=invocation_id,
        status=status,
        result=result,
        error=error,
        metadata=metadata or {},
    )


class _FailingNotifier:
    """Notifier который raise'ит — для проверки failure contract."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self._call_count = 0
        self._last_kwargs: dict[str, Any] | None = None

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        self._call_count += 1
        self._last_kwargs = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "metadata": metadata,
        }
        raise self._exc


# ─────────────────────────── tests ───────────────────────────


class TestExpressReplyFailureContract:
    """Failure contract: send() сбой notifier НЕ теряет reply silently."""

    @pytest.mark.asyncio
    async def test_notifier_failure_does_not_lose_invocation_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Notifie raise'ит → invocation_id попадает в log record.

        Audit P2: «проверить не только наличие лог-записи, но и
        результат, который получает caller, а также отсутствие
        бесшумной потери reply».

        Caller получает ``None`` (no return value), но failure
        visible в логе с invocation_id — caller мониторит по
        logger.error/critical.
        """
        notifier = _FailingNotifier(RuntimeError("express API down"))
        channel = ExpressReplyChannel(
            notifier=notifier, default_chat_id="chat-1"
        )
        response = _make_response(invocation_id="inv-must-survive-1")

        with caplog.at_level(logging.ERROR, logger="messaging.invocation_replies.express"):
            # send() НЕ raise (fail-safe documented)
            result = await channel.send(response)

        # Caller получает None (no return value, fail-safe)
        assert result is None, (
            f"send() should return None on failure (fail-safe contract); "
            f"got {result!r}"
        )
        # Notifier был вызван — failure НЕ silent skip
        assert notifier._call_count == 1, (
            "Notifier не вызван — silent skip, не failure"
        )
        # invocation_id попал в лог (anti data-loss contract)
        log_text = " ".join(r.message for r in caplog.records)
        assert "inv-must-survive-1" in log_text, (
            f"invocation_id потерян в логах: {log_text!r}; "
            "regression: silent data loss"
        )
        # exc type залогирован (observability)
        assert "RuntimeError" in log_text, (
            f"exc_type не залогирован: {log_text!r}; "
            "regression: Proposal 4 fix откатился"
        )

    @pytest.mark.asyncio
    async def test_notifier_failure_logs_exc_type_not_just_str(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Лог содержит ``type(exc).__name__``, не только ``str(exc)``.

        Без ``exc_type`` SRE не может алертить на конкретный exception
        class (например, ``ConnectionError`` vs ``TimeoutError``).
        """
        notifier = _FailingNotifier(ConnectionError("network blip"))
        channel = ExpressReplyChannel(notifier=notifier, default_chat_id="chat-2")
        response = _make_response(invocation_id="inv-exc-type-test")

        with caplog.at_level(logging.ERROR, logger="messaging.invocation_replies.express"):
            await channel.send(response)

        log_text = " ".join(r.message for r in caplog.records)
        # exc_type в формате "exc_type=ConnectionError" или похожем
        assert "ConnectionError" in log_text
        # Проверяем что exc_type явно упомянут (а не только str(exc))
        assert "exc_type" in log_text or "ConnectionError" in log_text, (
            f"exc_type не виден в логе: {log_text!r}"
        )

    @pytest.mark.asyncio
    async def test_no_chat_id_skips_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Нет chat_id в metadata + нет default → skip + warning.

        Это documented fail-safe: если некуда доставить, log
        warning с invocation_id и skip. Caller не получает
        exception, но failure visible в observability.
        """
        notifier = _FailingNotifier(RuntimeError("should not be called"))
        channel = ExpressReplyChannel(
            notifier=notifier,
            default_chat_id=None,  # НЕТ default
        )
        response = _make_response(
            invocation_id="inv-no-chat-id",
            metadata={},  # НЕТ chat_id в metadata
        )

        with caplog.at_level(logging.WARNING, logger="messaging.invocation_replies.express"):
            await channel.send(response)

        log_text = " ".join(r.message for r in caplog.records)
        assert "inv-no-chat-id" in log_text
        # Notifier не вызван — early return
        assert notifier._call_count == 0

    @pytest.mark.asyncio
    async def test_successful_delivery_does_not_log_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Happy path — нет ERROR-level логов.

        Regression-protection: ensure что success path НЕ шумит
        error-логами (это бы сделало shipping noisy alerting).
        """

        class _OKNotifier:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def send(
                self,
                *,
                recipient: str,
                subject: str,
                body: str,
                metadata: dict[str, Any],
            ) -> None:
                self.calls.append(
                    {"recipient": recipient, "subject": subject, "body": body}
                )

        notifier = _OKNotifier()
        channel = ExpressReplyChannel(
            notifier=notifier, default_chat_id="chat-ok"
        )
        response = _make_response(invocation_id="inv-ok-1", result={"data": 42})

        with caplog.at_level(logging.ERROR, logger="messaging.invocation_replies.express"):
            await channel.send(response)

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records == [], (
            f"ERROR log в success path: {[r.message for r in error_records]}; "
            "regression: error logging на success"
        )
        assert len(notifier.calls) == 1
        assert notifier.calls[0]["recipient"] == "chat-ok"

    @pytest.mark.asyncio
    async def test_multiple_failures_dont_break_subsequent_sends(self) -> None:
        """Failure на одном send() НЕ ломает channel для следующих.

        Контракт: каждый send() независим. После fail channel
        может принимать новые send() вызовы без re-initialization.
        """
        # Сначала failing
        failing = _FailingNotifier(RuntimeError("transient"))
        channel = ExpressReplyChannel(notifier=failing, default_chat_id="chat")

        await channel.send(_make_response(invocation_id="inv-fail-1"))
        assert failing._call_count == 1

        # Теперь OK notifier (тот же channel)
        ok_calls: list[Any] = []

        class _OK:
            async def send(self, **kwargs: Any) -> None:
                ok_calls.append(kwargs)

        # Подменяем notifier на OK (через internal — это тест,
        # production код так не делает)
        channel._notifier = _OK()  # type: ignore[assignment]

        await channel.send(_make_response(invocation_id="inv-ok-after-fail"))
        assert len(ok_calls) == 1, (
            "Channel сломался после failure — последующие send() не доставляются"
        )
