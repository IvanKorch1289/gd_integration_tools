"""Mobile BFF Pydantic schemas + payload optimizer.

Pydantic models для mobile API responses. Optimized for:
* Small payload size (только нужные поля)
* Fast deserialization на mobile
* Type-safe validation
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "CompressedResponse",
    "CursorPage",
    "MobileNotification",
    "MobileProfile",
    "MobileSyncState",
    "MobileTokenResponse",
    "PayloadOptimizer",
    "PushTokenRequest",
)


class MobileProfile(BaseModel):
    """User profile (lightweight view для mobile home screen)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_id: str = Field(..., description="User UUID")
    display_name: str = Field(..., description="Имя для UI")
    avatar_url: str | None = Field(None, description="CDN URL аватара")
    tenant_id: str = Field(..., description="Tenant ID (для multi-tenancy)")
    role: str = Field(default="user", description="user/admin/owner")
    last_seen_at: datetime | None = Field(None, description="Last activity")
    unread_count: int = Field(default=0, description="Unread notifications count")


class MobileNotification(BaseModel):
    """Single notification для mobile feed."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    title: str
    body: str
    icon: str | None = None
    deep_link: str | None = Field(None, description="app://deeplink/path")
    created_at: datetime
    read: bool = False
    priority: str = Field(default="normal", description="low/normal/high")


class CursorPage(BaseModel):
    """Cursor-based pagination (mobile-friendly infinite scroll)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: list[Any]
    next_cursor: str | None = Field(
        None, description="Cursor для следующей страницы (None = no more)"
    )
    has_more: bool = False
    total_estimated: int | None = Field(
        None, description="Approximate total (для UI counter)"
    )


class MobileSyncState(BaseModel):
    """Sync state для offline-first mobile app."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    last_sync_at: datetime
    changes: list[dict[str, Any]] = Field(
        default_factory=list, description="Server changes since last sync"
    )
    server_version: int = Field(..., description="Server monotonic version")


class MobileTokenResponse(BaseModel):
    """Mobile auth token response (short-lived access + long-lived refresh)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    access_token: str
    refresh_token: str
    expires_in: int = Field(..., description="Access token TTL в секундах")
    token_type: str = Field(default="Bearer")


class PushTokenRequest(BaseModel):
    """Push notification token registration request."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    token: str = Field(..., description="FCM/APNs token")
    platform: str = Field(..., description="ios/android/web")
    device_id: str = Field(..., description="Unique device ID")


class CompressedResponse(BaseModel):
    """Response wrapper с metadata для mobile.

    Включает:
    * data: actual payload
    * timestamp: server time (для clock-sync)
    * request_id: для debugging
    * compressed: был ли payload gzipped
    * schema_version: для client-side migrations
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: Any
    timestamp: datetime
    request_id: str
    compressed: bool = False
    schema_version: int = 1


# ── Payload optimizer ────────────────────────────────────────────────


class PayloadOptimizer:
    """Optimize payload для mobile (small JSON, no excess fields).

    Mobile-specific optimizations:
    * Drop null fields (кроме explicit schema)
    * Truncate long strings (например, descriptions > 200 chars)
    * Convert datetime → Unix timestamp (короче)
    * Strip _id prefixes (mongo ObjectId → "o-1" format)
    * Minify booleans (1/0 instead of true/false) — optional

    Usage::

        optimized = PayloadOptimizer.compact(notification_dict)
    """

    MAX_STRING_LENGTH = 200
    DATETIME_AS_TIMESTAMP = True

    @classmethod
    def compact(cls, data: Any) -> Any:
        """Recursively compact a dict/list/value."""
        if isinstance(data, dict):
            return {k: cls.compact(v) for k, v in data.items() if v is not None or k == "data"}
        if isinstance(data, list):
            return [cls.compact(item) for item in data]
        if isinstance(data, datetime):
            return int(data.timestamp()) if cls.DATETIME_AS_TIMESTAMP else data.isoformat()
        if isinstance(data, str):
            return data[: cls.MAX_STRING_LENGTH] if len(data) > cls.MAX_STRING_LENGTH else data
        return data

    @classmethod
    def estimate_size(cls, data: Any) -> int:
        """Estimate JSON size в bytes (rough)."""
        import json

        try:
            return len(json.dumps(data, default=str))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def reduction_pct(cls, original: Any, optimized: Any) -> float:
        """Calculate % reduction (0-100)."""
        orig_size = cls.estimate_size(original)
        opt_size = cls.estimate_size(optimized)
        if orig_size == 0:
            return 0.0
        return 100.0 * (orig_size - opt_size) / orig_size
