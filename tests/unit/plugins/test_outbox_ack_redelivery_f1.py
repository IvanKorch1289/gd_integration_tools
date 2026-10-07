"""F-1 (CRITICAL): подтверждённое событие outbox доставлялось бесконечно.

`_ack` определял id строки по префиксу ``outbox_msg_id:`` внутри
``correlation_id``. Но `_pending_source` выбирал
``original_cid or f"outbox_msg_id:{m.id}"`` — а реальный correlation_id
есть у большинства сообщений, поэтому маркер вытеснялся, условие не
срабатывало, и ``mark_sent`` **не вызывался никогда**.

Последствия: строка навсегда оставалась ``status='processing'`` с
истекающим ``claimed_until``; sweeper возвращал её в ``pending``; то же
событие доставлялось снова и снова — дубликаты в Kafka/NATS и лавина на
брокере при **любом** событии с correlation_id, то есть практически
всегда.

Тест фиксирует решение об id как самостоятельный контракт: он не должен
зависеть от того, оказался ли маркер в correlation_id.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_SETUP = _ROOT / "src/backend/plugins/composition/lifecycle/outbox_setup.py"


def _load_setup() -> Any:
    """Загрузить модуль outbox_setup как модуль (не импортируя пакет).

    Returns:
        Модуль с функцией ``_resolve_outbox_msg_id``.

    """
    spec = importlib.util.spec_from_file_location("_outbox_setup_under_test", _SETUP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(**kwargs: Any) -> Any:
    """Собрать минимальный OutboxEvent.

    Args:
        **kwargs: Переопределяемые поля события.

    Returns:
        Экземпляр ``OutboxEvent``.

    """
    from src.backend.core.messaging.outbox import OutboxEvent

    return OutboxEvent(transport="kafka", action="orders.created", payload={}, **kwargs)


class TestResolveOutboxMsgId:
    """F-1: id строки не должен теряться внутри correlation_id."""

    def test_dedicated_field_wins_over_correlation_id(self) -> None:
        """Реальный correlation_id не должен вытеснять id строки.

        Именно этот случай ломал ack: correlation_id='abc-123' не начинается
        с маркера, поэтому mark_sent не вызывался.
        """
        module = _load_setup()
        event = _event(correlation_id="abc-123", outbox_msg_id=42)
        assert module._resolve_outbox_msg_id(event) == 42

    def test_legacy_marker_still_resolved(self) -> None:
        """События, созданные до правки, ack'аются по старому маркеру."""
        module = _load_setup()
        assert (
            module._resolve_outbox_msg_id(_event(correlation_id="outbox_msg_id:7")) == 7
        )

    def test_unresolvable_returns_none(self) -> None:
        """Без id и без маркера возвращается None, а не мусорный id."""
        module = _load_setup()
        assert module._resolve_outbox_msg_id(_event(correlation_id="abc-123")) is None
        assert module._resolve_outbox_msg_id(_event()) is None

    def test_malformed_marker_returns_none(self) -> None:
        """Битый маркер не должен ронять ack и не должен превращаться в id."""
        module = _load_setup()
        assert (
            module._resolve_outbox_msg_id(_event(correlation_id="outbox_msg_id:abc"))
            is None
        )


class TestClaimPopulatesMessageId:
    """F-1: адаптер claim обязан проставлять id строки в событие."""

    def test_pending_source_sets_outbox_msg_id(self) -> None:
        """Каждое claimed-событие несёт id своей строки outbox.

        Проверяется по исходнику: id должен попадать в OutboxEvent при
        построении, иначе ack снова останется без маршрута к строке.
        """
        source = _SETUP.read_text(encoding="utf-8")
        assert "outbox_msg_id=m.id" in source, (
            "F-1: _pending_source обязан проставлять outbox_msg_id=m.id — "
            "иначе ack не знает, какую строку помечать как sent"
        )
        assert "original_cid or " in source, (
            "F-1: маркер перестал быть обязательным — при наличии реального "
            "correlation_id он вытеснялся"
        )
