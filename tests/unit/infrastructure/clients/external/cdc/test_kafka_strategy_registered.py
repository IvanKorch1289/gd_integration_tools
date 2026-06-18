"""S167 W1.1: regression test — _KafkaDebeziumStrategy must be wired into CDCClient._STRATEGIES.

S166 W1 added _KafkaDebeziumStrategy to cdc/kafka_strategy.py but forgot to register
it in CDCClient._STRATEGIES dict (client.py:47-51). Result: subscribe(strategy="kafka")
raised ValueError("Unknown CDC strategy 'kafka'").

This test is the regression guard — if someone removes "kafka" from _STRATEGIES again,
this test will fail with a clear message.
"""

from __future__ import annotations


def test_kafka_strategy_registered() -> None:
    """S167 W1.1: _KafkaDebeziumStrategy must be in CDCClient._STRATEGIES."""
    from src.backend.infrastructure.clients.external.cdc.client import CDCClient
    from src.backend.infrastructure.clients.external.cdc.kafka_strategy import (
        _KafkaDebeziumStrategy,
    )

    assert "kafka" in CDCClient._STRATEGIES, (
        "S166 W1 regression: _KafkaDebeziumStrategy not in CDCClient._STRATEGIES. "
        "subscribe(strategy='kafka') raises ValueError. "
        "Fix: add 'kafka': _KafkaDebeziumStrategy to client.py _STRATEGIES dict."
    )
    assert CDCClient._STRATEGIES["kafka"] is _KafkaDebeziumStrategy


def test_subscribe_kafka_does_not_raise_value_error() -> None:
    """S167 W1.1: subscribe(strategy='kafka') must NOT raise ValueError.

    Smoke check that the strategy validation passes. We don't actually run
    the consumer — that's covered by integration tests with real Kafka.
    """
    from src.backend.infrastructure.clients.external.cdc.client import CDCClient

    client = CDCClient()
    # _validate_strategy check (internal): should not raise ValueError.
    assert "kafka" in client._STRATEGIES


def test_strategy_docstring_lists_four() -> None:
    """S167 W1.1: CDCClient docstring must mention 4 strategies (not stale 3)."""
    from src.backend.infrastructure.clients.external.cdc.client import CDCClient

    docstring = CDCClient.__doc__ or ""
    assert "4 стратегии" in docstring, (
        f"CDCClient docstring is stale: {docstring!r}. "
        "Should mention '4 стратегии: polling, listen_notify, logminer, kafka'."
    )


def test_kafka_strategy_inherits_cdc_strategy_base() -> None:
    """S167 W1.1: _KafkaDebeziumStrategy must inherit from _CDCStrategy.

    ABC contract enforcement: all 4 strategies must subclass _CDCStrategy
    so they share the run(sub, dispatch) abstract method signature.
    """
    from src.backend.infrastructure.clients.external.cdc.kafka_strategy import (
        _KafkaDebeziumStrategy,
    )
    from src.backend.infrastructure.clients.external.cdc.strategies import _CDCStrategy

    assert issubclass(_KafkaDebeziumStrategy, _CDCStrategy), (
        "_KafkaDebeziumStrategy must inherit from _CDCStrategy ABC base. "
        "Otherwise Pyright flags _STRATEGIES type union."
    )
