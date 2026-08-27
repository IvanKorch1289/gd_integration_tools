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
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status

from src.backend.core.logging import get_logger
from src.backend.entrypoints.api.mobile.refresh_token_store import (
    get_refresh_token_store,
)
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
        timestamp=datetime.now(tz=UTC),
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

    D-AUDIT-9101 fix (cycle 91, API-P0-005): добавлен fail-CLOSED gate
    на feature flag ``mobile_demo_auth_enabled``. В production
    (default OFF) ЛЮБОЙ mobile:* токен → 401, потому что demo
    format не валидируется (fail-OPEN vulnerability). В dev_light
    / dev / staging (flag ON) — старое поведение сохранено для
    удобства разработки.

    Production JWT validation (when ``mobile_jwt_enabled`` flag is ON):
    uses ``MobileJwtVerifier`` (src/backend/core/auth/mobile_jwt.py) with
    mobile-specific claim validation (device_id UUID v4, tenant_id,
    jti, iss in whitelist, aud matches). Implemented in S46 W1.

    Demo mode (flag ON only): simple bearer format ``mobile:<user_id>:<token>``.

    Raises:
        HTTPException 401 if invalid/missing or demo auth disabled.

    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:]

    # D-AUDIT-9101: demo-auth fail-CLOSED gate. Если feature flag
    # выключен (default) — не пропускаем mobile:* токены вообще.
    try:
        from src.backend.core.config.features import feature_flags

        demo_auth_enabled = bool(
            getattr(feature_flags, "mobile_demo_auth_enabled", False)
        )
    except Exception as _:
        # Если feature_flags недоступен — fail-CLOSED (production safety).
        demo_auth_enabled = False

    if not demo_auth_enabled:
        # S46 W1 (cycle 261, ADR-0262/0264): real JWT validation path.
        # When mobile_jwt_enabled is ON, validate token via MobileJwtVerifier
        # before falling through to demo path. Default OFF keeps current
        # fail-closed 401 behavior for production safety.
        try:
            mobile_jwt_on = bool(
                getattr(feature_flags, "mobile_jwt_enabled", False)
            )
        except Exception as _:
            mobile_jwt_on = False

        if mobile_jwt_on:
            try:
                from src.backend.core.auth.jwt_backend import JwtBackend
                from src.backend.core.auth.mobile_jwt import (
                    JwtVerificationError,
                    MobileJwtVerifier,
                )

                # Lazy-init verifier from factory; in production this
                # should read JWT public key from secrets/Vault.
                verifier = MobileJwtVerifier(
                    backend=JwtBackend(),
                    issuer_whitelist=["gd-mobile-prod", "gd-mobile-staging"],
                    audience="gd-mobile-api",
                )
                ctx = await verifier.verify(token)
                return ctx.user_id
            except JwtVerificationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"JWT verification failed: {exc}",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc
            except Exception:
                # If JWT verifier itself is not configured (missing keys etc.),
                # fail-CLOSED — do not silently fall through to demo path.
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Mobile JWT verifier unavailable",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # JWT off or unavailable → fail-closed demo path (production safety).
        # S46 W1 + S55 W1: JWT validation IS implemented for mobile_jwt_enabled=True
        # path. This 401 only fires if BOTH demo_auth AND mobile_jwt are disabled.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Mobile auth disabled "
                "(FEATURE_MOBILE_DEMO_AUTH_ENABLED=false AND "
                "FEATURE_MOBILE_JWT_ENABLED=false). "
                "Enable FEATURE_MOBILE_JWT_ENABLED=true for JWT-based mobile auth."
            ),
        )

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


