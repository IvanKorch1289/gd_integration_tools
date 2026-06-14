"""Capability-checked facade для SKB API service (S124 W1).

ADR-0207: extensions/core_entities/{orderkinds,orders}/services/*.py
импортируют ``APISKBService`` и ``get_skb_service`` из
``services.integrations.skb``.
"""

from __future__ import annotations

from src.backend.services.integrations.skb import (  # noqa: F401
    APISKBService,
    get_skb_service,
)

__all__ = ("APISKBService", "get_skb_service")
