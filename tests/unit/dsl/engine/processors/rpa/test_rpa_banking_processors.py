"""``rpa_banking.py`` — покрытие ``process()`` 5 процессоров (cycle 172, C5).

До cycle 172 все 5 процессоров покрывались только round-trip'ом
(``to_spec()``) — ветка ``process()`` (capability-гейт + запись
свойств в exchange) оставалась без тестов.

Проверяется для каждого процессора:

* ``auth_check`` → True → ожидаемые свойства выставлены;
* ``auth_check`` → False → ранний выход, ни одного свойства;
* валидация ctor (где она есть).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.processors.rpa_banking import (
    AppiumMobileProcessor,
    CitrixSessionProcessor,
    EmailDrivenProcessor,
    KeystrokeReplayProcessor,
    TerminalEmulator3270Processor,
)


def _exchange() -> MagicMock:
    """Заглушка Exchange."""
    exchange = MagicMock()
    exchange.in_message = MagicMock()
    exchange.in_message.body = {}
    exchange.set_property = MagicMock()
    exchange.fail = MagicMock()
    exchange.stop = MagicMock()
    return exchange


def _properties(exchange: MagicMock) -> dict[str, object]:
    """Свойства, записанные процессором в exchange."""
    return {call.args[0]: call.args[1] for call in exchange.set_property.call_args_list}


#: (процессор, ожидаемые свойства) — happy path.
_HAPPY_CASES: list[tuple[object, dict[str, object]]] = [
    (
        CitrixSessionProcessor(operation="click", session_id="sess-1"),
        {
            "rpa_backend": "citrix",
            "rpa_operation": "click",
            "rpa_session_id": "sess-1",
            "rpa_action": "rpa.citrix.invoke",
        },
    ),
    (
        TerminalEmulator3270Processor(host="mf.local", port=992, action="submit"),
        {
            "rpa_backend": "3270",
            "rpa_host": "mf.local",
            "rpa_port": 992,
            "rpa_action": "rpa.3270.submit",
        },
    ),
    (
        AppiumMobileProcessor(
            platform="android", app_package="com.bank.app", operation="tap"
        ),
        {
            "rpa_backend": "appium",
            "appium_platform": "android",
            "appium_app": "com.bank.app",
            "rpa_operation": "tap",
            "rpa_action": "rpa.appium.invoke",
        },
    ),
    (
        EmailDrivenProcessor(
            mailbox="Bank", subject_filter="statement", extract="csv_attachment"
        ),
        {
            "email_mailbox": "Bank",
            "email_subject_filter": "statement",
            "email_extract": "csv_attachment",
            "rpa_action": "email.poll_and_extract",
        },
    ),
    (
        KeystrokeReplayProcessor(script_name="login_seq"),
        {
            "rpa_backend": "keystroke",
            "keystroke_script": "login_seq",
            "rpa_action": "rpa.keystroke.replay",
        },
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processor", "expected"), _HAPPY_CASES, ids=lambda case: type(case).__name__
)
async def test_process_sets_properties(processor: object, expected: dict[str, object]) -> None:
    """auth_check → True: процессор выставляет ожидаемые свойства."""
    processor.auth_check = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    exchange = _exchange()

    await processor.process(exchange, MagicMock())  # type: ignore[attr-defined]

    assert _properties(exchange) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processor", "expected"), _HAPPY_CASES, ids=lambda case: type(case).__name__
)
async def test_process_denied_skips_properties(
    processor: object, expected: dict[str, object]
) -> None:
    """auth_check → False: ранний выход, ни одного свойства не выставлено."""
    processor.auth_check = AsyncMock(return_value=False)  # type: ignore[attr-defined]
    exchange = _exchange()

    await processor.process(exchange, MagicMock())  # type: ignore[attr-defined]

    exchange.set_property.assert_not_called()


def test_citrix_rejects_unknown_operation() -> None:
    """Неизвестная citrix-операция → ValueError."""
    with pytest.raises(ValueError, match="Unknown citrix operation"):
        CitrixSessionProcessor(operation="teleport", session_id="s")


def test_appium_rejects_unknown_platform() -> None:
    """Неизвестная платформа → ValueError."""
    with pytest.raises(ValueError, match="platform"):
        AppiumMobileProcessor(
            platform="symbian", app_package="com.bank.app", operation="tap"
        )


def test_required_capabilities_declared() -> None:
    """У всех 5 процессоров объявлен required_capability."""
    for processor, _ in _HAPPY_CASES:
        assert getattr(processor, "required_capability", None), (
            f"{type(processor).__name__} без required_capability"
        )
