"""Camel EIP / Streaming / Transport (часть) миксин для RouteBuilder.

Группа: wire_tap / split / aggregate / recipient_list / load_balance /
claim_check_in/out / normalize / resequence / multicast / sort /
scatter_gather / dynamic_route / translate / enrich / filter / transform /
express_* / telegram_* / composed_message / multicast_routes /
windowed_dedup / windowed_collect / tumbling_window / sliding_window /
session_window / group_by_key / exactly_once / durable_fanout /
purge_channel / sample / reply_to / schema_validate / cdc / sse_source /
protocol / transport.

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations


class CamelEIPMixin:
    """Поведенческий миксин EIP/streaming/transport для ``RouteBuilder``."""

    __slots__ = ()  