# S54 W2 (cycle 290): refresh token TTL — controls how long issued
# refresh tokens remain valid for rotation. Per OWASP, refresh tokens
# should outlive access tokens (15 min) by enough margin to allow
# legitimate re-auth but short enough to limit attack window.
_REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _extract_refresh_jti(refresh_token: str) -> str:
    """Extract jti-подобный segment из ``mobile-refresh:<user_id>:<jti>`` формата.

    Args:
        refresh_token: Refresh token issued by /auth/login.

    Returns:
        The third colon-separated segment (the jti-like identifier).

    Raises:
        ValueError: if token format is invalid or jti segment is empty.

    """
    parts = refresh_token.split(":", 2)
    if len(parts) < 3 or not parts[2]:
        raise ValueError("malformed refresh token")
    return parts[2]


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

    S54 W2 (cycle 290): refresh token tracked в ``InMemoryRefreshTokenStore``
    для rotation. Login → ``store.issue(user_id, device_id, jti, ttl)``.
    Refresh endpoint rotates: revoke old + issue new (reuse detection).
    """
    user_id = f"user_{device_id[:8]}"
    access = f"mobile:{user_id}:{uuid.uuid4().hex[:16]}"
    refresh = f"mobile-refresh:{user_id}:{uuid.uuid4().hex[:16]}"
    refresh_jti = _extract_refresh_jti(refresh)
    await get_refresh_token_store().issue(
        user_id=user_id,
        device_id=device_id,
        refresh_jti=refresh_jti,
        ttl_seconds=_REFRESH_TOKEN_TTL_SECONDS,
    )
    _log.info("mobile login: user_id=%s tenant=%s", user_id, tenant_id)
    return MobileTokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=900,  # 15 min
    )


@mobile_router.post("/auth/refresh", response_model=MobileTokenResponse)
async def refresh_token(
    refresh_token: str = Query(..., description="Refresh token from /auth/login"),
    device_id: str = Query(..., description="Device UUID (must match token)"),
    authorization: str | None = Header(default=None),
) -> MobileTokenResponse:
    """Exchange refresh token for new access + refresh token pair.

    S48 W2 (cycle 271, ADR-0267): refresh token endpoint.
    S49 W3 (cycle 275): JWT path integration.

    Implements OAuth2.0-compatible refresh flow.

    Production JWT path (when mobile_jwt_enabled is ON):
    - Authorization header MUST contain valid JWT access_token
    - Verified via MobileJwtVerifier (same auth as other endpoints)
    - Refresh proceeds only if JWT verification passes

    Demo mode (mobile_jwt_enabled OFF):
    - refresh_token + device_id in query params
    - No Authorization header required
    - Deterministic re-issue (matches login behavior)

    Args:
        refresh_token: Refresh token issued by /auth/login.
        device_id: Device UUID (for binding verification).
        authorization: Bearer JWT for production path (when enabled).

    Returns:
        MobileTokenResponse with new access + refresh tokens.

    Raises:
        HTTPException 401 if JWT invalid (production) or refresh token
            malformed (demo).
        HTTPException 400 if device_id doesn't match refresh token binding.

    """
    # S49 W3 (cycle 275): if JWT path enabled, verify Authorization header first
    try:
        from src.backend.core.config.features import feature_flags
        mobile_jwt_on = bool(
            getattr(feature_flags, "mobile_jwt_enabled", False)
        )
    except Exception:
        mobile_jwt_on = False

    if mobile_jwt_on:
        # Production JWT path: verify access_token via MobileJwtVerifier
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header (Bearer JWT required)",
                headers={"WWW-Authenticate": "Bearer"},
            )
        jwt_token = authorization[7:]
        try:
            from src.backend.core.auth.jwt_backend import JwtBackend
            from src.backend.core.auth.mobile_jwt import (
                JwtVerificationError,
                MobileJwtVerifier,
            )

            verifier = MobileJwtVerifier(
                backend=JwtBackend(),
                issuer_whitelist=["gd-mobile-prod", "gd-mobile-staging"],
                audience="gd-mobile-api",
            )
            ctx = await verifier.verify(jwt_token)
            # Use verified user_id from JWT (overrides refresh_token user_id)
            user_id = ctx.user_id
            # Verify device_id matches JWT claim
            if ctx.device_id != device_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Device ID does not match JWT binding",
                )
            # S55 W1 (cycle 291): JWT refresh token rotation via store.
            # JWT jti is FOREIGN (issued by external auth provider), not by us.
            # Use ``issue_if_new()`` for atomic first-use detection — if same
            # JWT jti is presented twice (replay attack), the second call
            # returns False and we reject with 401. This narrows the attack
            # window from "JWT TTL" (~15 min) to "single-use rotation".
            #
            # S56 W1 (cycle 293): OWASP family revocation. On reuse detected,
            # call ``revoke_family`` to invalidate ALL current-generation
            # tokens for this (user, device) pair. User must obtain a new
            # JWT from auth provider to refresh again.
            store = get_refresh_token_store()
            if not await store.issue_if_new(
                user_id=user_id,
                device_id=device_id,
                refresh_jti=ctx.jti,
                ttl_seconds=_REFRESH_TOKEN_TTL_SECONDS,
            ):
                invalidated = await store.revoke_family(user_id, device_id)
                _log.warning(
                    "JWT refresh reuse detected (family revoked): user=%s "
                    "device=%s jti=%s tokens_invalidated=%d",
                    user_id, device_id, ctx.jti[:8], invalidated,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        "JWT already used for refresh. Family revoked. "
                        "Re-authentication required (obtain new JWT)."
                    ),
                    headers={"WWW-Authenticate": "Bearer"},
                )
            _log.info("mobile refresh via JWT: user_id=%s jti=%s", user_id, ctx.jti[:8])
            return MobileTokenResponse(
                access_token=f"mobile:{user_id}:{uuid.uuid4().hex[:16]}",
                refresh_token=f"mobile-refresh:{user_id}:{uuid.uuid4().hex[:16]}",
                expires_in=900,
            )
        except JwtVerificationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"JWT verification failed: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    # Demo mode: parse user_id from refresh token format
    if not refresh_token.startswith("mobile-refresh:"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token format",
        )
    parts = refresh_token.split(":", 2)
    if len(parts) < 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed refresh token"
        )
    user_id = parts[1]
    # Verify device_id matches user_id binding (user_<device_id[:8]>)
    expected_prefix = f"user_{device_id[:8]}"
    if user_id != expected_prefix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device ID does not match refresh token binding",
        )

    # S54 W2 (cycle 290): refresh token rotation via store.
    # Reuse detection: if old refresh token was already revoked (rotated),
    # attacker reusing stolen token → 401. This narrows the attack window
    # from "token lifetime" (30 days) to "rotation interval" (~15 min).
    #
    # S56 W1 (cycle 293): OWASP family revocation. On reuse detected,
    # call ``revoke_family`` to invalidate ALL current-generation tokens
    # for this (user, device) pair. User must re-login completely.
    old_jti = _extract_refresh_jti(refresh_token)
    store = get_refresh_token_store()
    if not await store.is_valid(user_id, device_id, old_jti):
        invalidated = await store.revoke_family(user_id, device_id)
        _log.warning(
            "mobile refresh reuse detected (family revoked): user=%s "
            "device=%s jti=%s tokens_invalidated=%d",
            user_id, device_id, old_jti[:8], invalidated,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Refresh token invalid (revoked or expired). "
                "Family revoked — re-login required."
            ),
        )
    # Rotate: revoke old, issue new
    await store.revoke(user_id, device_id, old_jti)
    new_access = f"mobile:{user_id}:{uuid.uuid4().hex[:16]}"
    new_refresh = f"mobile-refresh:{user_id}:{uuid.uuid4().hex[:16]}"
    new_jti = _extract_refresh_jti(new_refresh)
    await store.issue(
        user_id=user_id,
        device_id=device_id,
        refresh_jti=new_jti,
        ttl_seconds=_REFRESH_TOKEN_TTL_SECONDS,
    )
    _log.info("mobile refresh: user_id=%s rotated jti=%s", user_id, new_jti[:8])
    return MobileTokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
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
            last_seen_at=datetime.now(tz=UTC),
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
        last_sync_at=datetime.now(tz=UTC),
        changes=[],  # Production: query actual changes since `since`
        server_version=1,
    )
    _sync_states[user_id] = state
    return _wrap(state.model_dump(mode="json"))


@mobile_router.get("/health", response_model=CompressedResponse)
async def mobile_health() -> CompressedResponse:
    """Health check endpoint для mobile clients (liveness)."""
    return _wrap({"status": "ok", "ts": datetime.now(tz=UTC).isoformat()})


# ── Test helpers ────────────────────────────────────────────────────


def reset_mobile_state() -> None:
    """Reset all in-memory stores (для tests)."""
    _profiles.clear()
    _notifications.clear()
    _push_tokens.clear()
    _sync_states.clear()
    # S54 W2 (cycle 290): also reset refresh token rotation store
    # to avoid test cross-contamination (issue/revoke state).
    from src.backend.entrypoints.api.mobile import refresh_token_store

    store = refresh_token_store.get_refresh_token_store()
    # Clear all tokens by creating fresh instance via singleton reset.
    refresh_token_store._default_store = None
    _ = store  # keep ref to avoid unused-var lint; module-level reset suffices


def add_test_notification(user_id: str, notification: MobileNotification) -> None:
    """Add test notification (для tests)."""
    _notifications.setdefault(user_id, []).append(notification)


def get_mobile_router() -> APIRouter:
    """Return the mobile router instance."""
    return mobile_router
