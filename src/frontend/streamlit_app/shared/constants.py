"""Общие константы для всех страниц."""

from __future__ import annotations

VISUAL_PROCESSORS: dict[str, list[str]] = {
    "log": ["level", "message"],
    "validate": ["schema"],
    "transform": ["expression"],
    "dispatch_action": ["action"],
    "retry": ["max_attempts", "delay"],
    "redirect": ["mode", "status_code", "target_url", "url_source", "source_key"],
    "windowed_dedup": ["key_from", "window_seconds", "mode"],
    "windowed_collect": [
        "key_from",
        "window_seconds",
        "dedup_by",
        "dedup_mode",
        "inject_as",
    ],
    "multicast_routes": ["route_ids", "strategy", "on_error", "timeout"],
    "express_send": ["bot", "chat_id_from", "body_from"],
    "express_reply": ["bot", "body_from"],
    "notify": ["channel", "to", "template"],
}

PROCESSOR_ICONS: dict[str, str] = {
    "log": "📋",
    "validate": "✅",
    "transform": "🔄",
    "dispatch_action": "🎯",
    "retry": "🔁",
    "redirect": "↗️",
    "windowed_dedup": "🗂️",
    "windowed_collect": "📥",
    "multicast_routes": "📡",
    "express_send": "📨",
    "express_reply": "📩",
    "notify": "🔔",
}

PROCESSOR_COLORS: dict[str, str] = {
    "log": "blue",
    "validate": "green",
    "transform": "orange",
    "dispatch_action": "red",
    "retry": "yellow",
    "redirect": "gray",
    "windowed_dedup": "purple",
    "windowed_collect": "violet",
    "multicast_routes": "teal",
    "express_send": "blue",
    "express_reply": "cyan",
    "notify": "orange",
}

__all__ = ["VISUAL_PROCESSORS", "PROCESSOR_ICONS", "PROCESSOR_COLORS"]
