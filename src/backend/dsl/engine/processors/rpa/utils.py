"""Shared utilities for RPA processors."""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.exchange import Exchange


def write_to_target(exchange: Exchange[Any], target: str, value: Any) -> None:
    """Write value to target location in exchange.

    Supports:
        - "property:<name>" — set exchange property
        - "body" — replace entire body
        - "body.<key>" — set nested key in body dict
        - "header:<name>" — set exchange header

    Args:
        exchange: The exchange object.
        target: Target location string.
        value: Value to write.
    """
    if target.startswith("property:"):
        exchange.set_property(target[len("property:") :], value)
        return
    if target == "body":
        exchange.in_message.body = value
        return
    if target.startswith("body."):
        key = target[len("body.") :]
        body = exchange.in_message.body
        if not isinstance(body, dict):
            body = {}
        body[key] = value
        exchange.in_message.body = body
        return
    if target.startswith("header:"):
        header_name = target[len("header:") :]
        if not hasattr(exchange.in_message, "headers"):
            exchange.in_message.headers = {}
        exchange.in_message.headers[header_name] = value
        return
    # Default: set as property
    exchange.set_property(target, value)
