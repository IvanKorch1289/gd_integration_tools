"""Middlewares package — pure ASGI слой между entrypoints и services."""

from __future__ import annotations

from src.backend.entrypoints.middlewares.versioning import APIVersion

__all__ = ("APIVersion",)
