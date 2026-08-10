"""Mobile BFF (Backend for Frontend) — v21 §7.2.

Mobile-optimized API endpoints. Differs from admin (React) BFF:
* Compressed payloads (только mobile-relevant fields)
* Cursor-based pagination (not offset, mobile-friendly infinite scroll)
* Mobile-specific endpoints (profile, notifications, push tokens, sync state)
* Lightweight auth (mobile device tokens + refresh)
* Optimized for slow networks (3G/4G edge cases)

Architecture::

    Mobile App (iOS/Android)
            │
            │ HTTPS + Bearer token (short-lived)
            ▼
    ┌──────────────────┐
    │ Mobile BFF Router│  ← src/backend/entrypoints/api/mobile/router.py
    └──────┬───────────┘
           │
           ├──► Profile (lightweight user view)
           ├──► Notifications (paginated, cursor)
           ├──► Sync (offline-first state diff)
           ├──► Push tokens (FCM/APNs registration)
           └──► Compressed content (gzip-aware)
"""

from src.backend.entrypoints.api.mobile.router import get_mobile_router, mobile_router

__all__ = ("get_mobile_router", "mobile_router")
