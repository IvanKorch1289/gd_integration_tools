"""Mobile BFF router — main FastAPI router.

Endpoints:
* POST /mobile/auth/login — exchange device token for access/refresh
* GET  /mobile/profile — current user profile (compact)
* GET  /mobile/notifications — paginated, cursor-based
* POST /mobile/push-token — register FCM/APNs token
* GET  /mobile/sync — offline-first state diff
* GET  /mobile/health — health check (liveness для mobile clients)

All endpoints return CompressedResponse (uniform shape).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status

from src.backend.core.logging import get_logger
from src.backend.entrypoints.api.mobile.schemas import (
    CompressedResponse,
    CursorPage,
    MobileNotification,
    MobileProfile,
    MobileSyncState,
    MobileTokenResponse,
    PayloadOptimizer,
    PushTokenRequest,
)

__all__ = ("get_mobile_router", "mobile_router")

_log = get_logger(__name__)

mobile_router = APIRouter(
    prefix="/mobile/v1",
    tags=["mobile-bff"],
    responses={401: {"description": "Unauthorized"}},
)


def _wrap(data: Any, compressed: bool = True) -> CompressedResponse:
    """Wrap data в CompressedResponse с metadata."""
    return CompressedResponse(
        data=PayloadOptimizer.compact(data) if compressed else data,
        timestamp=datetime.now(tz=timezone.utc),
        request_id=str(uuid.uuid4()),
        compressed=compressed,
    )


# ── In-memory stores (для tests / demo; production uses DI services) ──


_profiles: dict[str, MobileProfile] = {}
_notifications: dict[str, list[MobileNotification]] = {}
_push_tokens: dict[str, list[PushTokenRequest]] = {}
_sync_states: dict[str, MobileSyncState] = {}


# ── Auth helper ─────────────────────────────────────────────────────


async def _verify_mobile_token(authorization: str | None) -> str:
    """Verify mobile bearer token, return user_id.

    Production: JWT validation с mobile-specific claims (device_id, tenant_id).
    For demo: simple bearer format ``mobile:<user_id>:<token>``.

    Raises:
        HTTPException 401 if invalid/missing.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:]
    if not token.startswith("mobile:"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mobile token format",
        )
    parts = token.split(":", 2)
    if len(parts) < 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed mobile token"
        )
    return parts[1]


# ── Endpoints ────────────────────────────────────────────────────────


@mobile_router.post("/auth/login", response_model=MobileTokenResponse)
async def login(
    device_id: str = Query(..., description="Mobile device UUID"),
    tenant_id: str = Query(default="default", description="Tenant context"),
) -> MobileTokenResponse:
    """Exchange device credentials for access/refresh tokens.

    Production: validate device_id, generate JWT, return short-lived tokens.
    For demo: just generate deterministic tokens.

    Token format: ``mobile:<user_id>:<token>`` (colon-separated, no
    underscore ambiguity in user_id).
    """
    user_id = f"user_{device_id[:8]}"
    access = f"mobile:{user_id}:{uuid.uuid4().hex[:16]}"
    refresh = f"mobile-refresh:{user_id}:{uuid.uuid4().hex[:16]}"
    _log.info("mobile login: user_id=%s tenant=%s", user_id, tenant_id)
    return MobileTokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=900,  # 15 min
    )


@mobile_router.get("/profile", response_model=CompressedResponse)
async def get_profile(
    authorization: str | None = Header(default=None),
) -> CompressedResponse:
    """Return current user profile (lightweight view)."""
    user_id = await _verify_mobile_token(authorization)
    profile = _profiles.get(
        user_id,
        MobileProfile(
            user_id=user_id,
            display_name=f"User {user_id[:8]}",
            avatar_url=None,
            tenant_id="default",
            role="user",
            last_seen_at=datetime.now(tz=timezone.utc),
            unread_count=len(_notifications.get(user_id, [])),
        ),
    )
    return _wrap(profile.model_dump(mode="json"))


@mobile_router.get("/notifications", response_model=CompressedResponse)
async def get_notifications(
    authorization: str | None = Header(default=None),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> CompressedResponse:
    """Paginated notifications (cursor-based, mobile-friendly)."""
    user_id = await _verify_mobile_token(authorization)
    all_notifs = _notifications.get(user_id, [])
    # Simple cursor = index
    start_idx = int(cursor) if cursor and cursor.isdigit() else 0
    end_idx = min(start_idx + limit, len(all_notifs))
    page_items = all_notifs[start_idx:end_idx]
    next_cursor = str(end_idx) if end_idx < len(all_notifs) else None
    page = CursorPage(
        items=[n.model_dump(mode="json") for n in page_items],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
        total_estimated=len(all_notifs),
    )
    return _wrap(page.model_dump(mode="json"))


@mobile_router.post("/push-token", response_model=CompressedResponse)
async def register_push_token(
    request: PushTokenRequest, authorization: str | None = Header(default=None)
) -> CompressedResponse:
    """Register FCM/APNs push token для device."""
    user_id = await _verify_mobile_token(authorization)
    _push_tokens.setdefault(user_id, []).append(request)
    _log.info(
        "push token registered: user=%s platform=%s device=%s",
        user_id,
        request.platform,
        request.device_id,
    )
    return _wrap({"registered": True, "platform": request.platform})


@mobile_router.get("/sync", response_model=CompressedResponse)
async def get_sync_state(
    authorization: str | None = Header(default=None),
    since: str | None = Query(default=None, description="Last sync ISO timestamp"),
) -> CompressedResponse:
    """Offline-first sync: return server changes since last sync."""
    user_id = await _verify_mobile_token(authorization)
    state = MobileSyncState(
        last_sync_at=datetime.now(tz=timezone.utc),
        changes=[],  # Production: query actual changes since `since`
        server_version=1,
    )
    _sync_states[user_id] = state
    return _wrap(state.model_dump(mode="json"))


@mobile_router.get("/health", response_model=CompressedResponse)
async def mobile_health() -> CompressedResponse:
    """Health check endpoint для mobile clients (liveness)."""
    return _wrap({"status": "ok", "ts": datetime.now(tz=timezone.utc).isoformat()})


# ── Test helpers ────────────────────────────────────────────────────


def reset_mobile_state() -> None:
    """Reset all in-memory stores (для tests)."""
    _profiles.clear()
    _notifications.clear()
    _push_tokens.clear()
    _sync_states.clear()


def add_test_notification(user_id: str, notification: MobileNotification) -> None:
    """Add test notification (для tests)."""
    _notifications.setdefault(user_id, []).append(notification)


def get_mobile_router() -> APIRouter:
    """Return the mobile router instance."""
    return mobile_router
