"""Admin API service (Sprint 19 K5 W5b): RBAC + audit trail.

Wave tags:
    - s19/k5-w5b: AuthorizationGateway RBAC wiring + audit trail
    - s19/k5-w5c: admin-react pages (upcoming)

audit_callback pattern (same as RouteLoader):
    Callable[[dict[str, Any]], None] — receives event dicts.
"""

from src.backend.services.admin.api import AdminService  # noqa: F401 — re-export
from src.backend.services.admin.audit import emit_admin_action  # noqa: F401 — re-export
from src.backend.services.admin.sqladmin_setup import (
    register_admin,  # noqa: F401 — re-export
)

__all__ = ("AdminService", "emit_admin_action", "register_admin")
