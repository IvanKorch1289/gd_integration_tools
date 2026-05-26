"""Admin API service (Sprint 19 K5 W5b): RBAC + audit trail.

Wave tags:
    - s19/k5-w5b: AuthorizationGateway RBAC wiring + audit trail
    - s19/k5-w5c: admin-react pages (upcoming)

audit_callback pattern (same as RouteLoader):
    Callable[[dict[str, Any]], None] — receives event dicts.
"""

from src.backend.services.admin.api import AdminService
from src.backend.services.admin.audit import emit_admin_action

__all__ = ("AdminService", "emit_admin_action")
